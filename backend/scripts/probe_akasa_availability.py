"""Save full Akasa availability JSON after a successful widget search."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

UA = "Nabhsetu-Research-Bot/0.1 (+https://www.mospi.gov.in; SIH26056 airfare index research)"
OUT = Path("data/akasa-availability.json")
TRAVEL = date(2026, 9, 27)
PICK_JS = """
(code) => {
  const needle = String(code).toUpperCase();
  const items = [...document.querySelectorAll("li")].filter((el) => {
    const r = el.getBoundingClientRect();
    return r.width > 40 && r.height > 20;
  });
  const hit = items.find((el) => (el.innerText || "").replace(/\\s+/g, " ").trim().toUpperCase().startsWith(needle + " "));
  if (!hit) return {ok: false};
  hit.scrollIntoView({block: "center"});
  hit.click();
  return {ok: true};
}
"""


def _host_root(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


async def main() -> None:
    captured: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=UA, locale="en-IN", viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        async def on_response(response) -> None:
            if "json" not in (response.headers or {}).get("content-type", "").lower():
                return
            host = _host_root(response.url)
            if host != "akasaair.com" and not host.endswith(".akasaair.com"):
                return
            if "availability" not in response.url:
                return
            try:
                body = await response.json()
            except Exception:
                return
            captured.append({"url": response.url, "body": body})

        page.on("response", on_response)
        await page.goto("https://www.akasaair.com/", wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2000)
        await page.locator("#From").click()
        await page.wait_for_timeout(1600)
        await page.evaluate(PICK_JS, "DEL")
        await page.wait_for_timeout(400)
        await page.locator("#To").click()
        await page.wait_for_timeout(1600)
        await page.evaluate(PICK_JS, "BOM")
        await page.wait_for_timeout(400)
        await page.locator("input[name='DepartureDate']").click()
        await page.wait_for_timeout(700)
        await page.evaluate(
            """(day) => {
              const hit = [...document.querySelectorAll("button,td,[role='gridcell']")].find((el) => {
                const t = (el.innerText || "").trim();
                const r = el.getBoundingClientRect();
                return t === String(day) && r.width > 8 && r.width < 80;
              });
              if (hit) hit.click();
            }""",
            TRAVEL.day,
        )
        await page.evaluate(
            """() => {
              const btn = [...document.querySelectorAll("button")].find((el) => (el.innerText || "").trim() === "Search Flights");
              if (btn) btn.click();
            }"""
        )
        await page.wait_for_timeout(14000)
        OUT.write_text(json.dumps(captured, default=str), encoding="utf-8")
        print("saved", OUT, "payloads", len(captured), "bytes", OUT.stat().st_size)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
