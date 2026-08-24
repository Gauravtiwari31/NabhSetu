"""The Provenance Ledger (Part 6, section 2.2.2).

Every fetch writes an append-only record whose hash chains to its predecessor:

    h_n = SHA256( h_{n-1} || canonical(record_n) )

so the collection history is tamper-evident. Change any historical record and
every subsequent hash stops verifying.

This is the artefact that makes the system deployable by a ministry, and it is
what `GET /v1/provenance/{index_id}` answers from.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

GENESIS = "0" * 64

# What the ledger records about a fetch. Deliberately excludes the response
# body: we keep the SHA-256 of the canonicalised payload on the quote instead,
# so a number can be traced to the exact bytes it came from without retaining
# third-party content indefinitely.
CHAINED_FIELDS = ["seq", "run_id", "source", "ladder_rung", "legal_basis",
                  "request_url_hash", "robots_directive_applied", "rate_limit_bucket",
                  "http_status", "outcome", "n_quotes", "fetched_at", "note"]


def canonical(record: Dict) -> str:
    """Deterministic serialisation. Sorted keys, no whitespace drift, UTF-8."""
    return json.dumps({k: record.get(k) for k in CHAINED_FIELDS},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def chain_hash(prev_hash: str, record: Dict) -> str:
    return hashlib.sha256((prev_hash + canonical(record)).encode("utf-8")).hexdigest()


def payload_hash(payload) -> str:
    """SHA-256 of a canonicalised raw payload, stored as `raw_hash` on a quote."""
    if isinstance(payload, (dict, list)):
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    else:
        blob = str(payload)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ProvenanceLedger:
    """Append-only, hash-chained fetch log."""

    def __init__(self, conn: sqlite3.Connection, run_id: str):
        self.conn = conn
        self.run_id = run_id

    def _tip(self):
        row = self.conn.execute(
            "SELECT seq, this_hash FROM ledger_provenance ORDER BY seq DESC LIMIT 1").fetchone()
        if row is None:
            return 0, GENESIS
        return int(row["seq"]), str(row["this_hash"])

    def record(self, *, source: str, ladder_rung: int, legal_basis: str, outcome: str,
               robots_directive: str = "NOT_APPLICABLE", request_url_hash: Optional[str] = None,
               rate_limit_bucket: Optional[str] = None, http_status: Optional[int] = None,
               n_quotes: int = 0, note: str = "") -> str:
        """Append one record and return its provenance_id.

        `outcome` is one of OK, ROBOTS_BLOCKED, HARD_BLOCK, CIRCUIT_OPEN, ERROR,
        KILL_SWITCH. A request that was never issued because robots.txt
        disallowed it is recorded just as carefully as one that succeeded --
        that is the point: we can prove months later what we did NOT do.
        """
        seq, prev = self._tip()
        rec = {
            "seq": seq + 1, "run_id": self.run_id, "source": source,
            "ladder_rung": ladder_rung, "legal_basis": legal_basis,
            "request_url_hash": request_url_hash,
            "robots_directive_applied": robots_directive,
            "rate_limit_bucket": rate_limit_bucket, "http_status": http_status,
            "outcome": outcome, "n_quotes": int(n_quotes),
            "fetched_at": datetime.now(timezone.utc).isoformat(), "note": note,
        }
        this = chain_hash(prev, rec)
        pid = str(uuid.uuid4())
        self.conn.execute(
            """INSERT INTO ledger_provenance
               (provenance_id, seq, run_id, source, ladder_rung, legal_basis,
                request_url_hash, robots_directive_applied, rate_limit_bucket,
                http_status, outcome, n_quotes, fetched_at, note, prev_hash, this_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, rec["seq"], rec["run_id"], rec["source"], rec["ladder_rung"],
             rec["legal_basis"], rec["request_url_hash"], rec["robots_directive_applied"],
             rec["rate_limit_bucket"], rec["http_status"], rec["outcome"], rec["n_quotes"],
             rec["fetched_at"], rec["note"], prev, this))
        self.conn.commit()
        return pid


def verify_chain(conn: sqlite3.Connection) -> Dict[str, object]:
    """Recompute the whole chain. Returns where it first breaks, if it does.

    This runs as a BLOCKING data-quality check before publication, and is the
    live demo for the governance slide.
    """
    rows = conn.execute(
        """SELECT seq, run_id, source, ladder_rung, legal_basis, request_url_hash,
                  robots_directive_applied, rate_limit_bucket, http_status, outcome,
                  n_quotes, fetched_at, note, prev_hash, this_hash
           FROM ledger_provenance ORDER BY seq ASC""").fetchall()
    prev = GENESIS
    broken: List[int] = []
    for r in rows:
        rec = {k: r[k] for k in CHAINED_FIELDS}
        expected = chain_hash(prev, rec)
        if r["prev_hash"] != prev or r["this_hash"] != expected:
            broken.append(int(r["seq"]))
        prev = r["this_hash"]
    return {
        "n_records": len(rows),
        "intact": not broken,
        "first_broken_seq": broken[0] if broken else None,
        "n_broken": len(broken),
        "tip_hash": prev,
    }
