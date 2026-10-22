"""T029: screenshot of the report header and one 2026 winter game (390 and 1100 px), and the scroll width check.

uv run --with playwright python specs/012-sale-calendar-sync/prototype/t029_shot.py <report.html>
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

page_path = Path(sys.argv[1]).resolve()
with sync_playwright() as p:
    browser = p.chromium.launch()
    for width in (390, 1100):
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.goto(page_path.as_uri())
        header = page.locator("header")
        header.screenshot(path=str(page_path.with_name(f"t029-header-{width}.png")))
        scroll = page.evaluate("document.documentElement.scrollWidth")
        line = [t for t in header.inner_text().splitlines() if "特賣日期更新" in t]
        winter = page.locator("details.game", has_text="2026 冬特").first
        winter.scroll_into_view_if_needed()
        winter.screenshot(path=str(page_path.with_name(f"t029-winter-{width}.png")))
        print(f"{width}px: scrollWidth {scroll} {'OK' if scroll <= width else 'HORIZONTAL SCROLL'}; "
              f"calendar line {line}; first 2026 冬特 game: {winter.locator('summary').inner_text()[:80]!r}")
        page.close()
    browser.close()
