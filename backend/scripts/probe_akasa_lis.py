"""Debug visible airport LIs after clicking #From."""

from __future__ import annotations

import asyncio
import json

from playwright.async_api import async_playwright

UA = "Nabhsetu-Research-Bot/0.1 (+https://www.mospi.gov.in; SIH26056 airfare index research)"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=UA, locale="en-IN", viewport={"width": 1400, "height": 900})
        page = await context.new_page()
        await page.goto("https://www.akasaair.com/", wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2500)
        await page.locator("#From").click()
        await page.wait_for_timeout(1500)
        dump = await page.evaluate(
            """() => {
              const visibleLis = [...document.querySelectorAll("li")].filter((el) => {
                const r = el.getBoundingClientRect();
                return r.width > 40 && r.height > 20;
              }).map((el) => (el.innerText || "").replace(/\\s+/g, " ").trim().slice(0, 80));
              return {
                visibleLis: visibleLis.slice(0, 40),
                count: visibleLis.length,
                searchButtons: [...document.querySelectorAll("button,div,span,a")]
                  .map((el) => (el.innerText || "").trim())
                  .filter((t) => /search/i.test(t))
                  .slice(0, 10),
              };
            }"""
        )
        print(json.dumps(dump, indent=2))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
