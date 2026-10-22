"""014 T004: the Steam Community profile XML source (research R1, R3; FR-002, FR-003)."""

import httpx
import pytest

from sweetspot.sources.errors import SourceDisabled, SourceError
from sweetspot.sources.http import RateLimitedClient
from sweetspot.sources.steam_community import (BASE, Profile, ProfileNotFound, SteamCommunity, parse_profile)
from tests.conftest import FIXTURES
from tests.config_builders import FAKE_STEAMID


def xml(name: str) -> str:
    return (FIXTURES / "community" / f"{name}.xml").read_text(encoding="utf-8")


def community(handler, sleeps=None) -> SteamCommunity:
    http = RateLimitedClient("steam-community", min_interval=0, transport=httpx.MockTransport(handler),
                             sleep=(sleeps.append if sleeps is not None else lambda s: None))
    return SteamCommunity(http)


def answer(body: str, status: int = 200, **headers):
    return lambda request: httpx.Response(status, text=body, headers={"content-type": "text/xml", **headers})


@pytest.mark.parametrize(("name", "privacy", "display"), [
    ("profile_public", "public", "範例玩家"),
    ("profile_friendsonly", "friendsonly", "Example Friend"),
    ("profile_private", "private", "Example Private"),
])
def test_parse_profile(name, privacy, display):
    assert parse_profile(xml(name)) == Profile(steamid=FAKE_STEAMID, name=display, privacy=privacy)


def test_parse_profile_not_found():
    with pytest.raises(ProfileNotFound):
        parse_profile(xml("profile_not_found"))


@pytest.mark.parametrize("text", ["", "not xml", "<profile><steamID64>12</steamID64></profile>",
                                  '<?xml version="1.0"?><!DOCTYPE p [<!ENTITY x "y">]><profile/>'])
def test_parse_profile_rejects_malformed_or_dtd(text):
    with pytest.raises(SourceError) as info:
        parse_profile(text)
    assert not isinstance(info.value, ProfileNotFound)


def test_by_vanity_requests_the_xml_of_that_name():
    seen = []

    def handler(request):
        seen.append(request.url)
        return answer(xml("profile_public"))(request)

    assert community(handler).by_vanity("Some_Name-1").steamid == FAKE_STEAMID
    assert str(seen[0]) == f"{BASE}/id/Some_Name-1/?xml=1"


def test_by_steamid_requests_the_numeric_profile():
    seen = []

    def handler(request):
        seen.append(request.url)
        return answer(xml("profile_friendsonly"))(request)

    assert community(handler).by_steamid(FAKE_STEAMID).privacy == "friendsonly"
    assert str(seen[0]) == f"{BASE}/profiles/{FAKE_STEAMID}/?xml=1"


@pytest.mark.parametrize("name", ["", "a/b", "名稱", "a b", "x" * 33, "../x"])
def test_by_vanity_refuses_names_steam_does_not_allow(name):
    with pytest.raises(ValueError):
        community(answer(xml("profile_public"))).by_vanity(name)


def test_not_found_is_its_own_error():
    with pytest.raises(ProfileNotFound):
        community(answer(xml("profile_not_found"))).by_vanity("nobody")


def test_waits_on_429_then_reads():
    calls, sleeps = [], []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return answer(xml("profile_public"))(request)

    assert community(handler, sleeps).by_vanity("someone").privacy == "public"
    assert 3 in sleeps and len(calls) == 2


@pytest.mark.parametrize("status", [401, 403])
def test_stops_on_401_403_without_retrying(status):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status)

    source = community(handler)
    with pytest.raises(SourceDisabled):
        source.by_vanity("someone")
    with pytest.raises(SourceDisabled):
        source.by_steamid(FAKE_STEAMID)
    assert len(calls) == 1


def test_other_http_errors_are_source_errors():
    with pytest.raises(SourceError):
        community(answer("", status=404)).by_vanity("someone")
