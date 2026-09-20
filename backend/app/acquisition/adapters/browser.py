from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import urlparse

from app.acquisition.adapters.results import (
    confidence_for,
    denied_result,
    from_outcome,
    robots_or_deny,
)
from app.acquisition.base import BaseCollector
from app.acquisition.discovery.robots import RobotsSnapshot
from app.acquisition.path_policy import request_permitted
from app.config import DataMode, Settings
from app.domain.enums import CollectionStatus, CollectorModality, HttpResponseCategory, SourceType
from app.domain.models import CollectionError, CollectionResult, SourceProfile, utcnow
from app.sources.catalog import plugin_for
from app.sources.common.fare_extract import ParseOutcome
from app.sources.common.html import looks_like_block, looks_like_challenge
from app.sources.common.plugin import BrowserSearchPlan


def _host_root(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _same_site(url: str, base_url: str) -> bool:
    host = _host_root(url)
    root = _host_root(base_url)
    return host == root or host.endswith("." + root)


def _payload_and_url(item: Any) -> tuple[Any, str]:
    if isinstance(item, dict) and "body" in item:
        return item.get("body"), str(item.get("url") or "")
    return item, ""


@dataclass
class BrowserCapture:
    url: str
    html: str = ""
    json_payloads: list[Any] = field(default_factory=list)
    status: CollectionStatus = CollectionStatus.NO_RESULTS
    message: str = ""
    http_status: int | None = 200


class BrowserRuntime:
    """One Chromium identity per process. Identified UA only. No stealth flags."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright = None
        self._browser = None
        self._context = None
        self.captures: dict[str, BrowserCapture] = {}

    def cache_key(self, source_id, query) -> str:
        return f"{source_id}:{query.origin}:{query.destination}:{query.travel_date.isoformat()}"

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def _ensure(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return None
        if self._context is not None:
            return self._context
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(
            user_agent=self.settings.identified_user_agent,
            locale="en-IN",
            viewport={"width": 1400, "height": 900},
            extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"},
        )
        return self._context

    async def capture(
        self,
        source: SourceProfile,
        plan: BrowserSearchPlan,
        robots: RobotsSnapshot | None,
        key: str,
    ) -> BrowserCapture:
        if key in self.captures:
            return self.captures[key]
        context = await self._ensure()
        if context is None:
            capture = BrowserCapture(
                url=plan.start_url,
                status=CollectionStatus.UNSUPPORTED,
                message="playwright is not installed",
            )
            self.captures[key] = capture
            return capture
        if robots is None or not robots.can_fetch(self.settings.identified_user_agent, plan.start_url):
            capture = BrowserCapture(
                url=plan.start_url,
                status=CollectionStatus.POLICY_DENIED,
                message="robots.txt does not allow the browser start URL",
            )
            self.captures[key] = capture
            return capture
        permitted, rule = request_permitted(plan.start_url, source)
        if not permitted:
            capture = BrowserCapture(
                url=plan.start_url,
                status=CollectionStatus.POLICY_DENIED,
                message=f"start URL blocked by policy: {rule}",
            )
            self.captures[key] = capture
            return capture

        page = await context.new_page()
        payloads: list[Any] = []
        blocked_hit = False
        challenge_hit = False
        http_status = 200

        async def _on_response(response) -> None:
            nonlocal blocked_hit, http_status
            url = response.url
            if not _same_site(url, source.base_url):
                return
            allowed, _ = request_permitted(url, source)
            robots_ok = robots is not None and robots.can_fetch(self.settings.identified_user_agent, url)
            if response.status == 403:
                try:
                    if response.request.resource_type == "document":
                        blocked_hit = True
                        http_status = 403
                except Exception:
                    pass
            if response.status == 429:
                http_status = 429
            content_type = (response.headers or {}).get("content-type", "")
            if "json" not in content_type.lower():
                return
            if not allowed or not robots_ok:
                return
            try:
                payloads.append({"url": url, "body": await response.json()})
            except Exception:
                return

        page.on("response", _on_response)
        try:
            response = await page.goto(
                plan.start_url,
                wait_until="domcontentloaded",
                timeout=self.settings.playwright_timeout_ms,
            )
            if response is not None:
                http_status = response.status
            if http_status == 403:
                blocked_hit = True
            await page.wait_for_timeout(2000)
            html = ""
            if not blocked_hit:
                try:
                    await _fill_search(page, plan, self.settings.playwright_timeout_ms)
                    await page.wait_for_timeout(2000)
                except Exception:
                    pass
            html = await page.content()
            bodies = list(payloads)
            if plan.dom_record_selector:
                try:
                    records = await page.locator(plan.dom_record_selector).all_inner_texts()
                except Exception:
                    records = []
                if records:
                    bodies.append(
                        {
                            "url": page.url,
                            "body": {
                                "origin": plan.origin_code,
                                "destination": plan.destination_code,
                                "travel_date": plan.travel_date.isoformat(),
                                "page_url": page.url,
                                "dom_records": records,
                            },
                        }
                    )
            if looks_like_challenge(html):
                challenge_hit = True
            if looks_like_block(html) and http_status >= 400:
                blocked_hit = True
            if challenge_hit:
                status = CollectionStatus.CAPTCHA_BLOCKED
                message = "Human-verification challenge observed"
            elif http_status == 429:
                status = CollectionStatus.RATE_LIMITED
                message = "HTTP 429 during browser session"
            elif blocked_hit or http_status == 403:
                status = CollectionStatus.BLOCKED
                message = "HTTP 403 or access-denied page during browser session"
            else:
                status = CollectionStatus.NO_RESULTS
                message = "Browser session completed without matching dated fares"
            capture = BrowserCapture(
                url=page.url,
                html=html,
                json_payloads=bodies,
                status=status,
                message=message,
                http_status=http_status,
            )
        except Exception as exc:
            name = type(exc).__name__
            if "Timeout" in name:
                status = CollectionStatus.NETWORK_ERROR
            else:
                status = CollectionStatus.TEMPORARY_FAILURE
            capture = BrowserCapture(
                url=plan.start_url,
                status=status,
                message=name,
                http_status=http_status,
            )
        finally:
            await page.close()
        self.captures[key] = capture
        return capture


_PICK_AIRPORT_JS = """
(code) => {
  const needle = String(code).toUpperCase();
  const items = [...document.querySelectorAll("li")].filter((el) => {
    const box = el.getBoundingClientRect();
    return box.width > 40 && box.height > 20;
  });
  const hit = items.find((el) =>
    (el.innerText || "").replace(/\\s+/g, " ").trim().toUpperCase().startsWith(needle + " ")
  );
  if (!hit) return false;
  hit.scrollIntoView({ block: "center" });
  hit.click();
  return true;
}
"""

_CLICK_CALENDAR_DAY_JS = """
(day) => {
  const wanted = String(day);
  const hit = [...document.querySelectorAll("button, td, [role='gridcell']")].find((el) => {
    const text = (el.innerText || "").trim();
    const box = el.getBoundingClientRect();
    return text === wanted && box.width > 8 && box.width < 80;
  });
  if (!hit) return false;
  hit.click();
  return true;
}
"""

_CLICK_CALENDAR_STRIP_JS = """
(day) => {
  const wanted = String(day);
  const hit = [...document.querySelectorAll("button, td, [role='gridcell'], div")].find((el) => {
    const text = (el.innerText || "").trim();
    const first = text.split("\\n")[0].trim();
    const box = el.getBoundingClientRect();
    return first === wanted && box.width > 20 && box.width < 140 && box.height > 20 && box.height < 160;
  });
  if (!hit) return false;
  hit.click();
  return true;
}
"""

_CLICK_SEARCH_FLIGHTS_JS = """
() => {
  const button = [...document.querySelectorAll("button")].find((el) => {
    return (el.innerText || "").trim() === "Search Flights";
  });
  if (!button) return false;
  button.click();
  return true;
}
"""

_NEXT_MONTH_JS = """
() => {
  const button = [...document.querySelectorAll("button")].find((el) => {
    const label = (el.getAttribute("aria-label") || "").trim();
    return /next month/i.test(label);
  });
  if (!button) return false;
  button.click();
  return true;
}
"""


async def _fill_akasa_widget(page, plan: BrowserSearchPlan, timeout_ms: int) -> bool:
    if await page.locator("#From").count() == 0 or await page.locator("#To").count() == 0:
        return False
    origin_code = (plan.origin_code or plan.origin_query[:3]).upper()
    destination_code = (plan.destination_code or plan.destination_query[:3]).upper()
    await page.locator("#From").click(timeout=timeout_ms)
    await page.wait_for_timeout(1600)
    await page.evaluate(_PICK_AIRPORT_JS, origin_code)
    await page.wait_for_timeout(400)
    await page.locator("#To").click(timeout=timeout_ms)
    await page.wait_for_timeout(1600)
    await page.evaluate(_PICK_AIRPORT_JS, destination_code)
    await page.wait_for_timeout(400)
    await page.locator("input[name='DepartureDate']").click(timeout=timeout_ms)
    await page.wait_for_timeout(700)
    if plan.travel_date.month != date.today().month or plan.travel_date.year != date.today().year:
        await _advance_calendar_month(page, plan.travel_date)
    await page.evaluate(_CLICK_CALENDAR_DAY_JS, plan.travel_date.day)
    await page.evaluate(_CLICK_SEARCH_FLIGHTS_JS)
    try:
        await page.wait_for_url("**/flight-search**", timeout=15000)
    except Exception:
        await page.evaluate(_CLICK_SEARCH_FLIGHTS_JS)
        try:
            await page.wait_for_url("**/flight-search**", timeout=10000)
        except Exception:
            await page.wait_for_timeout(8000)
    else:
        await page.wait_for_timeout(8000)
    if "flight-search" in (page.url or ""):
        await page.evaluate(_CLICK_CALENDAR_STRIP_JS, plan.travel_date.day)
        await page.wait_for_timeout(8000)
    return True


_PICK_EASEMYTRIP_AIRPORT_JS = """
(code) => {
  const needle = String(code).toUpperCase();
  const options = [...document.querySelectorAll("li")].filter((el) => {
    const box = el.getBoundingClientRect();
    return box.width > 40 && box.height > 15;
  });
  const hit = options.find((el) => {
    const text = (el.innerText || "").replace(/\\s+/g, " ").trim().toUpperCase();
    return text.includes("(" + needle + ")") || text.includes("[" + needle + "]");
  });
  if (!hit) return false;
  hit.scrollIntoView({ block: "center" });
  hit.click();
  return true;
}
"""

_SET_EASEMYTRIP_DATE_JS = """
(value) => {
  const input = document.querySelector("#ddate");
  if (!input) return false;
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  return true;
}
"""


async def _select_easemytrip_airport(
    page,
    *,
    display_selector: str,
    edit_selector: str,
    query_text: str,
    code: str,
    timeout_ms: int,
) -> bool:
    display = page.locator(display_selector)
    if await display.count() == 0:
        return False
    edit = page.locator(edit_selector)
    if not await edit.is_visible():
        try:
            await display.click(timeout=min(timeout_ms, 2000))
        except Exception:
            pass
    try:
        await edit.wait_for(state="visible", timeout=min(timeout_ms, 8000))
        await edit.fill(query_text, timeout=timeout_ms)
    except Exception:
        return False
    await page.wait_for_timeout(1200)
    return bool(await page.evaluate(_PICK_EASEMYTRIP_AIRPORT_JS, code))


async def _fill_easemytrip_widget(page, plan: BrowserSearchPlan, timeout_ms: int) -> bool:
    origin_ok = await _select_easemytrip_airport(
        page,
        display_selector="#FromSector_show",
        edit_selector="#a_FromSector_show",
        query_text=plan.origin_query,
        code=plan.origin_code,
        timeout_ms=timeout_ms,
    )
    if not origin_ok:
        return False
    destination_ok = await _select_easemytrip_airport(
        page,
        display_selector="#Editbox13_show",
        edit_selector="#a_Editbox13_show",
        query_text=plan.destination_query,
        code=plan.destination_code,
        timeout_ms=timeout_ms,
    )
    if not destination_ok:
        return False
    await page.wait_for_timeout(700)
    overlay = page.locator("#overlaybg1:visible")
    if await overlay.count():
        await overlay.last.click(position={"x": 5, "y": 5}, timeout=min(timeout_ms, 5000))
    date_value = plan.travel_date.strftime("%d/%m/%Y")
    if not await page.evaluate(_SET_EASEMYTRIP_DATE_JS, date_value):
        return False
    search = page.locator("input.srchBtnSe").first
    if await search.count() == 0:
        return False
    await search.click(timeout=timeout_ms)
    try:
        await page.wait_for_url("**/flight-search/listing**", timeout=max(timeout_ms, 20000))
        await page.locator(".nw_listing_bx").first.wait_for(
            state="visible", timeout=max(timeout_ms, 30000)
        )
        await page.wait_for_function(
            """({ selector, origin, destination }) => {
              return [...document.querySelectorAll(selector)].some((card) => {
                const text = (card.innerText || "").toUpperCase();
                return text.includes("(" + origin + ")")
                  && text.includes("(" + destination + ")")
                  && text.includes("₹");
              });
            }""",
            arg={
                "selector": plan.dom_record_selector or ".nw_listing_bx",
                "origin": plan.origin_code,
                "destination": plan.destination_code,
            },
            timeout=max(timeout_ms, 30000),
        )
    except Exception:
        return False
    return True


async def _advance_calendar_month(page, travel_date: date) -> None:
    target_month = travel_date.strftime("%B")
    for _ in range(8):
        labels = await page.evaluate(
            """() => {
              const months = "January|February|March|April|May|June|July|August|September|October|November|December";
              const re = new RegExp("^(" + months + ")\\\\s+\\\\d{4}$");
              return [...document.querySelectorAll("div, span, button, h2, strong")]
                .map((el) => (el.innerText || "").trim())
                .filter((text) => re.test(text))
                .slice(0, 6);
            }"""
        )
        if any(str(label).startswith(target_month) for label in labels):
            return
        if not labels:
            return
        moved = await page.evaluate(_NEXT_MONTH_JS)
        if not moved:
            return
        await page.wait_for_timeout(300)


async def _fill_search(page, plan: BrowserSearchPlan, timeout_ms: int) -> None:
    if plan.widget == "akasa":
        await _fill_akasa_widget(page, plan, timeout_ms)
        return
    if plan.widget == "easemytrip":
        await _fill_easemytrip_widget(page, plan, timeout_ms)
        return
    origin = page.get_by_placeholder("From").first
    destination = page.get_by_placeholder("To").first
    if await origin.count() == 0:
        origin = page.get_by_label("From", exact=False).first
    if await destination.count() == 0:
        destination = page.get_by_label("To", exact=False).first
    if await origin.count():
        await origin.click(timeout=timeout_ms)
        await origin.fill(plan.origin_query, timeout=timeout_ms)
        option = page.get_by_text(plan.origin_query, exact=False).nth(1)
        if await option.count():
            await option.click(timeout=timeout_ms)
    if await destination.count():
        await destination.click(timeout=timeout_ms)
        await destination.fill(plan.destination_query, timeout=timeout_ms)
        option = page.get_by_text(plan.destination_query, exact=False).nth(1)
        if await option.count():
            await option.click(timeout=timeout_ms)
    await _pick_date(page, plan.travel_date, timeout_ms)
    for label in plan.submit_labels:
        button = page.get_by_role("button", name=label, exact=False).first
        if await button.count():
            await button.click(timeout=timeout_ms)
            await page.wait_for_timeout(2500)
            return


async def _pick_date(page, travel_date: date, timeout_ms: int) -> None:
    iso = travel_date.isoformat()
    date_input = page.locator('input[type="date"]').first
    if await date_input.count():
        await date_input.fill(iso, timeout=timeout_ms)
        return
    trigger = page.get_by_placeholder("Select dates").first
    if await trigger.count() == 0:
        trigger = page.get_by_placeholder("Departure").first
    if await trigger.count():
        await trigger.click(timeout=timeout_ms)
    day = str(travel_date.day)
    cell = page.get_by_role("gridcell", name=day, exact=True).first
    if await cell.count() == 0:
        cell = page.get_by_text(day, exact=True).first
    if await cell.count():
        await cell.click(timeout=timeout_ms)


class _BrowserCollector(BaseCollector):
    def __init__(self, settings: Settings, runtime: BrowserRuntime) -> None:
        self.settings = settings
        self.runtime = runtime
        self._robots: dict = {}

    def bind_robots(self, source_id, snapshot: RobotsSnapshot) -> None:
        self._robots[source_id] = snapshot

    def robots_for(self, source: SourceProfile) -> RobotsSnapshot | None:
        return self._robots.get(source.id)

    def plugin(self, source: SourceProfile):
        return plugin_for(source.id, source.name)

    async def _supported(self, source: SourceProfile) -> bool:
        plugin = self.plugin(source)
        if plugin is None or self.settings.data_mode != DataMode.LIVE:
            return False
        if source.source_type == SourceType.MOCK:
            return False
        return plugin.spec.requires_javascript or plugin.spec.browser_network_json


class PlaywrightNetworkCollector(_BrowserCollector):
    identity = CollectorModality.PLAYWRIGHT_NETWORK
    parser_name = "airline_browser_network"
    parser_version = "1.0.0"

    async def supports(self, source: SourceProfile) -> bool:
        return await self._supported(source) and source.capabilities.browser_network_json

    async def collect(self, query, source, *, lease, egress) -> CollectionResult:
        return await _collect_browser(self, query, source, lease=lease, prefer_json=True)


class PlaywrightDomCollector(_BrowserCollector):
    identity = CollectorModality.PLAYWRIGHT_DOM
    parser_name = "airline_browser_dom"
    parser_version = "1.0.0"

    async def supports(self, source: SourceProfile) -> bool:
        return await self._supported(source) and source.capabilities.requires_javascript

    async def collect(self, query, source, *, lease, egress) -> CollectionResult:
        return await _collect_browser(self, query, source, lease=lease, prefer_json=False)


async def _collect_browser(collector: _BrowserCollector, query, source, *, lease, prefer_json: bool) -> CollectionResult:
    started = utcnow()
    if not lease.is_valid(started):
        return denied_result(
            source, collector.identity, started, code="LEASE_INVALID", message="Compliance lease is not valid"
        )
    plugin = collector.plugin(source)
    if plugin is None:
        return CollectionResult(
            source_id=source.id,
            collector=collector.identity,
            status=CollectionStatus.UNSUPPORTED,
            requested_at=started,
            completed_at=utcnow(),
        )
    plan = plugin.browser_plan(query)
    if plan is None:
        return CollectionResult(
            source_id=source.id,
            collector=collector.identity,
            status=CollectionStatus.UNSUPPORTED,
            requested_at=started,
            completed_at=utcnow(),
            metadata={"reason": "no_browser_plan"},
        )
    robots = collector.robots_for(source)
    blocked = robots_or_deny(source, collector.identity, started, robots)
    if blocked:
        return blocked
    key = collector.runtime.cache_key(source.id, query)
    capture = await collector.runtime.capture(source, plan, robots, key)
    if capture.status in {
        CollectionStatus.BLOCKED,
        CollectionStatus.CAPTCHA_BLOCKED,
        CollectionStatus.POLICY_DENIED,
        CollectionStatus.RATE_LIMITED,
        CollectionStatus.NETWORK_ERROR,
        CollectionStatus.TEMPORARY_FAILURE,
        CollectionStatus.UNSUPPORTED,
    }:
        return CollectionResult(
            source_id=source.id,
            collector=collector.identity,
            status=capture.status,
            requested_at=started,
            completed_at=utcnow(),
            errors=[CollectionError(code=capture.status.value.upper(), message=capture.message)],
            metadata={"url": capture.url, "http_status": capture.http_status},
            http_response_category=(
                HttpResponseCategory.HTTP_403 if capture.http_status == 403 else HttpResponseCategory.NONE
            ),
        )
    confidence = confidence_for(collector.settings, collector.identity)
    observations = []
    if prefer_json:
        for item in capture.json_payloads:
            payload, url = _payload_and_url(item)
            outcome = plugin.parse_payload(payload, query, source, collector.identity, confidence, url=url)
            observations.extend(outcome.observations)
    if not observations:
        outcome = plugin.parse_html(capture.html, query, source, collector.identity, confidence)
        observations.extend(outcome.observations)
    named = [item for item in observations if item.flight_number != "UNSPECIFIED"]
    if named:
        observations = named
    if observations:
        parsed = ParseOutcome(status=CollectionStatus.SUCCESS, observations=observations)
    else:
        parsed = ParseOutcome(status=CollectionStatus.NO_RESULTS, message=capture.message)
    page_like = type(
        "PageLike",
        (),
        {
            "text": capture.html,
            "media_type": "text/html",
            "url": capture.url,
            "status_code": capture.http_status,
            "http_response_category": HttpResponseCategory.HTTP_2XX,
        },
    )()
    result = from_outcome(
        source,
        collector.identity,
        started,
        parsed,
        page=page_like,  # type: ignore[arg-type]
        parser_name=plugin.spec.parser_name,
        parser_version=plugin.spec.parser_version,
        limit=collector.settings.live_payload_max_bytes,
    )
    urls = []
    for item in capture.json_payloads:
        if isinstance(item, dict) and item.get("url"):
            urls.append(str(item["url"])[:240])
    result.metadata = {
        **(result.metadata or {}),
        "final_url": capture.url,
        "json_count": len(capture.json_payloads),
        "json_urls": urls[:12],
    }
    return result
