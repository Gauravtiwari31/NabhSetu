"""Dump Akasa From-field UI after click, without guessing selectors."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

UA = "APIx-Research-Bot/0.1 (+https://www.mospi.gov.in; SIH26056 airfare index research)"
OUT = Path("data/akasa-from-click.json")
SHOT = Path("data/akasa-from-click.png")


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=UA, locale="en-IN", viewport={"width": 1400, "height": 900})
        page = await context.new_page()
        await page.goto("https://www.akasaair.com/", wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2500)
        await page.locator("#From").click()
        await page.wait_for_timeout(1200)
        await page.screenshot(path=str(SHOT), full_page=False)
        dump = await page.evaluate(
            """() => {
              const from = document.querySelector("#From");
              const rect = from.getBoundingClientRect();
              const nearby = [...document.querySelectorAll("li,div,button,span,p")]
                .filter((el) => {
                  const r = el.getBoundingClientRect();
                  if (r.width === 0 || r.height === 0) return false;
                  if (r.top < rect.bottom - 10 || r.top > rect.bottom + 420) return false;
                  const t = (el.innerText || "").trim();
                  return t.length > 1 && t.length < 60;
                })
                .slice(0, 40)
                .map((el) => ({
                  tag: el.tagName,
                  role: el.getAttribute("role"),
                  testid: el.getAttribute("data-testid"),
                  text: el.innerText.trim().slice(0, 80),
                }));
              return { fromValue: from?.value, nearby };
            }"""
        )
        OUT.write_text(json.dumps(dump, indent=2), encoding="utf-8")
        print(json.dumps(dump, indent=2)[:6000])
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
