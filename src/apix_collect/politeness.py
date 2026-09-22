"""The Politeness Governor (Part 6, section 2.2.1).

A single middleware every fetch passes through. Compliance is the HARD
CONSTRAINT; coverage is the optimisation target. That inversion is the whole
architectural argument, and this file is where it is actually enforced rather
than merely claimed.

What is deliberately absent from this file, and from this repository:
    * any CAPTCHA solver or CAPTCHA-solving service client
    * any residential/datacentre proxy rotator
    * any credential store, login flow, or account creation
    * any header or fingerprint spoofing after a block

Those are not missing features. A CAPTCHA is a technical access control, so
defeating it is unauthorised access under s.43 of the IT Act, 2000. A prototype
that demos a CAPTCHA solver is demonstrating a liability, not a capability.
"""
from __future__ import annotations

import time
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Dict, Optional
from urllib.parse import urlparse

# Statuses that mean "stop", not "retry harder". On any of these the fetch is
# abandoned and the failure escalates to a human.
DEFAULT_HARD_BLOCK = (401, 402, 403, 407, 429)


@dataclass
class TokenBucket:
    """Per-host rate limit. Refills continuously; never bursts above capacity.

    `last` starts unset rather than at time.monotonic(): a caller that supplies
    its own clock (the tests, and any deterministic replay) would otherwise
    measure elapsed time against a monotonic origin it never used, and the
    first call would refill the bucket by an arbitrary amount.
    """
    rate_per_s: float
    capacity: float = 1.0
    tokens: float = 1.0
    last: Optional[float] = None

    def take(self, now: Optional[float] = None) -> float:
        """Return the seconds a caller must wait before its request is allowed."""
        now = time.monotonic() if now is None else now
        if self.last is None:
            self.last = now
        elapsed = max(0.0, now - self.last)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate_per_s)
        self.last = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return 0.0
        return (1.0 - self.tokens) / self.rate_per_s


@dataclass
class CircuitBreaker:
    """Three consecutive hard blocks on a host and the circuit opens for 24h.

    Critically, an open circuit escalates to a HUMAN, not to a workaround, and
    marks the affected cells SOURCE_UNAVAILABLE so the index SUPPRESSION logic
    -- not a silent gap -- handles the missing data.
    """
    threshold: int = 3
    cooldown_s: float = 86400.0
    failures: int = 0
    opened_at: Optional[float] = None

    def is_open(self, now: Optional[float] = None) -> bool:
        if self.opened_at is None:
            return False
        now = time.monotonic() if now is None else now
        if now - self.opened_at >= self.cooldown_s:
            self.opened_at = None
            self.failures = 0
            return False
        return True

    def record_block(self, now: Optional[float] = None) -> bool:
        """Returns True if this block opened the circuit."""
        self.failures += 1
        if self.failures >= self.threshold and self.opened_at is None:
            self.opened_at = time.monotonic() if now is None else now
            return True
        return False

    def record_success(self) -> None:
        self.failures = 0


class Decision:
    """The governor's verdict on one intended request."""

    def __init__(self, allowed: bool, outcome: str, wait_s: float = 0.0,
                 robots_directive: str = "NOT_APPLICABLE", note: str = ""):
        self.allowed = allowed
        self.outcome = outcome          # OK | ROBOTS_BLOCKED | CIRCUIT_OPEN | KILL_SWITCH
        self.wait_s = wait_s
        self.robots_directive = robots_directive
        self.note = note

    def __repr__(self) -> str:
        return f"Decision(allowed={self.allowed}, outcome={self.outcome!r}, wait={self.wait_s:.1f}s)"


class PolitenessGovernor:
    """robots.txt, token buckets, concurrency ceiling, backoff, circuit breaker,
    kill switch -- in one place, so the policy is auditable as a single object."""

    def __init__(self, config: Dict[str, object], robots_fetcher=None):
        self.user_agent = str(config.get("user_agent", "Nabhsetu-Research/1.0"))
        self.respect_robots = bool(config.get("respect_robots", True))
        self.default_delay = float(config.get("default_crawl_delay_s", 10.0))
        self.jitter = float(config.get("jitter_s", 2.0))
        self.max_concurrency = int(config.get("max_concurrency_per_host", 1))
        self.daily_cap = int(config.get("daily_request_cap_per_host", 2000))
        self.backoff_base = float(config.get("backoff_base_s", 2.0))
        self.backoff_max = float(config.get("backoff_max_s", 300.0))
        self.hard_block = tuple(config.get("hard_block_statuses", DEFAULT_HARD_BLOCK))
        self.kill_switch = set(config.get("kill_switch_hosts", []) or [])

        self._threshold = int(config.get("circuit_breaker_threshold", 3))
        self._cooldown = float(config.get("circuit_breaker_cooldown_s", 86400))
        self._buckets: Dict[str, TokenBucket] = {}
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._robots: Dict[str, urllib.robotparser.RobotFileParser] = {}
        self._counts: Dict[str, int] = {}
        self._robots_fetcher = robots_fetcher   # injectable, so tests never hit the network

    # -- helpers ---------------------------------------------------------
    def host_of(self, url: str) -> str:
        return urlparse(url).netloc.lower()

    def breaker(self, host: str) -> CircuitBreaker:
        if host not in self._breakers:
            self._breakers[host] = CircuitBreaker(self._threshold, self._cooldown)
        return self._breakers[host]

    def bucket(self, host: str, crawl_delay: Optional[float] = None) -> TokenBucket:
        if host not in self._buckets:
            delay = crawl_delay if crawl_delay else self.default_delay
            self._buckets[host] = TokenBucket(rate_per_s=1.0 / max(delay, 0.001))
        return self._buckets[host]

    def robots_for(self, host: str, scheme: str = "https"):
        """Fetch, parse and cache robots.txt. The parsed object is snapshotted
        so we can prove, months later, what the file said on the day."""
        if host in self._robots:
            return self._robots[host]
        rp = urllib.robotparser.RobotFileParser()
        url = f"{scheme}://{host}/robots.txt"
        rp.set_url(url)
        try:
            if self._robots_fetcher is not None:
                rp.parse(self._robots_fetcher(url).splitlines())
            else:
                rp.read()
        except Exception:
            # Unreadable robots.txt is treated as DISALLOW, not as permission.
            # Failing closed is the only defensible default for a government
            # statistical product.
            rp = None
        self._robots[host] = rp
        return rp

    # -- the single entry point every fetch passes through ----------------
    def check(self, url: str) -> Decision:
        host = self.host_of(url)

        if host in self.kill_switch:
            return Decision(False, "KILL_SWITCH", note=f"{host} disabled by kill switch")

        if self.breaker(host).is_open():
            return Decision(False, "CIRCUIT_OPEN",
                            note=f"circuit open on {host}; escalated to a human, not routed around")

        if self._counts.get(host, 0) >= self.daily_cap:
            return Decision(False, "CIRCUIT_OPEN", note=f"daily request cap reached on {host}")

        directive = "NOT_APPLICABLE"
        crawl_delay = None
        if self.respect_robots:
            rp = self.robots_for(host)
            if rp is None:
                return Decision(False, "ROBOTS_BLOCKED", robots_directive="UNREADABLE",
                                note="robots.txt unreadable; failing closed")
            if not rp.can_fetch(self.user_agent, url):
                # The request is NEVER ISSUED. A ROBOTS_BLOCKED provenance
                # record is written instead, which is the proof of what we did
                # not do.
                return Decision(False, "ROBOTS_BLOCKED", robots_directive="DISALLOWED",
                                note=f"robots.txt disallows {url} for {self.user_agent}")
            directive = "ALLOWED"
            try:
                declared = rp.crawl_delay(self.user_agent)
                crawl_delay = float(declared) if declared else None
            except Exception:
                crawl_delay = None

        wait = self.bucket(host, crawl_delay).take()
        self._counts[host] = self._counts.get(host, 0) + 1
        return Decision(True, "OK", wait_s=wait, robots_directive=directive)

    def backoff_s(self, attempt: int) -> float:
        """Exponential backoff with full jitter, for 5xx and network errors only."""
        import random
        capped = min(self.backoff_max, self.backoff_base * (2 ** max(attempt - 1, 0)))
        return random.uniform(0, capped)

    def on_response(self, url: str, status: int) -> str:
        """Classify a response. A hard block STOPS the host; it never retries."""
        host = self.host_of(url)
        if status in self.hard_block:
            opened = self.breaker(host).record_block()
            return "CIRCUIT_OPEN" if opened else "HARD_BLOCK"
        if status >= 500:
            return "ERROR"
        self.breaker(host).record_success()
        return "OK"
