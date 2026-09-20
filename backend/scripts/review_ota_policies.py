from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

os.environ["APIX_DATA_MODE"] = "live"
os.environ.setdefault("APIX_EGRESS_MODE", "direct")
os.environ.setdefault("APIX_ENVIRONMENT", "ota-policy-review")
os.environ.setdefault("APIX_API_KEY", "ota-policy-local")
os.environ.setdefault("APIX_HTTP_TIMEOUT_SECONDS", "45")
os.environ.setdefault("APIX_HTTP_CONNECT_TIMEOUT_SECONDS", "15")

from app.acquisition.discovery.robots import fetch_robots  # noqa: E402
from app.config.settings import get_settings  # noqa: E402
from app.domain.models import utcnow  # noqa: E402
from app.sources.ota.catalog import OTA_PLUGINS  # noqa: E402

REPORT_PATH = Path("data/ota-policy-review.json")


async def review() -> dict:
    get_settings.cache_clear()
    settings = get_settings()
    sources = []
    for plugin in OTA_PLUGINS:
        spec = plugin.spec
        robots = await fetch_robots(settings, spec.base_url)
        sources.append(
            {
                "source": spec.name,
                "base_url": spec.base_url,
                "terms_url": spec.terms_url,
                "terms_review_status": spec.terms_review_status.value,
                "automation_allowed": spec.automation_allowed,
                "terms_notes": spec.terms_notes,
                "robots_url": robots.robots_url,
                "robots_status": robots.status.value,
                "robots_http_status": robots.http_status,
                "robots_error": robots.error,
                "robots_disallow_paths": robots.disallow_paths,
                "robots_sitemaps": robots.sitemaps,
                "robots_allows_home": robots.can_fetch(
                    settings.identified_user_agent, spec.base_url + "/"
                ),
            }
        )
    return {
        "reviewed_at": utcnow().isoformat(),
        "user_agent": settings.identified_user_agent,
        "data_mode": settings.data_mode.value,
        "egress_mode": settings.egress_mode.value,
        "sources": sources,
    }


def main() -> None:
    payload = asyncio.run(review())
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
