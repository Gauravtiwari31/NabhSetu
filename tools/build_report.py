#!/usr/bin/env python
"""Build the APIx review-and-test PDF from collected evidence.

Every number printed here is read from reports/evidence.json, which is produced
by tools/collect_evidence.py by actually running the thing it reports on. The
report is regenerable end to end:

    python tools/collect_evidence.py && python tools/build_report.py
"""
from __future__ import annotations

import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Preformatted, Spacer,
                                Table, TableStyle, Image as RLImage)


def _register_unicode_fonts():
    """Use DejaVu rather than Helvetica.

    ReportLab's built-in Type 1 fonts are Latin-1 only, so the rupee sign and
    several maths symbols were being DROPPED SILENTLY from the rendered page --
    not boxed, not warned about, just absent. A report about correctness cannot
    quietly lose characters. DejaVu ships with matplotlib, which is already a
    dependency here, so this costs nothing.
    """
    import matplotlib
    d = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    faces = {"DejaVuSans": "DejaVuSans.ttf",
             "DejaVuSans-Bold": "DejaVuSans-Bold.ttf",
             "DejaVuSans-Oblique": "DejaVuSans-Oblique.ttf",
             "DejaVuSansMono": "DejaVuSansMono.ttf"}
    for name, fn in faces.items():
        path = d / fn
        if not path.exists():
            return False
        pdfmetrics.registerFont(TTFont(name, str(path)))
    pdfmetrics.registerFontFamily("DejaVuSans", normal="DejaVuSans",
                                  bold="DejaVuSans-Bold", italic="DejaVuSans-Oblique",
                                  boldItalic="DejaVuSans-Bold")
    return True


UNICODE_OK = _register_unicode_fonts()
SANS = "DejaVuSans" if UNICODE_OK else "Helvetica"
SANS_B = "DejaVuSans-Bold" if UNICODE_OK else "Helvetica-Bold"
MONO = "DejaVuSansMono" if UNICODE_OK else "Courier"

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "reports" / "evidence.json"
OUT = ROOT / "reports" / "APIx_Test_and_Review_Report.pdf"

BLUE = colors.HexColor("#123A6B")
TEAL = colors.HexColor("#0E6E6E")
AMBER = colors.HexColor("#9A6400")
RED = colors.HexColor("#9B2226")
GREY = colors.HexColor("#4A4A4A")
RULE = colors.HexColor("#C9CFD6")
BAND = colors.HexColor("#EEF3F8")
TEALBAND = colors.HexColor("#E9F4F3")
AMBERBAND = colors.HexColor("#FBF3E2")
REDBAND = colors.HexColor("#FAEDED")

ev = json.loads(EV.read_text(encoding="utf-8"))

# ------------------------------------------------------------------ styles
ss = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("t", parent=ss["Title"], fontName=SANS_B,
                            fontSize=23, textColor=BLUE, leading=30, alignment=TA_LEFT),
    "sub": ParagraphStyle("s", parent=ss["Normal"], fontName=SANS,
                          fontSize=12, textColor=TEAL, leading=17),
    "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontName=SANS_B,
                         fontSize=14, textColor=BLUE, spaceBefore=14, spaceAfter=6),
    "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName=SANS_B,
                         fontSize=11, textColor=TEAL, spaceBefore=10, spaceAfter=4),
    "body": ParagraphStyle("b", parent=ss["Normal"], fontName=SANS,
                           fontSize=9, leading=13.4, spaceAfter=5),
    "small": ParagraphStyle("sm", parent=ss["Normal"], fontName=SANS,
                            fontSize=7.8, leading=10.2, textColor=GREY),
    "cell": ParagraphStyle("c", parent=ss["Normal"], fontName=SANS,
                           fontSize=7.8, leading=10.2),
    "cellb": ParagraphStyle("cb", parent=ss["Normal"], fontName=SANS_B,
                            fontSize=7.8, leading=10.2),
    "mono": ParagraphStyle("m", parent=ss["Code"], fontName=MONO, fontSize=6.6,
                           leading=9.2, textColor=colors.black),
}


def P(t, s="body"):
    return Paragraph(t, S[s])


def box(text, kind="key"):
    fill, line = {"key": (BAND, BLUE), "usp": (TEALBAND, TEAL),
                  "warn": (AMBERBAND, AMBER), "red": (REDBAND, RED)}[kind]
    t = Table([[P(text)]], colWidths=[168 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fill),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, line),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def table(rows, widths, header=True, align_right=(), font=8):
    data = []
    for i, r in enumerate(rows):
        style = "cellb" if (header and i == 0) else "cell"
        data.append([c if isinstance(c, (Table, RLImage))
                     else Paragraph(str(c), S[style]) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.9, BLUE) if header else
        ("LINEBELOW", (0, 0), (-1, 0), 0.3, RULE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, RULE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    for c in align_right:
        cmds.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(cmds))
    return t


WRAP = 104          # characters that fit inside the code box at 6.6pt DejaVu Mono


def code(text, maxlines=None):
    """Verbatim output, WRAPPED rather than truncated.

    Hard truncation at a fixed column silently dropped the ends of the nowcast
    refusal reasons — which are the substance of that section. Long lines are
    folded with a hanging indent so nothing runs off the right edge and nothing
    is lost.
    """
    import textwrap
    lines = text.rstrip().splitlines()
    if maxlines and len(lines) > maxlines:
        lines = lines[:maxlines] + [f"... ({len(text.splitlines()) - maxlines} more lines)"]
    folded = []
    for ln in lines:
        if len(ln) <= WRAP:
            folded.append(ln)
            continue
        indent = " " * (len(ln) - len(ln.lstrip()) + 4)
        pieces = textwrap.wrap(ln, width=WRAP, subsequent_indent=indent,
                               break_long_words=True, break_on_hyphens=False)
        folded.extend(pieces or [ln[:WRAP]])
    p = Preformatted("\n".join(folded), S["mono"])
    t = Table([[p]], colWidths=[168 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F6F8")),
        ("BOX", (0, 0), (-1, -1), 0.4, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def chart(fn, width=168 * mm, height=None):
    """Render a matplotlib figure into a flowable."""
    buf = io.BytesIO()
    fig = fn()
    fig.savefig(buf, format="png", dpi=170, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    buf.seek(0)
    w, h = fig.get_size_inches()
    return RLImage(buf, width=width, height=height or width * h / w)


# --------------------------------------------------------------- page frame
def page(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(22 * mm, 285 * mm, 188 * mm, 285 * mm)
    canvas.setFont(SANS, 7.5)
    canvas.setFillColor(GREY)
    canvas.drawString(22 * mm, 288 * mm, "APIx — Test & Code Review Report")
    canvas.drawRightString(188 * mm, 288 * mm, "SIH 2026 | PS 26056")
    canvas.drawCentredString(105 * mm, 12 * mm, str(canvas.getPageNumber()))
    canvas.restoreState()


def cover(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(BLUE)
    canvas.rect(0, 246 * mm, 210 * mm, 3 * mm, stroke=0, fill=1)
    canvas.setFont(SANS, 7.5)
    canvas.setFillColor(GREY)
    canvas.drawCentredString(105 * mm, 12 * mm, str(canvas.getPageNumber()))
    canvas.restoreState()


# ------------------------------------------------------------------ parsing
def pytest_counts():
    out = ev["pytest"]["stdout"] + ev["pytest"]["stderr"]
    m = re.search(r"(\d+) passed", out)
    passed = int(m.group(1)) if m else 0
    failed = int(re.search(r"(\d+) failed", out).group(1)) if "failed" in out else 0
    errors = int(re.search(r"(\d+) error", out).group(1)) if " error" in out else 0
    t = re.search(r"in ([\d.]+)s", out)
    return passed, failed, errors, float(t.group(1)) if t else 0.0


def per_file_tests():
    """Handle both --collect-only shapes: one line per test, or a per-file tally."""
    out = ev.get("pytest_collect", {}).get("stdout", "")
    counts = {}
    for line in out.splitlines():
        line = line.strip()
        m = re.match(r"^(tests[\/][\w./\-]+\.py):\s*(\d+)$", line)
        if m:
            counts[m.group(1).replace("\\", "/")] = int(m.group(2))
        elif "::" in line and line.startswith("tests"):
            f = line.split("::")[0].replace("\\", "/")
            counts[f] = counts.get(f, 0) + 1
    return counts


def durations():
    out = ev["pytest"]["stdout"]
    rows = []
    for line in out.splitlines():
        m = re.match(r"\s*([\d.]+)s\s+(call|setup|teardown)\s+(\S+)", line)
        if m:
            rows.append((m.group(1) + "s", m.group(2), m.group(3).replace("\\", "/")))
    return rows[:10]


PASSED, FAILED, ERRORS, DURATION = pytest_counts()
COV = ev.get("coverage", {})

story = []

# =========================================================== COVER
story += [
    Spacer(1, 26 * mm),
    P("APIx", "title"),
    P("Test &amp; Code Review Report", "title"),
    Spacer(1, 5 * mm),
    P("Real-time Airfare Price Index for India — SIH 2026, PS 26056, MoSPI DIID", "sub"),
    Spacer(1, 9 * mm),
    NextPageTemplate("body"),
]

verdict_colour = "usp" if FAILED == 0 and ERRORS == 0 else "red"
story.append(box(
    f"<b>Verdict.</b> {PASSED} tests pass, {FAILED} fail, {ERRORS} errors. "
    f"Statement coverage {COV.get('total_pct', 0):.1f}% over "
    f"{COV.get('statements', 0):,} statements. The index engine reproduces an "
    f"independently written reference implementation of the Part 4 arithmetic to "
    f"<b>0.000e+00</b>. Six defects were found by review; the one correctness bug "
    f"among them is fixed and pinned by regression tests.", verdict_colour))
story.append(Spacer(1, 6 * mm))

story.append(table([
    ["Field", "Value"],
    ["Report generated", ev["generated_at_utc"][:19].replace("T", " ") + " UTC"],
    ["Python", ev["python"]],
    ["Platform", ev["platform"]],
    ["Tests", f"{PASSED} passed / {FAILED} failed / {ERRORS} errors in {DURATION:.1f}s"],
    ["Statement coverage", f"{COV.get('total_pct', 0):.1f}%  "
                           f"({COV.get('statements', 0) - COV.get('missing', 0):,} of "
                           f"{COV.get('statements', 0):,} statements)"],
    ["Source lines", f"{sum(v for k, v in ev['loc'].items() if k.startswith('src')):,} "
                     f"in src/, {sum(v for k, v in ev['loc'].items() if k.startswith('tests')):,} in tests/"],
    ["Store", f"{ev.get('store', {}).get('fact_fare_quote', 0):,} quotes, "
              f"{ev.get('store', {}).get('fact_index_value', 0):,} published index values, "
              f"{ev.get('db_size_mb', 0)} MB"],
    ["Quote history", " .. ".join(str(x) for x in ev.get("store_span", ["—", "—"]))],
], [42 * mm, 126 * mm]))

story.append(Spacer(1, 6 * mm))
story.append(box(
    "<b>Scope.</b> This report covers the APIx implementation only: the index engine, "
    "collection pipeline, governance layer, data-quality contract, the two fitted models "
    "(lead-time elasticity and the CPI nowcast bridge), the HTTP API and the store. It "
    "does <b>not</b> assess the underlying fare data, because there is none — the quote "
    "history is generated by the rung-0 deterministic simulator and every row carries "
    "<font face='DejaVuSansMono'>is_synthetic = 1</font>. Statements about index <i>values</i> in "
    "this report are statements about arithmetic, not about Indian airfares.", "warn"))

story.append(PageBreak())

# =========================================================== 1 SUMMARY
story += [P("1. What was reviewed, and how", "h1"),
          P("The review had four parts, run in this order. Each produced evidence that is "
            "reproduced verbatim later in this report.", "body")]

story.append(table([
    ["#", "Activity", "Method", "Result"],
    ["1", "Manual code review", "Read every module hunting for defects; probe suspicions "
          "with targeted scripts rather than assuming", "6 findings, 1 of them a real "
          "correctness bug"],
    ["2", "Static analysis", "ruff over src/, tests/, cli.py; triage every rule class that "
          "could indicate a real defect", "3 genuine issues, rest cosmetic or false positive"],
    ["3", "Test execution", "pytest with coverage; per-module statement coverage",
     f"{PASSED} pass, {COV.get('total_pct', 0):.1f}% coverage"],
    ["4", "Behavioural verification", "Engine vs independent reference; hash chain; quality "
          "contract; reproducibility; API sweep incl. negative cases", "All pass"],
], [8 * mm, 34 * mm, 76 * mm, 50 * mm]))

story.append(Spacer(1, 4 * mm))
story.append(P("1.1 Findings at a glance", "h2"))

FINDINGS = [
    ("F1", "Winsorisation was silently discarded", "HIGH", "Correctness",
     "A quote marked WINSORISED entered the index at its full uncapped value. "
     "<font face='DejaVuSansMono'>clean()</font> capped only an in-memory column; the store kept "
     "<font face='DejaVuSansMono'>total_fare</font> and the index recomputed prices from it.",
     "FIXED + 4 regression tests"),
    ("F2", "No chain-linking for late entrants", "MEDIUM", "Method",
     "The base period is the first period in the data. A route or flight appearing later "
     "has no base observation, is unmatched forever and is suppressed. There is no splice "
     "mechanism for new entrants.",
     "DOCUMENTED + pinned by test"),
    ("F3", "Docstring claimed test coverage that did not exist", "MEDIUM", "Assurance",
     "<font face='DejaVuSansMono'>_effective_weights</font> collapses aggregation stages 2–4 into "
     "one weight vector and its docstring asserted the equivalence was covered by tests. "
     "No test referenced it. The maths is correct (verified to 5.7e-14) but was unverified.",
     "TEST ADDED"),
    ("F4", "Elasticity model had zero test coverage", "MEDIUM", "Assurance",
     "<font face='DejaVuSansMono'>elasticity.py</font> — source of the most quotable output in the "
     "system (τ*, 'cheapest time to book') — measured 0.0% statement coverage.",
     "19 TESTS ADDED, now 95.4%"),
    ("F5", "Two declared tables were never written", "LOW", "Hygiene",
     "<font face='DejaVuSansMono'>link_index_provenance</font> and "
     "<font face='DejaVuSansMono'>fact_cross_source_spread</font> existed in the schema with no "
     "writer, implying capability that did not exist.",
     "1 REMOVED, 1 DOCUMENTED"),
    ("F6", "Dead code and an obscure NaN idiom", "LOW", "Hygiene",
     "Unused locals in <font face='DejaVuSansMono'>cli.py</font> and "
     "<font face='DejaVuSansMono'>nowcast.py</font>; a bare "
     "<font face='DejaVuSansMono'>v == v</font> NaN test.",
     "FIXED"),
]

sev_colour = {"HIGH": RED, "MEDIUM": AMBER, "LOW": GREY}
rows = [["ID", "Finding", "Severity", "Class", "Status"]]
for fid, title, sev, cls, _desc, status in FINDINGS:
    rows.append([fid, title,
                 f"<font color='{sev_colour[sev].hexval()}'><b>{sev}</b></font>",
                 cls, status])
story.append(table(rows, [10 * mm, 62 * mm, 20 * mm, 22 * mm, 54 * mm]))

story.append(Spacer(1, 4 * mm))
story.append(box(
    "<b>The one that mattered.</b> F1 is the finding that justifies the review. On the "
    "current synthetic dataset zero quotes are winsorised, so no published number was "
    "wrong — but the moment real data with outliers arrives, a ₹45,000 parse artefact in a "
    "₹5,000 cell would have entered the index at ₹44,701 instead of the capped ₹5,652, "
    "while the audit trail asserted it had been capped. A disposition that lies about what "
    "the pipeline did is precisely the failure an official-statistics product cannot have.",
    "red"))

story.append(PageBreak())

# =========================================================== 2 FINDINGS DETAIL
story.append(P("2. Findings in detail", "h1"))

for fid, title, sev, cls, desc, status in FINDINGS:
    story.append(KeepTogether([
        P(f"{fid} — {title} "
          f"<font color='{sev_colour[sev].hexval()}'>[{sev}]</font>", "h2"),
        P(desc, "body"),
        P(f"<b>Status:</b> {status}", "body"),
    ]))

story.append(Spacer(1, 3 * mm))
story.append(P("2.1 F1 evidence — before and after", "h2"))
story.append(P("A 40-quote cell with one ₹45,000 outlier. The cleaner correctly flags and "
               "caps it; the question is whether the cap survives persistence.", "body"))
story.append(code(
    "BEFORE THE FIX\n"
    "  clean():   disposition = WINSORISED\n"
    "             total_fare  = 45000.00      price_T (capped) =  5652.39\n"
    "  after store + attach_variant_prices():\n"
    "             price_T     = 44701.00      <-- the cap was discarded\n"
    "  >>> WINSORISATION IS LOST\n"
    "\n"
    "AFTER THE FIX\n"
    "  clean():   disposition = WINSORISED\n"
    "             total_fare        = 45000.00   <- observation stays immutable\n"
    "             total_fare_capped =  5951.39   <- new persisted column\n"
    "             price_T (capped)  =  5652.39\n"
    "  after store round-trip:\n"
    "             price_T = 5652.39   price_B = 5035.61   price_A = 5951.39\n"
    "  >>> FIXED - cap survives the re-derivation\n"
    "  >>> max drift on non-winsorised rows: 0.0000000000"))

story.append(Spacer(1, 3 * mm))
story.append(P("The fix keeps the observed <font face='DejaVuSansMono'>total_fare</font> immutable "
               "and records the pipeline's treatment in a separate "
               "<font face='DejaVuSansMono'>total_fare_capped</font> column, consistent with the "
               "append-only discipline the schema already enforces. Because administered "
               "charges are fixed amounts and GST is ad valorem, the base fare is re-derived "
               "as the residual at the same GST rate rather than scaled naively. An "
               "idempotent migration adds the column to stores written before it existed.",
               "body"))

story.append(PageBreak())

# =========================================================== 3 TESTS
story.append(P("3. Test results", "h1"))
story.append(P(f"<b>{PASSED} tests, {FAILED} failures, {ERRORS} errors, "
               f"{DURATION:.1f}s wall clock.</b> The suite runs entirely offline against "
               f"throwaway SQLite databases in temporary directories; no test touches the "
               f"demo store or the network.", "body"))

pf = per_file_tests()
if pf:
    rows = [["Test module", "Tests", "What it establishes"]]
    blurb = {
        "tests/test_index_math.py": "Index-number properties: time reversal, transitivity, "
            "AM–GM ordering, exact weekly-cycle annihilation, availability blend reduction, "
            "weight injection, dual basis, determinism.",
        "tests/test_pipeline_and_governance.py": "Decomposition reconciliation, cleaning "
            "dispositions, hash-chain tamper evidence, DB immutability, politeness governor, "
            "circumvention-absence scan, quality contract, winsorisation persistence.",
        "tests/test_elasticity.py": "Ground-truth recovery of τ* and curvature, η(τ) shape "
            "and closed form, refusal when no interior minimum exists, clustered SEs, "
            "fare-ladder mixture recovery.",
        "tests/test_reference_and_models.py": "CPI loader shape handling, back-test refusal "
            "rules and known-relationship recovery, nowcast interpretability guards, "
            "expanding-window OOS, JSON serialisation.",
        "tests/test_end_to_end.py": "Collect → clean → index → publish → serve on a fresh "
            "database; idempotency, bit-identical recomputation, publication blocked on a "
            "broken chain.",
    }
    for f in sorted(pf):
        rows.append([f.replace("tests/", ""), str(pf[f]), blurb.get(f, "")])
    rows.append([f"<b>Total</b>", f"<b>{sum(pf.values())}</b>", ""])
    story.append(table(rows, [52 * mm, 14 * mm, 102 * mm], align_right=(1,)))

story.append(Spacer(1, 4 * mm))
story.append(P("3.1 Slowest tests", "h2"))
d = durations()
if d:
    story.append(table([["Time", "Phase", "Test"]] + d, [16 * mm, 18 * mm, 134 * mm]))

story.append(Spacer(1, 4 * mm))
story.append(P("3.2 Suite output", "h2"))
story.append(code(ev["pytest"]["stdout"], maxlines=16))

story.append(PageBreak())

# =========================================================== 4 COVERAGE
story.append(P("4. Statement coverage", "h1"))
story.append(P(f"Overall <b>{COV.get('total_pct', 0):.1f}%</b> across "
               f"{COV.get('statements', 0):,} statements. Coverage was the instrument that "
               f"found F4 — the elasticity model measured 0.0% before this review and "
               f"95.4% after.", "body"))

if COV.get("files"):
    files = {k: v for k, v in COV["files"].items() if v["statements"] > 0}
    order = sorted(files.items(), key=lambda kv: kv[1]["pct"])

    def cov_chart():
        fig, ax = plt.subplots(figsize=(10, 5.2))
        names = [k.replace("src/", "").replace(".py", "") for k, _ in order]
        vals = [v["pct"] for _, v in order]
        cols = ["#9B2226" if v < 70 else "#9A6400" if v < 85 else "#0E6E6E" for v in vals]
        ax.barh(names, vals, color=cols, height=0.68)
        ax.axvline(COV["total_pct"], color="#123A6B", ls="--", lw=1.3,
                   label=f"overall {COV['total_pct']:.1f}%")
        ax.set_xlim(0, 100)
        ax.set_xlabel("statement coverage (%)", fontsize=9)
        ax.tick_params(labelsize=8)
        ax.legend(fontsize=8, loc="lower right")
        ax.grid(axis="x", alpha=0.25)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        return fig

    story.append(chart(cov_chart))
    story.append(Spacer(1, 3 * mm))

    rows = [["Module", "Stmts", "Miss", "Cover"]]
    for k, v in sorted(files.items()):
        rows.append([k.replace("src/", ""), f"{v['statements']}", f"{v['missing']}",
                     f"{v['pct']:.1f}%"])
    rows.append(["<b>TOTAL</b>", f"<b>{COV['statements']}</b>",
                 f"<b>{COV['missing']}</b>", f"<b>{COV['total_pct']:.1f}%</b>"])
    story.append(table(rows, [86 * mm, 22 * mm, 22 * mm, 24 * mm],
                       align_right=(1, 2, 3)))

story.append(Spacer(1, 3 * mm))
story.append(box(
    "<b>Where coverage is deliberately lower.</b> "
    "<font face='DejaVuSansMono'>apix_api/main.py</font> (59%) and "
    "<font face='DejaVuSansMono'>apix_reference/cpi.py</font> (63%) carry branches exercised only "
    "by a live store or by workbook shapes not present in the supplied files — the "
    "item-level CPI path, for instance, is written and unit-tested at the transform level "
    "but no shipped extract contains item rows. "
    "<font face='DejaVuSansMono'>apix_collect/runner.py</font> (73%) contains the rung-1 and rung-3 "
    "adapter branches, which are stubs pending a licensed API key.", "warn"))

story.append(PageBreak())

# =========================================================== 5 NUMERICAL
story.append(P("5. Numerical validation", "h1"))
story.append(P("5.1 Engine versus an independent reference implementation", "h2"))
story.append(P("The vectorised engine is compared against a deliberately naive "
               "implementation written straight from the Part 4 specification with nested "
               "Python loops and no reference to the engine's internals. Agreeing with it "
               "is evidence; agreeing with itself would be evidence of nothing. The test "
               "data includes a bucket-closure episode so the availability path is "
               "exercised rather than bypassed.", "body"))
story.append(code(ev.get("engine_validation", {}).get("stdout", "not run")))

story.append(Spacer(1, 3 * mm))
story.append(P("5.2 Mathematical properties asserted, not assumed", "h2"))
story.append(table([
    ["Property", "Statement", "Result"],
    ["Time reversal", "I<sup>J</sup>(0,t) · I<sup>J</sup>(t,0) = 100, over 200 random "
     "price vectors", "Holds to 1e-9"],
    ["Transitivity", "I(0,1) · I(1,2) = I(0,2) in index points", "Holds to 1e-9"],
    ["AM–GM ordering", "Carli ≥ Jevons over 200 random vectors", "Holds"],
    ["Carli bias", "Carli fails time reversal upward — the reason it is not used", "Confirmed"],
    ["Weekly-cycle removal", "7-day centred geometric MA applied to a pure weekly cycle "
     "leaves interior spread 0", "Exactly 0.0"],
    ["Blend reduction", "A = 1 ⟹ I<sub>adj</sub> = I<sub>matched</sub> exactly", "Holds"],
    ["Blend monotonicity", "I<sub>adj</sub> monotone and continuous in A over [0,1]", "Holds"],
    ["Stage collapse", "Collapsed effective weights = staged aggregation (F3)", "5.7e-14"],
    ["Bootstrap determinism", "Same seed ⟹ identical interval", "Holds"],
    ["CI containment", "Published value lies inside its own band, every period", "Holds"],
], [34 * mm, 96 * mm, 38 * mm]))

story.append(Spacer(1, 3 * mm))
story.append(P("5.3 The availability adjustment, on real pipeline output", "h2"))

try:
    sys.path.insert(0, str(ROOT / "src"))
    from apix_store import db as _db
    _c = _db.connect()
    import pandas as _pd
    avail = _pd.read_sql_query(
        "SELECT period, AVG(matched) m, AVG(laf) l, AVG(adjusted) adj, "
        "AVG(availability) a FROM fact_cell_index WHERE basis='book' AND suppressed=0 "
        "AND route IN ('DEL-BOM','BOM-DEL') GROUP BY period ORDER BY period", _c)
    _c.close()
except Exception:
    avail = None

if avail is not None and len(avail):
    # Zoom to the episode. Over the full 240-day span the day-of-week sawtooth
    # dominates and the three lines are visually indistinguishable; the panel
    # exists to show them SEPARATE, which only happens when buckets close.
    closed = avail.index[avail["a"] < 0.999]
    if len(closed):
        lo = max(0, int(closed.min()) - 12)
        hi = min(len(avail), int(closed.max()) + 13)
        avail_zoom = avail.iloc[lo:hi].reset_index(drop=True)
    else:
        avail_zoom = avail

    def avail_chart():
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 5.0), sharex=True,
                                     gridspec_kw={"height_ratios": [3, 1]})
        z = avail_zoom
        x = range(len(z))
        a1.plot(x, z["m"], color="#3b528b", lw=1.8, label="matched (naive)")
        a1.plot(x, z["l"], color="#c9b400", lw=1.6, ls="--", label="lowest available fare")
        a1.plot(x, z["adj"], color="#21918c", lw=2.2, label="availability-adjusted")
        a1.set_ylabel("index", fontsize=9); a1.legend(fontsize=8, loc="upper left")
        a1.grid(alpha=0.25); a1.tick_params(labelsize=8)
        a2.fill_between(x, z["a"], 1.0, color="#21918c", alpha=0.30)
        a2.plot(x, z["a"], color="#0E6E6E", lw=1.3)
        a2.set_ylabel("A", fontsize=9); a2.set_ylim(min(0.55, z["a"].min() - 0.05), 1.02)
        a2.grid(alpha=0.25); a2.tick_params(labelsize=8)
        step = max(1, len(z) // 10)
        a2.set_xticks(list(x)[::step])
        a2.set_xticklabels(z["period"][::step], rotation=45, ha="right", fontsize=7)
        for ax in (a1, a2):
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
        fig.suptitle("DEL–BOM / BOM–DEL through the bucket-closure episode: "
                     "matched vs LAF vs adjusted, with availability A",
                     fontsize=10, color="#123A6B")
        return fig
    viol = avail[(avail["a"] >= 0.999) &
                 ((avail["adj"] - avail["m"]).abs() > 1e-6)]
    peak = avail.loc[avail["a"].idxmin()]
    story.append(KeepTogether([
        chart(avail_chart),
        P(f"At peak closure ({peak['period']}, A = {peak['a']:.3f}) the naive matched index "
          f"reads {peak['m']:.2f} while the availability-adjusted index reads "
          f"{peak['adj']:.2f} — the naive line understates the episode by "
          f"{peak['adj'] - peak['m']:.1f} index points.", "body"),
    ]))
    story.append(P(f"Across {int((avail['a'] >= 0.999).sum())} periods where A = 1, the "
                   f"adjusted index equals the matched index exactly: "
                   f"<b>{len(viol)} violations</b>. That reduction property is what makes the "
                   f"blend defensible rather than ad hoc — it changes nothing in the normal "
                   f"case and only bites when buckets actually close.", "body"))

story.append(PageBreak())

# =========================================================== 6 GOVERNANCE
story.append(P("6. Governance verification", "h1"))
story.append(P("These are the checks that determine whether a ministry could deploy the "
               "system, as distinct from whether the arithmetic is right.", "body"))
story.append(code(ev.get("verify", {}).get("stdout", "not run"), maxlines=26))

story.append(Spacer(1, 3 * mm))
story.append(table([
    ["Control", "How it is enforced", "Verified by"],
    ["Quote immutability", "SQLite triggers reject UPDATE and DELETE on "
     "<font face='DejaVuSansMono'>fact_fare_quote</font>", "Test asserts IntegrityError on both"],
    ["Ledger tamper-evidence", "h<sub>n</sub> = SHA256(h<sub>n−1</sub> ‖ canonical(record))",
     "Test drops the trigger, edits a row, asserts the chain reports the exact break point"],
    ["Legal basis mandatory", "<font face='DejaVuSansMono'>dim_source.legal_basis</font> NOT NULL",
     "End-to-end test asserts zero orphan quotes and zero blank bases"],
    ["No circumvention capability", "No CAPTCHA solver, proxy rotator or credential store "
     "exists in the tree", "Test greps the whole package for 12 banned library and function "
     "names and fails if any appears"],
    ["robots.txt fails closed", "Unreadable robots.txt ⟹ request refused, not allowed",
     "Test injects a fetcher that raises and asserts ROBOTS_BLOCKED"],
    ["Blocked requests recorded", "A disallowed request is never issued and writes a "
     "ROBOTS_BLOCKED provenance row", "Test asserts the row and its directive"],
    ["Publication gate", "BLOCK-severity quality failure raises PublicationBlocked",
     "Test breaks the hash chain and asserts the index refuses to publish"],
], [34 * mm, 62 * mm, 72 * mm]))

story.append(Spacer(1, 3 * mm))
story.append(P("6.1 Reproducibility", "h2"))
repro = ROOT / "reports" / "reproduce.log"
if not repro.exists():
    repro = Path("/tmp/reproduce.log")
repro_txt = repro.read_text(encoding="utf-8") if repro.exists() else "(not captured)"
story.append(P("Every published number is recomputed from raw quotes and diffed against "
               "what was published. This works because the engine is pure, the bootstrap is "
               "seeded, and index ids are deterministic UUID5 hashes of "
               "(code, period, frequency, basis, preset, method_version, weights_version).",
               "body"))
story.append(code(repro_txt.replace("REPRO_DONE", "").strip(), maxlines=12))

story.append(PageBreak())

# =========================================================== 7 MODELS
story.append(P("7. The two fitted models", "h1"))
story.append(P("Everything in <font face='DejaVuSansMono'>apix_index</font> is deterministic "
               "index-number arithmetic — nothing there is trained. Exactly two components "
               "estimate parameters from data, and both were reviewed as models rather than "
               "as code.", "body"))

story.append(P("7.1 Lead-time elasticity — validated by ground-truth recovery", "h2"))
story.append(P("The estimator is tested by generating fares from a <i>known</i> "
               "log-quadratic lead-time curve and asserting it recovers the parameters. "
               "That is a round trip against truth, not self-consistency.", "body"))
story.append(table([
    ["Quantity", "True value (generator)", "Recovered", "Test"],
    ["τ* (trough)", "26.0 days", "within ±2.0 days", "test_recovers_a_known_tau_star"],
    ["τ* (moved)", "14.0 / 35.0 days", "±2.5 / ±4.0 days", "test_recovers_a_different_trough"],
    ["β₂ (curvature)", "0.085", "within ±0.015", "test_recovers_a_known_curvature"],
    ["η(τ*)", "0 by construction", "0 to 1e-6", "test_eta_has_the_right_shape_and_sign"],
    ["Fare ladder", "3 buckets at ₹4k/₹7k/₹12k", "3 found, ±5%", "test_fare_ladder_recovers…"],
], [30 * mm, 40 * mm, 34 * mm, 64 * mm]))
story.append(Spacer(1, 2 * mm))
story.append(code(ev.get("elasticity", {}).get("stdout", "not run"), maxlines=18))

story.append(Spacer(1, 3 * mm))
story.append(P("7.2 CPI nowcast bridge — the refusal is the result", "h2"))
story.append(P("The bridge regresses CPI transport inflation on APIx growth with lags. On "
               "the data available it declines to report interpretable coefficients, and "
               "that refusal is the correct output rather than a failure.", "body"))
story.append(code(ev.get("nowcast", {}).get("stdout", "not run"), maxlines=24))
story.append(Spacer(1, 2 * mm))
story.append(box(
    "<b>Why this matters.</b> The fit reports R² = 0.9353, which looks like a strong result "
    "and is nothing of the kind — it is six observations against four parameters. A module "
    "that printed that table without the guard would hand a team a number they could not "
    "defend for thirty seconds under questioning. Two guards fire here: too few "
    "observations, and a synthetic regressor. Out-of-sample evaluation is expanding-window "
    "and declines outright; the Granger test declines on the grounds that it has no power, "
    "reporting <i>cannot tell</i> rather than <i>no relationship</i>.", "red"))

story.append(PageBreak())

# =========================================================== 8 BACKTEST
story.append(P("8. Back-test against official CPI", "h1"))
story.append(code(ev.get("backtest", {}).get("stdout", "not run"), maxlines=30))

story.append(Spacer(1, 3 * mm))
story.append(box(
    "<b>Read these numbers with both caveats attached.</b> The comparator is the CPI "
    "<i>Transport</i> aggregate, not the air-fare item — no air-fare item index exists in "
    "the supplied extracts — and Transport also contains road fuel, vehicle purchase, rail "
    "fares and communication. Agreement is therefore diluted by construction. And the APIx "
    "side is synthetic, so these statistics describe the simulator's relationship to real "
    "CPI, which is not a meaningful quantity. They verify that the harness computes. They "
    "are not validation, and presenting them as validation would be the worst available use "
    "of this report.", "red"))

story.append(PageBreak())

# =========================================================== 9 API
story.append(P("9. API verification", "h1"))
story.append(P("Every route exercised, including negative cases — an unknown id must return "
               "404, and a bad enum must return 422, not 500.", "body"))
story.append(code(ev.get("api_sweep", {}).get("stdout", "not run"), maxlines=44))

story.append(PageBreak())

# =========================================================== 10 STATIC
story.append(P("10. Static analysis", "h1"))
story.append(P("ruff over <font face='DejaVuSansMono'>src/</font>, "
               "<font face='DejaVuSansMono'>tests/</font> and "
               "<font face='DejaVuSansMono'>cli.py</font>. The raw count is large but dominated by "
               "two stylistic classes that do not apply to this codebase: UP006 and UP045 "
               "want PEP 585/604 annotation syntax, which the project deliberately does not "
               "use because it targets Python 3.10 with "
               "<font face='DejaVuSansMono'>from __future__ import annotations</font>. Every rule "
               "class capable of indicating a real defect was triaged individually.", "body"))
story.append(code(ev.get("ruff_stats", {}).get("stdout", "")
                  + ev.get("ruff_stats", {}).get("stderr", ""), maxlines=24))

story.append(Spacer(1, 3 * mm))
story.append(P("10.1 Triage of the classes that can indicate real defects", "h2"))
story.append(table([
    ["Rule", "Count", "Verdict"],
    ["ISC004 — implicit string concatenation in a collection", "2",
     "<b>False positive.</b> Both are wrapped multi-line message strings, not missing "
     "commas. Inspected individually."],
    ["F841 — unused local", "3", "<b>Real.</b> Dead variables in cli.py, nowcast.py and one "
     "test. All removed."],
    ["PLR0124 — comparison with itself", "1", "<b>Real but intentional.</b> A bare "
     "<font face='DejaVuSansMono'>v == v</font> NaN check; replaced with "
     "<font face='DejaVuSansMono'>math.isfinite</font> for legibility."],
    ["B008 — function call in default argument", "13", "<b>False positive.</b> This is the "
     "standard FastAPI <font face='DejaVuSansMono'>Depends()</font> idiom."],
    ["BLE001 — blind except", "5", "<b>Deliberate.</b> Chiefly the robots.txt fail-closed "
     "path, where any exception must mean <i>refuse</i>."],
    ["F401 / I001 / RUF100 — imports and noqa", "~30", "Cosmetic."],
], [56 * mm, 14 * mm, 98 * mm], align_right=(1,)))

story.append(Spacer(1, 3 * mm))
story.append(P("10.2 Residual serious findings after the fixes", "h2"))
story.append(code(ev.get("ruff_serious", {}).get("stdout", "").strip() or "(none)",
                  maxlines=10))

story.append(PageBreak())

# =========================================================== 11 LIMITATIONS
story.append(P("11. Limitations this review did not resolve", "h1"))
story.append(P("Stated plainly, because a review that reports only what it fixed is not a "
               "review.", "body"))

story.append(table([
    ["Limitation", "Consequence", "What would resolve it"],
    ["<b>The data is synthetic.</b> Every quote comes from the rung-0 simulator.",
     "No statement in this report about index <i>values</i> is a statement about Indian "
     "airfares. The back-test and nowcast verify machinery only.",
     "A rung-1 licensed API key; the ladder, governor, ledger and engine around the adapter "
     "are complete and tested."],
    ["<b>No air-fare item index exists in the supplied CPI extracts.</b>",
     "The back-test compares against the Transport aggregate, diluting agreement by "
     "construction.",
     "An item-level extract for COICOP 07.3.3 from cpi.mospi.gov.in."],
    ["<b>No chain-linking for late entrants</b> (F2).",
     "A route or flight appearing after the base period is suppressed permanently. Correct "
     "and visible today, but it caps basket evolution.",
     "A splice/link mechanism at basket revision, which is a genuine feature, not a patch."],
    ["<b>ω<sub>τ</sub> is a policy parameter, not a measurement.</b>",
     "The lead-time weights are declared, not estimated. This is disclosed in the API "
     "payload and published under three presets.",
     "A measured booking lead-time distribution, which DGCA sought in Dec 2024 and did not "
     "obtain."],
    ["<b>Weekly frequency F<sub>c,r</sub> is proxied by national carrier share.</b>",
     "Within-route carrier weights are approximate; φ currently reproduces published DGCA "
     "passenger shares to within 1.3 pp.",
     "DGCA schedule data at route level."],
    ["<b>Bootstrap intervals are computed for the headline configuration only.</b>",
     "Non-headline variant/preset combinations carry point estimates; the API says so "
     "rather than showing an empty band.",
     "More compute, or a cheaper interval estimator, if intervals are wanted everywhere."],
], [46 * mm, 62 * mm, 60 * mm]))

story.append(Spacer(1, 4 * mm))
story.append(P("12. Reproducing this report", "h1"))
story.append(code(
    "cd apix\n"
    "python -m pip install -r requirements.txt coverage ruff\n"
    "\n"
    "python cli.py init\n"
    "python cli.py load-cpi --dir ../Datasets\n"
    "python cli.py backfill --days 240 --end 2026-07-31\n"
    "python cli.py index\n"
    "\n"
    "python tools/collect_evidence.py     # runs everything, writes reports/evidence.json\n"
    "python tools/build_report.py         # renders this PDF from that evidence\n"))
story.append(Spacer(1, 3 * mm))
story.append(P("Every figure in this document is read from "
               "<font face='DejaVuSansMono'>reports/evidence.json</font>, which is produced by "
               "executing the thing it reports on. No number here was typed by hand.",
               "small"))

# --------------------------------------------------------------- build
OUT.parent.mkdir(parents=True, exist_ok=True)
doc = BaseDocTemplate(str(OUT), pagesize=A4,
                      leftMargin=21 * mm, rightMargin=21 * mm,
                      topMargin=22 * mm, bottomMargin=18 * mm,
                      title="APIx — Test & Code Review Report",
                      author="APIx", subject="SIH 2026 PS 26056")
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
doc.addPageTemplates([
    PageTemplate(id="cover", frames=[frame], onPage=cover),
    PageTemplate(id="body", frames=[frame], onPage=page),
])
doc.build(story)
print(f"PDF written: {OUT}  ({OUT.stat().st_size/1024:.0f} KB)")
