"""T049: the report at 390 px wide has no horizontal scroll, with every game expanded (feature 006 version lines).

uv run --with playwright python specs/006-version-tracking/prototype/check_390.py data/reports/latest.html
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

page_path = Path(sys.argv[1]).resolve()
shot = page_path.with_name("check-390.png")
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 390, "height": 900})
    page.goto(page_path.as_uri())
    page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
    width = page.evaluate("document.documentElement.scrollWidth")
    version = page.locator(".version").all_inner_texts()
    dying = page.locator('details.game[data-app="239140"]')
    dying.scroll_into_view_if_needed()
    dying.screenshot(path=str(shot))
    browser.close()
print(f"scrollWidth {width} (viewport 390): {'OK' if width <= 390 else 'HORIZONTAL SCROLL'}")
print("version lines:", version)
print("screenshot:", shot)
