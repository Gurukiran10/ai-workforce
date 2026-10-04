"""Capture README screenshots of the operator console (sandbox must be running).

    python scripts/capture_screenshots.py
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
BASE = "http://localhost:8000"

SHOTS = [
    ("console.png", "/runs", 1500, None),
    ("run-invoice-approval.png", "/runs/sample-invoice-over-limit-approval", 1500, None),
    ("run-recruiting.png", "/runs/sample-recruiting-screening", 1500, None),
    ("run-silent-drop-verifier.png", "/runs/sample-silent-drop-caught-by-verifier", 1500, None),
    ("evidence-report.png", "/runs/sample-invoice-over-limit-approval/file/report.html", 1100, None),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in ("dark",):
            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme=theme, device_scale_factor=1.5)
            page = ctx.new_page()
            for name, path, height, _ in SHOTS:
                page.set_viewport_size({"width": 1440, "height": height})
                page.goto(BASE + path, wait_until="networkidle")
                page.wait_for_timeout(3500)  # let the live page replay the trace
                page.screenshot(path=str(OUT / name))
                print("saved", name)
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
