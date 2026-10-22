"""Steam Community profile XML: a custom URL to its numeric SteamID, and the profile's privacy (014 research R1, R3).

Used once, by `sweetspot setup` (FR-002, FR-003). `/id/<name>/?xml=1` needs no key, unlike ResolveVanityURL, and
the same answer carries `privacyState`, so a private profile is told apart from one that does not exist.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from sweetspot.sources.errors import SourceError
from sweetspot.sources.http import RateLimitedClient

BASE = "https://steamcommunity.com"
MIN_INTERVAL = 1.5
VANITY = re.compile(r"[A-Za-z0-9_-]{2,32}")      # what Steam allows in a custom URL
_STEAMID = re.compile(r"7656119\d{10}")


@dataclass(frozen=True)
class Profile:
    steamid: str
    name: str | None
    privacy: str | None          # public / friendsonly / private


class ProfileNotFound(SourceError):
    """Steam answered that there is no such profile."""


def parse_profile(text: str) -> Profile:
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise SourceError("steam-community: unexpected DTD in the profile answer")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise SourceError("steam-community: the profile answer is not XML") from None
    if root.tag == "response" and root.find("error") is not None:
        raise ProfileNotFound((root.findtext("error") or "").strip())
    steamid = (root.findtext("steamID64") or "").strip()
    if root.tag != "profile" or not _STEAMID.fullmatch(steamid):
        raise SourceError("steam-community: the profile answer has no SteamID")
    privacy = (root.findtext("privacyState") or "").strip() or None
    return Profile(steamid=steamid, name=(root.findtext("steamID") or "").strip() or None, privacy=privacy)


class SteamCommunity:
    def __init__(self, http: RateLimitedClient):
        self.http = http

    def _get(self, path: str) -> Profile:
        response = self.http.get(f"{BASE}{path}", params={"xml": 1})
        if response.status_code != 200:
            raise SourceError(f"steam-community: HTTP {response.status_code}")
        return parse_profile(response.text)

    def by_vanity(self, name: str) -> Profile:
        if not VANITY.fullmatch(name):
            raise ValueError(f"not a Steam custom URL name: {name!r}")
        return self._get(f"/id/{name}/")

    def by_steamid(self, steamid: str) -> Profile:
        if not _STEAMID.fullmatch(steamid):
            raise ValueError(f"not a SteamID: {steamid!r}")
        return self._get(f"/profiles/{steamid}/")
