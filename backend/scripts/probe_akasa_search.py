"""Akasa search after waiting for destination list. Identified UA only."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

UA = "APIx-Research-Bot/0.1 (+https://www.mospi.gov.in; SIH26056 airfare index research)"
OUT = Path("data/akasa-search-probe.json")
TRAVEL = date(2026, 9, 27)


def _host_root(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


PICK_JS = """
(code) => {
  const needle = String(code).toUpperCase();
  const items = [...document.querySelectorAll("li")].filter((el) => {
    const r = el.getBoundingClientRect();
    return r.width > 40 && r.height > 20;
  });
  const hit = items.find((el) => {
    const text = (el.innerText || "").replace(/\\s+/g, " ").trim().toUpperCase();
    return text.startsWith(needle + " ");
  });
  if (!hit) {
    return {ok: false, sample: items.slice(0, 12).map((el) => (el.innerText || "").replace(/\\s+/g, " ").trim().slice(0, 40))};
  }
  hit.scrollIntoView({block: "center"});
  hit.click();
  return {ok: true, text: (hit.innerText || "").replace(/\\s+/g, " ").trim().slice(0, 80)};
}
"""


async def _pick(page, field_id: str, code: str) -> dict:
    await page.locator(f"#{field_id}").click()
    await page.wait_for_timeout(1600)
    result = await page.evaluate(PICK_JS, code)
    await page.wait_for_timeout(400)
    value = await page.locator(f"#{field_id}").input_value()
    return {"pick": result, "value": value}


async def main() -> None:
    json_hits: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=UA, locale="en-IN", viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        async def on_response(response) -> None:
            ctype = (response.headers or {}).get("content-type", "")
            if "json" not in ctype.lower():
                return
            host = _host_root(response.url)
            if host != "akasaair.com" and not host.endswith(".akasaair.com"):
                return
            try:
                body = await response.json()
            except Exception:
                return
            json_hits.append({"url": response.url[:400], "status": response.status, "body": body})

        page.on("response", on_response)
        await page.goto("https://www.akasaair.com/", wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2000)
        origin = await _pick(page, "From", "DEL")
        dest = await _pick(page, "To", "BOM")
        print("origin", origin)
        print("dest", dest)
        await page.locator("input[name='DepartureDate']").click()
        await page.wait_for_timeout(800)
        day_result = await page.evaluate(
            """(payload) => {
              const day = String(payload.day);
              const month = payload.month;
              const nodes = [...document.querySelectorAll("button,td,[role='gridcell'],div,span")];
              const hit = nodes.find((el) => {
                const t = (el.innerText || "").trim();
                if (t !== day) return false;
                const r = el.getBoundingClientRect();
                return r.width > 8 && r.height > 8 && r.width < 80;
              });
              if (!hit) return {ok: false, monthHint: month};
              hit.click();
              return {ok: true};
            }""",
            {"day": TRAVEL.day, "month": TRAVEL.strftime("%B")},
        )
        print("day", day_result)
        clicked = await page.evaluate(
            """() => {
              const btn = [...document.querySelectorAll("button")].find((el) => (el.innerText || "").trim() === "Search Flights");
              if (!btn) return false;
              btn.click();
              return true;
            }"""
        )
        print("clicked_search", clicked)
        await page.wait_for_timeout(14000)
        html = await page.content()
        payload = {
            "origin": origin,
            "dest": dest,
            "day": day_result,
            "clicked_search": clicked,
            "final_url": page.url,
            "html_len": len(html),
            "rupee_count": html.count("₹"),
            "json_hit_count": len(json_hits),
            "json_hits": [
                {
                    "url": item["url"],
                    "status": item["status"],
                    "keys": list(item["body"].keys())[:40] if isinstance(item["body"], dict) else type(item["body"]).__name__,
                    "preview": str(item["body"])[:1500],
                }
                for item in json_hits
            ],
        }
        OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        await page.screenshot(path="data/akasa-after-search.png")
        print("final_url", page.url)
        print("json_hit_count", len(json_hits), "rupee", payload["rupee_count"])
        for item in payload["json_hits"]:
            print(item["status"], item["url"][:160], item["keys"])
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
