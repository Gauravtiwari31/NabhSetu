from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = REPO_ROOT / "docs" / "APIx-Project-Usage-Guide.pptx"

W = Inches(13.333)
H = Inches(7.5)

NAVY = "0B1F3A"
NAVY_2 = "122D4F"
BLUE = "1473E6"
TEAL = "00A6A6"
SAFFRON = "F59E0B"
GREEN = "16A34A"
RED = "DC2626"
AMBER = "D97706"
INK = "172033"
SLATE = "526174"
MUTED = "718096"
PALE = "EEF4FA"
PALE_TEAL = "E6F7F7"
PALE_GREEN = "EAF8EF"
PALE_AMBER = "FFF6E5"
PALE_RED = "FDECEC"
WHITE = "FFFFFF"
LIGHT_LINE = "D9E2EC"
DARK_CODE = "071426"


def rgb(value: str) -> RGBColor:
    return RGBColor.from_string(value)


def set_fill(shape, color: str, transparency: int = 0) -> None:
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(color)
    shape.fill.transparency = transparency


def set_line(shape, color: str, width: float = 1) -> None:
    shape.line.color.rgb = rgb(color)
    shape.line.width = Pt(width)


def add_rect(slide, x, y, w, h, color: str, radius: bool = False, line: str | None = None):
    kind = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
    shape = slide.shapes.add_shape(kind, x, y, w, h)
    set_fill(shape, color)
    if line:
        set_line(shape, line)
    else:
        shape.line.fill.background()
    if radius:
        shape.adjustments[0] = 0.12
    return shape


def add_text(
    slide,
    text: str,
    x,
    y,
    w,
    h,
    *,
    size: float = 18,
    color: str = INK,
    bold: bool = False,
    font: str = "Aptos",
    align=PP_ALIGN.LEFT,
    valign=MSO_ANCHOR.TOP,
    margin: float = 0.03,
):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = Inches(margin)
    tf.margin_right = Inches(margin)
    tf.margin_top = Inches(margin)
    tf.margin_bottom = Inches(margin)
    tf.vertical_anchor = valign
    p = tf.paragraphs[0]
    p.alignment = align
    p.space_after = Pt(0)
    run = p.add_run()
    run.text = text
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = rgb(color)
    return box


def add_pill(slide, text: str, x, y, w, *, fill=PALE_TEAL, color=TEAL, size=10.5):
    shape = add_rect(slide, x, y, w, Inches(0.34), fill, radius=True)
    add_text(
        slide,
        text,
        x,
        y + Inches(0.015),
        w,
        Inches(0.3),
        size=size,
        color=color,
        bold=True,
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
        margin=0,
    )
    return shape


def add_card(
    slide,
    x,
    y,
    w,
    h,
    *,
    title: str,
    body: str,
    accent: str = TEAL,
    fill: str = WHITE,
    title_size: float = 16,
    body_size: float = 12.5,
):
    shape = add_rect(slide, x, y, w, h, fill, radius=True, line=LIGHT_LINE)
    add_rect(slide, x, y, Inches(0.07), h, accent, radius=True)
    add_text(
        slide,
        title,
        x + Inches(0.22),
        y + Inches(0.16),
        w - Inches(0.38),
        Inches(0.42),
        size=title_size,
        color=INK,
        bold=True,
    )
    add_text(
        slide,
        body,
        x + Inches(0.22),
        y + Inches(0.62),
        w - Inches(0.38),
        h - Inches(0.74),
        size=body_size,
        color=SLATE,
    )
    return shape


def add_code(slide, code: str, x, y, w, h, *, size: float = 11.5, title: str | None = None):
    add_rect(slide, x, y, w, h, DARK_CODE, radius=True)
    if title:
        add_text(
            slide,
            title,
            x + Inches(0.2),
            y + Inches(0.12),
            w - Inches(0.4),
            Inches(0.28),
            size=9.5,
            color="8BB8E8",
            bold=True,
        )
        top = y + Inches(0.48)
        height = h - Inches(0.58)
    else:
        top = y + Inches(0.18)
        height = h - Inches(0.3)
    add_text(
        slide,
        code,
        x + Inches(0.2),
        top,
        w - Inches(0.4),
        height,
        size=size,
        color="E9F2FF",
        font="Consolas",
    )


def add_stat(slide, value: str, label: str, x, y, w, *, accent=TEAL):
    add_rect(slide, x, y, w, Inches(1.05), WHITE, radius=True, line=LIGHT_LINE)
    add_text(
        slide,
        value,
        x + Inches(0.12),
        y + Inches(0.12),
        w - Inches(0.24),
        Inches(0.46),
        size=22,
        color=accent,
        bold=True,
        align=PP_ALIGN.CENTER,
    )
    add_text(
        slide,
        label,
        x + Inches(0.12),
        y + Inches(0.58),
        w - Inches(0.24),
        Inches(0.36),
        size=10,
        color=SLATE,
        bold=True,
        align=PP_ALIGN.CENTER,
    )


def base_slide(prs: Presentation, title: str, kicker: str, number: int):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.background
    bg.fill.solid()
    bg.fill.fore_color.rgb = rgb("F8FAFC")
    add_rect(slide, 0, 0, W, Inches(0.11), TEAL)
    add_text(
        slide,
        kicker.upper(),
        Inches(0.64),
        Inches(0.27),
        Inches(8.2),
        Inches(0.27),
        size=9.5,
        color=TEAL,
        bold=True,
    )
    add_text(
        slide,
        title,
        Inches(0.64),
        Inches(0.54),
        Inches(11.9),
        Inches(0.62),
        size=24,
        color=NAVY,
        bold=True,
    )
    add_rect(slide, Inches(0.64), Inches(1.22), Inches(0.72), Inches(0.055), SAFFRON)
    add_text(
        slide,
        "APIx • SIH26056 • 20 Sep 2026",
        Inches(0.66),
        Inches(7.13),
        Inches(5.4),
        Inches(0.2),
        size=8.5,
        color=MUTED,
    )
    add_text(
        slide,
        f"{number:02d}",
        Inches(12.25),
        Inches(7.08),
        Inches(0.42),
        Inches(0.25),
        size=9,
        color=MUTED,
        bold=True,
        align=PP_ALIGN.RIGHT,
    )
    return slide


def build_presentation() -> Presentation:
    prs = Presentation()
    prs.slide_width = W
    prs.slide_height = H
    prs.core_properties.title = "APIx — System built and setup completed"
    prs.core_properties.subject = "SIH26056 Real-Time Airfare Price Index for India"
    prs.core_properties.author = "APIx — SIH 2026"
    prs.core_properties.keywords = "APIx, SIH26056, MoSPI, airfare index, compliance, live"

    # 1 Cover
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.background
    bg.fill.solid()
    bg.fill.fore_color.rgb = rgb(NAVY)
    add_rect(slide, 0, 0, Inches(0.13), H, TEAL)
    add_rect(slide, Inches(0.13), 0, Inches(0.055), H, SAFFRON)
    add_pill(slide, "SIH 2026  •  PS SIH26056  •  MoSPI", Inches(0.72), Inches(0.7), Inches(3.55), fill=NAVY_2, color="9DE8E8")
    add_text(slide, "APIx", Inches(0.72), Inches(1.45), Inches(8.0), Inches(0.95), size=52, color=WHITE, bold=True)
    add_text(
        slide,
        "Real-Time Airfare Price Index for India",
        Inches(0.72),
        Inches(2.45),
        Inches(10.5),
        Inches(0.5),
        size=22,
        color="D9EAFE",
        bold=True,
    )
    add_text(
        slide,
        "System built, live setup completed, and how to operate it — including why a\n"
        "collection row can read denied / policy_denied / live without being a failure.",
        Inches(0.72),
        Inches(3.15),
        Inches(8.4),
        Inches(0.95),
        size=16,
        color="B9C9DC",
    )
    for i, (label, color) in enumerate(
        [("Compliance-first", TEAL), ("Live + mock isolated", BLUE), ("Honest coverage", SAFFRON)]
    ):
        add_pill(slide, label, Inches(0.72 + i * 2.35), Inches(4.45), Inches(2.2), fill=NAVY_2, color=color, size=11)
    add_text(slide, "Companion: docs/APIx-Project-Usage-Guide.md", Inches(0.72), Inches(6.55), Inches(7.5), Inches(0.3), size=13, color="8EA6C0", font="Consolas")
    add_text(slide, "20 SEPTEMBER 2026", Inches(0.72), Inches(6.95), Inches(3.2), Inches(0.28), size=11, color="8EA6C0", bold=True)

    # 2 Problem and product
    slide = base_slide(prs, "Problem statement and what APIx delivers", "Product", 2)
    add_card(
        slide,
        Inches(0.64),
        Inches(1.5),
        Inches(6.0),
        Inches(5.2),
        title="SIH26056 asks for",
        body=(
            "A near-real-time airfare price index for India: scrape permitted "
            "airline/OTA fares, clean and normalise them, compute APIx at daily / "
            "weekly / monthly frequencies for city-pairs and T+1/7/15/30/45, expose "
            "a dashboard and NSO/RBI API, and support a 30-day DGCA back-test.\n\n"
            "Hard constraint: no CAPTCHA solving, stealth, auth bypass, rotate-on-block, "
            "or robots circumvention. Blocked sources are recorded; another permitted "
            "source may be chosen. Fares are never fabricated."
        ),
        accent=BLUE,
        body_size=13.5,
    )
    add_card(
        slide,
        Inches(6.85),
        Inches(1.5),
        Inches(5.85),
        Inches(5.2),
        title="What this repository is",
        body=(
            "A greenfield platform at the repo root. Team_Tarang_SIH-26-main is "
            "reference-only and is not imported.\n\n"
            "Governed collectors, immutable ledger, versioned APIx-T engine, "
            "authenticated /v1 APIs, React operator dashboard, Docker mock + live "
            "overlay, and a live EaseMyTrip demonstration cell — with mock always "
            "labelled simulated and never mixed into a live series."
        ),
        accent=TEAL,
        fill=PALE_TEAL,
        body_size=13.5,
    )

    # 3 Built inventory
    slide = base_slide(prs, "Setup completed — working inventory", "Built", 3)
    tiles = [
        ("Acquisition", "Governor, registry, waterfall adapters, identified Playwright", TEAL),
        ("Sources", "7 airlines, 6 OTAs, isolated mock; EaseMyTrip approved", BLUE),
        ("Ledger", "SHA-256 provenance, supersedes_id, immutability guards", SAFFRON),
        ("Index", "Decimal Jevons + availability + Young; method v1.0.0", GREEN),
        ("Workers", "Scheduler, SKIP LOCKED collector, publisher", NAVY),
        ("Dashboard + API", "Eight operator pages; JSON / CSV / SDMX-JSON /v1", TEAL),
    ]
    for idx, (title, body, accent) in enumerate(tiles):
        col, row = idx % 3, idx // 3
        add_card(
            slide,
            Inches(0.64 + col * 4.15),
            Inches(1.5 + row * 2.55),
            Inches(3.95),
            Inches(2.35),
            title=title,
            body=body,
            accent=accent,
            title_size=16,
            body_size=13,
        )

    # 4 Pipeline
    slide = base_slide(prs, "End-to-end path: query to published APIx-T", "Architecture", 4)
    steps = [
        ("1", "FareQuery", "City-pair, T+ window, source"),
        ("2", "Governor", "ALLOW / DENY / REVIEW"),
        ("3", "Collectors", "HTTP then Playwright"),
        ("4", "Ledger", "Immutable + hashes"),
        ("5", "Quality", "ACCEPTED / WINSORISED"),
        ("6", "Engine", "Jevons → Young → APIx-T"),
    ]
    for idx, (num, title, body) in enumerate(steps):
        x = Inches(0.55 + idx * 2.12)
        add_rect(slide, x, Inches(1.55), Inches(1.98), Inches(1.85), WHITE, radius=True, line=LIGHT_LINE)
        add_pill(slide, num, x + Inches(0.12), Inches(1.7), Inches(0.4), fill=TEAL, color=WHITE, size=11)
        add_text(slide, title, x + Inches(0.12), Inches(2.18), Inches(1.75), Inches(0.35), size=14, color=INK, bold=True)
        add_text(slide, body, x + Inches(0.12), Inches(2.55), Inches(1.75), Inches(0.6), size=11, color=SLATE)
    add_card(
        slide,
        Inches(0.64),
        Inches(3.65),
        Inches(12.05),
        Inches(3.05),
        title="Rules that never bend",
        body=(
            "First published period is 100. Unmatched basket cells are suppressed, not imputed. "
            "Late entrants are not chain-linked. Coverage is reported honestly (one DEL–BOM T+7 "
            "cell of a 5×5 basket is ~24%). Mock quotes never enter a live publication. "
            "403 / CAPTCHA / policy denial stop that source — no IP rotation, no CAPTCHA solver, "
            "no User-Agent spoofing."
        ),
        accent=SAFFRON,
        fill=PALE_AMBER,
        body_size=15,
    )

    # 5 Compliance
    slide = base_slide(prs, "Compliance governor — fail closed before any fetch", "Policy", 5)
    add_card(
        slide,
        Inches(0.64),
        Inches(1.5),
        Inches(4.05),
        Inches(5.2),
        title="ALLOW",
        body="Short-lived lease. Rate slot reserved. Collectors may run with the identified research User-Agent on a permitted path.",
        accent=GREEN,
        fill=PALE_GREEN,
        body_size=15,
    )
    add_card(
        slide,
        Inches(4.85),
        Inches(1.5),
        Inches(4.05),
        Inches(5.2),
        title="DENY",
        body=(
            "No collector runs. Job status = denied. Result = policy_denied.\n\n"
            "Triggers: disabled source, automation_allowed=false, robots unreadable or disallowed, "
            "quota exhausted, 403/CAPTCHA circuit, mock source while live."
        ),
        accent=RED,
        fill=PALE_RED,
        body_size=14.5,
    )
    add_card(
        slide,
        Inches(9.06),
        Inches(1.5),
        Inches(3.64),
        Inches(5.2),
        title="REVIEW REQUIRED",
        body="Terms or robots review missing or stale. Same stop as DENY. Written review is required before automation is switched on.",
        accent=AMBER,
        fill=PALE_AMBER,
        body_size=15,
    )

    # 6 policy_denied row
    slide = base_slide(prs, "How to read denied / policy_denied / live", "Collection console", 6)
    add_text(
        slide,
        "This row is correct behaviour, not a broken scrape.",
        Inches(0.64),
        Inches(1.4),
        Inches(12.0),
        Inches(0.35),
        size=16,
        color=SLATE,
    )
    headers = [("When", 2.2), ("Query", 2.1), ("Status", 1.7), ("Result", 2.3), ("Label", 1.6)]
    x = Inches(0.64)
    y = Inches(1.9)
    for label, width in headers:
        add_rect(slide, x, y, Inches(width), Inches(0.42), NAVY, radius=False)
        add_text(slide, label, x, y, Inches(width), Inches(0.42), size=12, color=WHITE, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE, margin=0)
        x += Inches(width)
    values = [("20 Sept 2026, 8:21 am", 2.2), ("DEL-BOM T+7", 2.1), ("denied", 1.7), ("policy_denied", 2.3), ("live", 1.6)]
    x = Inches(0.64)
    y = Inches(2.32)
    for label, width in values:
        add_rect(slide, x, y, Inches(width), Inches(0.48), WHITE, radius=False, line=LIGHT_LINE)
        add_text(slide, label, x, y, Inches(width), Inches(0.48), size=12, color=INK, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE, margin=0)
        x += Inches(width)
    add_card(
        slide,
        Inches(0.64),
        Inches(3.05),
        Inches(6.05),
        Inches(3.65),
        title="What each field means",
        body=(
            "Status denied — JobStatus.DENIED; the governor stopped the job.\n"
            "Result policy_denied — typed CollectionStatus; no adapter continued.\n"
            "Label live — APIX_DATA_MODE=live. Mock fares were not substituted.\n\n"
            "Causes: denied OTA, unreadable robots, review_required terms, prior 403/CAPTCHA, or mock asked for while live."
        ),
        accent=RED,
        fill=PALE_RED,
        body_size=13,
    )
    add_card(
        slide,
        Inches(6.9),
        Inches(3.05),
        Inches(5.8),
        Inches(3.65),
        title="What to do next",
        body=(
            "Do not “fix” the denial with simulated fares.\n\n"
            "Select EaseMyTrip (approved OTA) on the same DEL–BOM T+7 query. A later success row can sit beside this denial. The published index uses only live, quality-accepted quotes."
        ),
        accent=GREEN,
        fill=PALE_GREEN,
        body_size=13.5,
    )

    # 7 Sources
    slide = base_slide(prs, "Source catalog — reviewed 20 Sep 2026", "Sources", 7)
    add_card(
        slide,
        Inches(0.64),
        Inches(1.45),
        Inches(6.05),
        Inches(3.35),
        title="OTA decisions",
        body=(
            "EaseMyTrip — APPROVED for anonymous public search (robots Allow *).\n"
            "MakeMyTrip, Cleartrip, ixigo — DENIED by terms.\n"
            "Yatra, Goibibo — REVIEW REQUIRED; automation off.\n\n"
            "Denied sources stay visible on Source health and cannot be selected in the collection console."
        ),
        accent=TEAL,
        body_size=13.5,
    )
    add_card(
        slide,
        Inches(6.9),
        Inches(1.45),
        Inches(5.8),
        Inches(3.35),
        title="Airline plugins",
        body=(
            "IndiGo, Air India, Air India Express, Akasa, SpiceJet, Star Air, Alliance Air.\n\n"
            "Live robots.txt is still fetched fail-closed. Yield is source-limited. EaseMyTrip is the reliable permitted source for a live demo."
        ),
        accent=BLUE,
        body_size=13.5,
    )
    add_card(
        slide,
        Inches(0.64),
        Inches(5.0),
        Inches(12.05),
        Inches(1.7),
        title="Identified User-Agent (never spoof a consumer browser)",
        body="APIx-Research-Bot/0.1 (+https://www.mospi.gov.in; SIH26056 airfare index research)",
        accent=NAVY,
        fill=PALE,
        body_size=15,
    )

    # 8 Index math
    slide = base_slide(prs, "APIx-T methodology v1.0.0", "Index", 8)
    add_card(
        slide,
        Inches(0.64),
        Inches(1.45),
        Inches(4.05),
        Inches(3.4),
        title="Jevons elementary",
        body="Geometric mean of matched price relatives. Money is Decimal. First period = 100. Late entrants are not chain-linked.",
        accent=TEAL,
        body_size=14,
    )
    add_card(
        slide,
        Inches(4.85),
        Inches(1.45),
        Inches(4.05),
        Inches(3.4),
        title="Availability blend",
        body="I_adj = I_matched^A · I_LAF^(1−A). At A=1 this equals the matched index. Sold-out quotes do not invent prices.",
        accent=BLUE,
        body_size=14,
    )
    add_card(
        slide,
        Inches(9.06),
        Inches(1.45),
        Inches(3.64),
        Inches(3.4),
        title="Young aggregation",
        body="Weighted arithmetic mean of surviving cells, then routes, then T+ windows. Unmatched weight is redistributed.",
        accent=SAFFRON,
        body_size=14,
    )
    add_stat(slide, "5 routes", "SEED BASKET", Inches(0.64), Inches(5.1), Inches(2.4), accent=NAVY)
    add_stat(slide, "T+1…45", "OFFICIAL WINDOWS", Inches(3.2), Inches(5.1), Inches(2.4), accent=TEAL)
    add_stat(slide, "n_min 5", "CELL GATE", Inches(5.76), Inches(5.1), Inches(2.4), accent=GREEN)
    add_stat(slide, "ω uniform", "LEAD PRESET", Inches(8.32), Inches(5.1), Inches(2.4), accent=SAFFRON)
    add_text(slide, "Basket: DEL-BOM, BOM-DEL, DEL-BLR, BOM-BLR, DEL-HYD   •   Weights: equal_seed until DGCA file", Inches(0.7), Inches(6.35), Inches(12), Inches(0.35), size=13, color=SLATE)

    # 9 Quality + ledger
    slide = base_slide(prs, "Immutable ledger and quality gate", "Storage", 9)
    add_card(
        slide,
        Inches(0.64),
        Inches(1.45),
        Inches(6.05),
        Inches(5.25),
        title="Append-only observations",
        body=(
            "Raw payloads, normalised fares, components, validation flags, and provenance links reject UPDATE/DELETE.\n\n"
            "Corrections insert a new row and set supersedes_id.\n\n"
            "Each entity carries a SHA-256 content hash. Publication runs store input and output hashes shown on the methodology page."
        ),
        accent=NAVY,
        body_size=15,
    )
    add_card(
        slide,
        Inches(6.9),
        Inches(1.45),
        Inches(5.8),
        Inches(5.25),
        title="Publication dispositions",
        body=(
            "ACCEPTED — enters the index.\n"
            "WINSORISED — Tukey/Hampel adjusted; still publishable.\n"
            "QUARANTINED — sold-out, stale, or suspect; kept in the ledger.\n"
            "EXCLUDED — does not enter APIx-T.\n\n"
            "Live and mock series are selected by data mode. They are never blended."
        ),
        accent=SAFFRON,
        fill=PALE_AMBER,
        body_size=15,
    )

    # 10 Dashboard + API
    slide = base_slide(prs, "Operator dashboard and NSO/RBI APIs", "Surfaces", 10)
    add_card(
        slide,
        Inches(0.64),
        Inches(1.45),
        Inches(6.05),
        Inches(5.25),
        title="http://localhost:5173",
        body=(
            "Index trend — level, coverage %, 90% interval.\n"
            "Heatmap — route × T+; blanks are coverage gaps.\n"
            "Elasticity — log-log across official windows.\n"
            "Fares — INR, live vs simulated chip.\n"
            "Sources — terms, robots, circuits.\n"
            "Collection — permitted source picker, job ledger.\n"
            "Methodology — versions and hashes.\n"
            "Back-test — unavailable until official files."
        ),
        accent=TEAL,
        body_size=14,
    )
    add_card(
        slide,
        Inches(6.9),
        Inches(1.45),
        Inches(5.8),
        Inches(5.25),
        title="http://localhost:8000  •  X-API-Key",
        body=(
            "GET /health  /v1/status  /v1/index  /v1/coverage\n"
            "GET /v1/elasticity  /v1/methodology  /v1/provenance\n"
            "GET /v1/exports/index.csv  .sdmx.json\n"
            "POST /collection-jobs  /v1/index/publish\n"
            "GET /fares/latest  /v1/backtest\n\n"
            "OpenAPI at /docs. Live payloads set is_simulated=false."
        ),
        accent=BLUE,
        body_size=14,
    )

    # 11 Live vs mock
    slide = base_slide(prs, "Live and mock are isolated modes", "Data modes", 11)
    add_card(
        slide,
        Inches(0.64),
        Inches(1.45),
        Inches(6.05),
        Inches(5.25),
        title="LIVE (presentation default)",
        body=(
            "Green banner. MockFareSource is disabled.\n"
            "Publisher reads only non-simulated quotes.\n"
            "EaseMyTrip is the approved OTA collectable.\n"
            "Denied OTAs remain visible, not selectable.\n"
            "A policy_denied job stays empty — no fixture fill."
        ),
        accent=GREEN,
        fill=PALE_GREEN,
        body_size=15,
    )
    add_card(
        slide,
        Inches(6.9),
        Inches(1.45),
        Inches(5.8),
        Inches(5.25),
        title="MOCK (offline fallback)",
        body=(
            "Amber banner: SIMULATED DATA — not measurements of Indian airfares.\n\n"
            "docker compose up --build with APIX_DATA_MODE=mock.\n\n"
            "Use only when live sites are unreachable. Never present mock numbers as official APIx."
        ),
        accent=AMBER,
        fill=PALE_AMBER,
        body_size=15,
    )

    # 12 Laptop live setup
    slide = base_slide(prs, "Setup completed — laptop live demo", "Run", 12)
    add_code(
        slide,
        "cd backend\n"
        "python -m pip install -e \".[live,test,docs]\"\n"
        "python -m playwright install chromium\n"
        "$env:APIX_DATA_MODE=\"live\"; $env:APIX_EGRESS_MODE=\"direct\"\n"
        "$env:APIX_API_KEY=\"change-me\"\n"
        "$env:APIX_DATABASE_URL=\"sqlite+aiosqlite:///./data/apix-live-demo.db\"\n"
        "python scripts\\live_demo.py\n"
        "python -m uvicorn app.main:app --host 127.0.0.1 --port 8000\n\n"
        "cd frontend; npm install; npm run dev",
        Inches(0.64),
        Inches(1.45),
        Inches(7.35),
        Inches(5.25),
        title="POWERSHELL",
        size=13,
    )
    add_card(
        slide,
        Inches(8.2),
        Inches(1.45),
        Inches(4.5),
        Inches(5.25),
        title="Verified 20 Sep 2026",
        body=(
            "EaseMyTrip DEL–BOM T+7\n"
            "130 live observations\n"
            "0 simulated\n"
            "APIx-T 100.00\n"
            "Coverage 24%\n"
            "First period base = 100\n\n"
            "Dashboard :5173  •  API :8000"
        ),
        accent=GREEN,
        fill=PALE_GREEN,
        body_size=15,
    )

    # 13 Docker
    slide = base_slide(prs, "Setup completed — Docker mock and live overlay", "Deploy", 13)
    add_code(
        slide,
        "# Safe default (simulated fares, labelled)\n"
        "docker compose up --build\n\n"
        "# Live presentation (Chromium in worker + API)\n"
        "docker compose -f docker-compose.yml -f docker-compose.live.yml up --build\n\n"
        "# Optional daily EaseMyTrip basket — do not use for a short demo\n"
        "docker compose -f docker-compose.yml -f docker-compose.live.yml --profile live-schedule up",
        Inches(0.64),
        Inches(1.45),
        Inches(12.05),
        Inches(3.35),
        title="COMPOSE",
        size=15,
    )
    add_card(
        slide,
        Inches(0.64),
        Inches(5.0),
        Inches(12.05),
        Inches(1.7),
        title="Live overlay behaviour",
        body="APIX_DATA_MODE=live. Scheduler is off unless live-schedule. Collect from the dashboard. shm_size=1gb for Chromium. Mock source seeded disabled.",
        accent=TEAL,
        body_size=15,
    )

    # 14 Operator sequence
    slide = base_slide(prs, "Operator sequence for a live walkthrough", "Demo", 14)
    demo = [
        "Confirm /health → data_mode=live, is_simulated=false",
        "Source health — EaseMyTrip approved; MMT/Cleartrip/ixigo denied",
        "Collect EaseMyTrip DEL-BOM T+7 (or explain a policy_denied row)",
        "Fare drill-down — INR, live chip, no simulated flag",
        "Publish index — trend 100.00, coverage honest and low",
        "Methodology hashes + back-test unavailable without official files",
    ]
    for idx, item in enumerate(demo):
        y = Inches(1.48 + idx * 0.82)
        add_pill(slide, str(idx + 1), Inches(0.72), y, Inches(0.48), fill=TEAL, color=WHITE, size=12)
        add_text(slide, item, Inches(1.4), y + Inches(0.02), Inches(11.1), Inches(0.5), size=18, color=INK, bold=idx in {0, 2})

    # 15 Evidence
    slide = base_slide(prs, "Evidence already on disk", "Proof", 15)
    add_stat(slide, "1,823", "EMA OTA FARES (15/15 CELLS)", Inches(0.64), Inches(1.5), Inches(4.0), accent=BLUE)
    add_stat(slide, "0", "SIMULATED IN THAT MATRIX", Inches(4.85), Inches(1.5), Inches(4.0), accent=GREEN)
    add_stat(slide, "130", "LIVE DEMO CELL", Inches(9.06), Inches(1.5), Inches(3.64), accent=TEAL)
    add_card(
        slide,
        Inches(0.64),
        Inches(2.85),
        Inches(12.05),
        Inches(3.8),
        title="Machine-readable artifacts",
        body=(
            "backend/data/ota-policy-review.json — live robots/terms review\n"
            "backend/data/ota-live-run-report.json — OTA matrix including policy denials for MMT/Cleartrip/ixigo\n"
            "backend/data/live-demo-report.json — one-cell EaseMyTrip collect + publish\n"
            "backend/data/apix-live-demo.db — presentation SQLite ledger\n"
            "docs/ota-source-review.md — human-readable decisions"
        ),
        accent=NAVY,
        body_size=16,
    )

    # 16 Tests
    slide = base_slide(prs, "Verification — tests never hit airline sites", "Quality", 16)
    add_code(
        slide,
        "cd backend\npytest\n\ncd frontend\nnpm test\n\npython scripts\\generate_usage_presentation.py",
        Inches(0.64),
        Inches(1.45),
        Inches(6.2),
        Inches(3.3),
        title="COMMANDS",
        size=16,
    )
    add_card(
        slide,
        Inches(7.05),
        Inches(1.45),
        Inches(5.65),
        Inches(3.3),
        title="What tests cover",
        body="Governor, parsers vs fixtures, index math, API jobs, mock isolation, live-mode mock disable, no-circumvention guard, dashboard banner and number formatting.",
        accent=GREEN,
        fill=PALE_GREEN,
        body_size=15,
    )
    add_card(
        slide,
        Inches(0.64),
        Inches(4.95),
        Inches(12.05),
        Inches(1.75),
        title="Official files when you have them",
        body="python -m app.cli import-dgca FILE --source-url URL   •   import-cpi   •   run-index   •   backtest --comparator dgca. Never paste invented official numbers.",
        accent=AMBER,
        fill=PALE_AMBER,
        body_size=15,
    )

    # 17 Gaps
    slide = base_slide(prs, "Honest remaining gaps — say these to judges", "Boundaries", 17)
    gaps = [
        ("30-day series", "A one-cell live collect is not a month of APIx-T."),
        ("DGCA / CPI files", "Back-test stays unavailable until checksummed public files are imported."),
        ("SIH portal pack", "Idea PPT template, 3–5 min video, team ID, public GitHub, consent."),
        ("Full basket", "Five routes × five windows; one cell is ~24% coverage."),
        ("Airline yield", "Several carrier sites return typed empty/denied under identified UA."),
        ("OTA letters", "MMT, Cleartrip, ixigo stay denied without written permission."),
    ]
    for idx, (title, body) in enumerate(gaps):
        col, row = idx % 3, idx // 3
        add_card(
            slide,
            Inches(0.64 + col * 4.15),
            Inches(1.45 + row * 2.6),
            Inches(3.95),
            Inches(2.4),
            title=title,
            body=body,
            accent=SAFFRON if row == 0 else AMBER,
            fill=PALE_AMBER,
            title_size=15,
            body_size=13,
        )

    # 18 Close
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.background
    bg.fill.solid()
    bg.fill.fore_color.rgb = rgb(NAVY)
    add_rect(slide, 0, 0, W, Inches(0.12), TEAL)
    add_text(slide, "Ready to demonstrate APIx", Inches(0.8), Inches(0.7), Inches(11.5), Inches(0.7), size=32, color=WHITE, bold=True)
    add_text(slide, "Live, labelled, fail-closed — coverage and denials are features", Inches(0.82), Inches(1.45), Inches(11), Inches(0.4), size=16, color="A9BED3")
    checklist = [
        ("1", "Start live mode"),
        ("2", "Show EaseMyTrip success"),
        ("3", "Explain policy_denied"),
        ("4", "Publish APIx-T 100"),
        ("5", "Show hashes + 24%"),
        ("6", "State remaining gaps"),
    ]
    for idx, (num, label) in enumerate(checklist):
        col, row = idx % 3, idx // 3
        x = Inches(0.84 + col * 4.03)
        y = Inches(2.2 + row * 1.45)
        add_rect(slide, x, y, Inches(3.55), Inches(1.15), NAVY_2, radius=True, line="294966")
        add_pill(slide, num, x + Inches(0.16), y + Inches(0.36), Inches(0.48), fill=TEAL, color=WHITE, size=12)
        add_text(slide, label, x + Inches(0.78), y + Inches(0.35), Inches(2.55), Inches(0.45), size=16, color=WHITE, bold=True)
    add_text(
        slide,
        "docs/APIx-Project-Usage-Guide.md   •   docs/APIx-Project-Usage-Guide.pptx   •   http://localhost:5173",
        Inches(0.84),
        Inches(5.45),
        Inches(11.5),
        Inches(0.4),
        size=14,
        color="C8D6E5",
        font="Consolas",
    )
    add_text(
        slide,
        "APIx  •  Real-Time Airfare Price Index for India  •  SIH26056",
        Inches(0.84),
        Inches(6.7),
        Inches(11),
        Inches(0.3),
        size=12,
        color="7891AB",
        bold=True,
    )
    return prs


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    presentation = build_presentation()
    presentation.save(OUTPUT)
    print(f"created {OUTPUT} with {len(presentation.slides)} slides")


if __name__ == "__main__":
    main()
