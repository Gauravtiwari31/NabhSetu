from __future__ import annotations

from uuid import UUID

from app.sources.akasa.parser import parse_akasa
from app.sources.common.plugin import AirlineSitePlugin, SiteSpec
from app.sources.ota.catalog import OTA_PLUGINS

TERMS_NOTE = (
    "Public carrier website reviewed 2026-09-20 for SIH26056 MoSPI airfare-index research. "
    "Identified User-Agent only. robots.txt is fetched live and fail-closed. "
    "Disallowed paths are never requested. No circumvention, CAPTCHA solving, "
    "or egress rotation on access denial."
)

class AkasaSitePlugin(AirlineSitePlugin):
    def parse_payload(self, payload, query, source, collector, confidence, url: str = ""):
        parsed = parse_akasa(payload, query, source, collector, confidence, url=url)
        if parsed.observations:
            return parsed
        return super().parse_payload(payload, query, source, collector, confidence, url=url)


AKASA = AkasaSitePlugin(
    SiteSpec(
        source_id=UUID("00000000-0000-4000-a000-000000000011"),
        name="AkasaAir",
        carrier="QP",
        base_url="https://www.akasaair.com",
        marketing_path_template="/flight-booking/{origin}-to-{destination}",
        sitemap_url="https://www.akasaair.com/sitemap.xml",
        structured_feed=True,
        requires_javascript=True,
        browser_network_json=True,
        minimum_interval_seconds=8,
        terms_notes=TERMS_NOTE,
        parser_name="akasa_availability",
        parser_version="1.0.0",
        browser_widget="akasa",
    )
)

SPICEJET = AirlineSitePlugin(
    SiteSpec(
        source_id=UUID("00000000-0000-4000-a000-000000000012"),
        name="SpiceJet",
        carrier="SG",
        base_url="https://www.spicejet.com",
        blocked_paths=("/cgi-bin", "/api/v1", "/public/", "/externalBooking"),
        requires_javascript=False,
        browser_network_json=False,
        terms_notes=TERMS_NOTE + " Booking API and /externalBooking are robots-disallowed.",
    )
)

AIR_INDIA_EXPRESS = AirlineSitePlugin(
    SiteSpec(
        source_id=UUID("00000000-0000-4000-a000-000000000013"),
        name="AirIndiaExpress",
        carrier="IX",
        base_url="https://www.airindiaexpress.com",
        blocked_paths=("/flight-availability",),
        requires_javascript=False,
        browser_network_json=False,
        terms_notes=TERMS_NOTE + " /flight-availability is robots-disallowed and is never requested.",
    )
)

INDIGO = AirlineSitePlugin(
    SiteSpec(
        source_id=UUID("00000000-0000-4000-a000-000000000014"),
        name="IndiGo",
        carrier="6E",
        base_url="https://www.goindigo.in",
        static_html=True,
        embedded_json=True,
        requires_javascript=True,
        browser_network_json=True,
        terms_notes=TERMS_NOTE + " Collection proceeds only after robots.txt is readable and allows the path.",
    )
)

AIR_INDIA = AirlineSitePlugin(
    SiteSpec(
        source_id=UUID("00000000-0000-4000-a000-000000000015"),
        name="AirIndia",
        carrier="AI",
        base_url="https://www.airindia.com",
        static_html=True,
        embedded_json=True,
        requires_javascript=True,
        browser_network_json=True,
        terms_notes=TERMS_NOTE + " Collection proceeds only after robots.txt is readable and allows the path.",
    )
)

STAR_AIR = AirlineSitePlugin(
    SiteSpec(
        source_id=UUID("00000000-0000-4000-a000-000000000016"),
        name="StarAir",
        carrier="OG",
        base_url="https://www.starair.in",
        blocked_paths=("/content", "/Menudata", "/Widget"),
        requires_javascript=False,
        browser_network_json=False,
        terms_notes=TERMS_NOTE + " Widget/Menudata paths are robots-disallowed.",
    )
)

ALLIANCE_AIR = AirlineSitePlugin(
    SiteSpec(
        source_id=UUID("00000000-0000-4000-a000-000000000017"),
        name="AllianceAir",
        carrier="9I",
        base_url="https://www.allianceair.in",
        requires_javascript=False,
        browser_network_json=False,
        terms_notes=TERMS_NOTE + " robots.txt must be a machine-readable file; HTML responses are UNREADABLE.",
    )
)

PLUGINS: tuple[AirlineSitePlugin, ...] = (
    AKASA,
    SPICEJET,
    AIR_INDIA_EXPRESS,
    INDIGO,
    AIR_INDIA,
    STAR_AIR,
    ALLIANCE_AIR,
    *OTA_PLUGINS,
)

_BY_ID = {plugin.spec.source_id: plugin for plugin in PLUGINS}
_BY_NAME = {plugin.spec.name: plugin for plugin in PLUGINS}


def plugin_for(source_id=None, name: str | None = None) -> AirlineSitePlugin | None:
    if source_id is not None and source_id in _BY_ID:
        return _BY_ID[source_id]
    if name and name in _BY_NAME:
        return _BY_NAME[name]
    return None
