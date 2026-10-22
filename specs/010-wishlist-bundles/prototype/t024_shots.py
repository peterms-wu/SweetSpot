"""T024/T033 (SC-008): the report's 組合包 section at 390 px — page width, each card's table fits or scrolls inside its
own box, and screenshots of the section and of one game's pointer lines.

uv run --with playwright python specs/010-wishlist-bundles/prototype/t024_shots.py data/reports/latest.html
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

page_path = Path(sys.argv[1]).resolve()
out = Path(__file__).parent / "out"
out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    for width in (390, 1100):
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.goto(page_path.as_uri())
        page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
        scroll = page.evaluate("document.documentElement.scrollWidth")
        cards = page.locator("details.bundle")
        clipped = []
        for i in range(cards.count()):
            card = cards.nth(i)
            box = card.bounding_box()
            for cell in card.locator("td, th").all():
                b = cell.bounding_box()
                scroller = cell.evaluate("c => c.closest('.table-scroll')")
                if b and b["x"] + b["width"] > box["x"] + box["width"] + 1 and not scroller:
                    clipped.append(cell.inner_text())
        page.locator("#bundles").screenshot(path=str(out / f"bundles-{width}.png"))
        hint = page.locator('details.game[data-app="1868140"]')
        if hint.count():
            hint.scroll_into_view_if_needed()
            hint.screenshot(path=str(out / f"hint-{width}.png"))
        print(f"{width}px: scrollWidth {scroll} ({'OK' if scroll <= width else 'HORIZONTAL SCROLL'}), "
              f"cards {cards.count()}, clipped cells outside a scroll box: {clipped or 'none'}")
        page.close()
    browser.close()
print("screenshots in", out)
