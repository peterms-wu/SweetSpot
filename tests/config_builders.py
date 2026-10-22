"""Settings for tests: the default template with a fictional wishlist (014 T003).

DEFAULT_TOML carries no one's wishlist (014 FR-001), so a test that needs a working settings file writes TEST_TOML.
"""

import re

from sweetspot.config import DEFAULT_TOML

FAKE_STEAMID = "76561197960265728"      # account 0: Steam never gives it to anyone (014 research R8)
FAKE_WISHLIST_URL = f"https://store.steampowered.com/wishlist/profiles/{FAKE_STEAMID}/"

_URL_LINE = re.compile(r'^url = ".*"$', re.M)
assert len(_URL_LINE.findall(DEFAULT_TOML)) == 1, "DEFAULT_TOML must have exactly one url line"
TEST_TOML = _URL_LINE.sub(f'url = "{FAKE_WISHLIST_URL}"', DEFAULT_TOML)
