"""T031: screenshots of the other-editions table (390 px and 1100 px) and a check for horizontal scroll.

uv run --with playwright python specs/009-purchase-options/prototype/t031_shots.py data/reports/latest.html
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

page_path = Path(sys.argv[1]).resolve()
out = Path(__file__).parent / "out"
with sync_playwright() as p:
    browser = p.chromium.launch()
    for width in (390, 1100):
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.goto(page_path.as_uri())
        page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
        scroll = page.evaluate("document.documentElement.scrollWidth")
        hints = page.locator(".tag.editions").count()
        for app in (812140, 239140):
            game = page.locator(f'details.game[data-app="{app}"]')
            game.scroll_into_view_if_needed()
            game.screenshot(path=str(out / f"t031_{app}_{width}.png"))
        print(f"{width}px: scrollWidth {scroll} ({'OK' if scroll <= width else 'HORIZONTAL SCROLL'}), "
              f"edition hints {hints}")
    browser.close()
