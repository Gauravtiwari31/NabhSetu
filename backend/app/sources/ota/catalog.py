from __future__ import annotations

from uuid import UUID

from app.domain.enums import ReviewStatus, SourceType
from app.sources.common.plugin import AirlineSitePlugin, SiteSpec
from app.sources.ota.parser import parse_easemytrip_dom

REVIEW_DATE = "2026-09-20"
SAFEGUARDS = (
    "Identified SIH26056 research User-Agent; live robots.txt is fetched fail-closed; "
    "one request at a time; no CAPTCHA solving, access-control bypass, or rotate-on-block."
)


class OtaSitePlugin(AirlineSitePlugin):
    def parse_payload(self, payload, query, source, collector, confidence, url: str = ""):
        if self.spec.name == "EaseMyTrip":
            parsed = parse_easemytrip_dom(payload, query, source, collector, confidence)
            if parsed.observations:
                return parsed
        return super().parse_payload(payload, query, source, collector, confidence, url=url)


MAKE_MY_TRIP = OtaSitePlugin(
    SiteSpec(
        source_id=UUID("00000000-0000-4000-a000-000000000021"),
        name="MakeMyTrip",
        carrier=None,
        base_url="https://www.makemytrip.com",
        source_type=SourceType.OTA,
        requires_javascript=True,
        browser_network_json=True,
        automation_allowed=False,
        terms_review_status=ReviewStatus.DENIED,
        terms_url="https://www.makemytrip.com/legal/in/eng/user_agreement.html",
        terms_notes=(
            f"Reviewed {REVIEW_DATE}. Terms expressly prohibit robots, spiders, scrapers, "
            f"or automated copying without prior written permission. {SAFEGUARDS}"
        ),
        parser_name="ota_generic",
    )
)

YATRA = OtaSitePlugin(
    SiteSpec(
        source_id=UUID("00000000-0000-4000-a000-000000000022"),
        name="Yatra",
        carrier=None,
        base_url="https://www.yatra.com",
        source_type=SourceType.OTA,
        requires_javascript=True,
        browser_network_json=True,
        automation_allowed=False,
        terms_review_status=ReviewStatus.REVIEW_REQUIRED,
        terms_url="https://www.yatra.com/online/yatra-user-agreement.html",
        terms_notes=(
            f"Reviewed {REVIEW_DATE}. Terms prohibit obtaining information through means not "
            f"intentionally made available; no explicit research-scraping permission found. "
            f"Written review/permission required before automation. {SAFEGUARDS}"
        ),
        parser_name="ota_generic",
    )
)

EASE_MY_TRIP = OtaSitePlugin(
    SiteSpec(
        source_id=UUID("00000000-0000-4000-a000-000000000023"),
        name="EaseMyTrip",
        carrier=None,
        base_url="https://www.easemytrip.com",
        source_type=SourceType.OTA,
        requires_javascript=True,
        browser_network_json=True,
        minimum_interval_seconds=12,
        daily_request_limit=40,
        terms_review_status=ReviewStatus.APPROVED,
        terms_url="https://www.easemytrip.com/terms.html",
        terms_notes=(
            f"Reviewed {REVIEW_DATE}. Public terms contain no explicit automated-access ban; "
            f"current live robots.txt returns User-Agent: * / Allow: *. Approval is limited "
            f"to public anonymous flight search under these safeguards. {SAFEGUARDS}"
        ),
        browser_widget="easemytrip",
        dom_record_selector=".nw_listing_bx",
        parser_name="ota_dom_cards",
        parser_version="1.0.0",
    )
)

CLEARTRIP = OtaSitePlugin(
    SiteSpec(
        source_id=UUID("00000000-0000-4000-a000-000000000024"),
        name="Cleartrip",
        carrier=None,
        base_url="https://www.cleartrip.com",
        source_type=SourceType.OTA,
        blocked_paths=("/flights/search", "/flights/international/search", "/api/"),
        requires_javascript=True,
        browser_network_json=True,
        automation_allowed=False,
        terms_review_status=ReviewStatus.DENIED,
        terms_url="https://corporate.cleartrip.com/termsofuse.xhtml",
        terms_notes=(
            f"Reviewed {REVIEW_DATE}. Terms expressly prohibit robots, spiders, scrapers, "
            f"automated copying, and bypass of robots exclusions without written permission. "
            f"{SAFEGUARDS}"
        ),
        parser_name="ota_generic",
    )
)

IXIGO = OtaSitePlugin(
    SiteSpec(
        source_id=UUID("00000000-0000-4000-a000-000000000025"),
        name="Ixigo",
        carrier=None,
        base_url="https://www.ixigo.com",
        source_type=SourceType.OTA,
        blocked_paths=("/search/result/", "/flights/search", "/api/"),
        requires_javascript=True,
        browser_network_json=True,
        automation_allowed=False,
        terms_review_status=ReviewStatus.DENIED,
        terms_url="https://www.ixigo.com/about/terms-of-use/",
        terms_notes=(
            f"Reviewed {REVIEW_DATE}. Terms prohibit automated/non-human access, data mining, "
            f"robots, spiders, scrapers, and offline readers. {SAFEGUARDS}"
        ),
        parser_name="ota_generic",
    )
)

GOIBIBO = OtaSitePlugin(
    SiteSpec(
        source_id=UUID("00000000-0000-4000-a000-000000000026"),
        name="Goibibo",
        carrier=None,
        base_url="https://www.goibibo.com",
        source_type=SourceType.OTA,
        requires_javascript=True,
        browser_network_json=True,
        automation_allowed=False,
        terms_review_status=ReviewStatus.REVIEW_REQUIRED,
        terms_url="https://www.goibibo.com/info/user-agreement/",
        terms_notes=(
            f"Reviewed {REVIEW_DATE}. The accessible agreement does not clearly grant or deny "
            f"automated research collection; written review/permission is required. "
            f"{SAFEGUARDS}"
        ),
        parser_name="ota_generic",
    )
)

OTA_PLUGINS: tuple[OtaSitePlugin, ...] = (
    MAKE_MY_TRIP,
    YATRA,
    EASE_MY_TRIP,
    CLEARTRIP,
    IXIGO,
    GOIBIBO,
)
