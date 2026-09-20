"""One-shot live probe of Akasa booking widget. Identified UA, no stealth."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

UA = "Nabhsetu-Research-Bot/0.1 (+https://www.mospi.gov.in; SIH26056 airfare index research)"
OUT = Path("data/akasa-probe.json")


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=UA, locale="en-IN")
        page = await context.new_page()
        network: list[dict] = []

        def on_response(response) -> None:
            ctype = (response.headers or {}).get("content-type", "")
            network.append(
                {
                    "url": response.url[:300],
                    "status": response.status,
                    "content_type": ctype[:80],
                }
            )

        page.on("response", on_response)
        await page.goto("https://www.akasaair.com/", wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(4000)
        snapshot = await page.evaluate(
            """() => {
              const pick = (el) => ({
                tag: el.tagName,
                type: el.getAttribute("type"),
                name: el.getAttribute("name"),
                id: el.id,
                className: String(el.className).slice(0, 120),
                placeholder: el.getAttribute("placeholder"),
                aria: el.getAttribute("aria-label"),
                role: el.getAttribute("role"),
                text: (el.innerText || "").slice(0, 80),
              });
              return {
                title: document.title,
                url: location.href,
                inputs: [...document.querySelectorAll("input,textarea,[role='combobox'],[role='textbox']")].slice(0, 40).map(pick),
                buttons: [...document.querySelectorAll("button,[type='submit']")].slice(0, 30).map(pick),
                iframes: [...document.querySelectorAll("iframe")].map((el) => el.src),
              };
            }"""
        )
        payload = {"before": snapshot, "network_before": network[-40:], "after": None}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps(snapshot, indent=2)[:4000])
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
