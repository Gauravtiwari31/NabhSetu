"""Inspect Akasa airport dropdown after typing. Identified UA only."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

UA = "APIx-Research-Bot/0.1 (+https://www.mospi.gov.in; SIH26056 airfare index research)"
OUT = Path("data/akasa-dropdown-probe.json")


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=UA, locale="en-IN")
        page = await context.new_page()
        await page.goto("https://www.akasaair.com/", wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2000)
        await page.locator("#From").click()
        await page.locator("#From").fill("")
        await page.locator("#From").type("Delhi", delay=80)
        await page.wait_for_timeout(1500)
        dump = await page.evaluate(
            """() => {
              const visible = [...document.querySelectorAll("li,div,button,span")]
                .filter((el) => {
                  const t = (el.innerText || "").trim();
                  if (!t || t.length > 80) return false;
                  const r = el.getBoundingClientRect();
                  return r.width > 0 && r.height > 0 && /delhi|del/i.test(t);
                })
                .slice(0, 25)
                .map((el) => ({
                  tag: el.tagName,
                  role: el.getAttribute("role"),
                  testid: el.getAttribute("data-testid"),
                  className: String(el.className).slice(0, 100),
                  text: el.innerText.trim().slice(0, 80),
                }));
              return {
                fromValue: document.querySelector("#From")?.value,
                listboxes: [...document.querySelectorAll("[role='listbox'],[role='option'],ul")].length,
                visible,
              };
            }"""
        )
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(dump, indent=2), encoding="utf-8")
        print(json.dumps(dump, indent=2)[:5000])
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
