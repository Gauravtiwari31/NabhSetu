from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"

FORBIDDEN = (
    "2captcha",
    "anticaptcha",
    "captcha solver",
    "rotate_on_403",
    "rotate_on_captcha",
    "rotate_on_block",
    "fingerprint spoof",
    "stealth_browser",
    "undetected_chromedriver",
)


def test_no_circumvention_capability_in_tree() -> None:
    hits: list[str] = []
    for path in ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for token in FORBIDDEN:
            if token in text:
                hits.append(f"{path}: {token}")
    assert hits == []
