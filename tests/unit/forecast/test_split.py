"""research R4: games are split into a tuning and a validation part by a fixed hash (tasks T002; spec FR-009)."""

import hashlib

import pytest

from sweetspot.forecast.backtest.split import SALT, part, select


def test_the_salt_is_fixed():
    assert SALT == "steamsage-004-split"


@pytest.mark.parametrize("app, expected", [(1091500, "validation"), (1245620, "validation"), (413150, "validation"),
                                           (220, "tuning"), (292030, "tuning")])
def test_known_parts(app, expected):
    assert part(app) == expected


def test_the_rule_is_the_documented_hash():
    for app in (1, 57, 1091500):
        value = int(hashlib.sha256(f"{SALT}:{app}".encode()).hexdigest()[:8], 16)
        assert part(app) == ("tuning" if value % 2 == 0 else "validation")


def test_same_answer_every_time():
    assert [part(a) for a in range(1, 200)] == [part(a) for a in range(1, 200)]


def test_roughly_half_and_half():
    tuning = sum(part(a) == "tuning" for a in range(1, 5001))
    assert 0.45 * 5000 <= tuning <= 0.55 * 5000


def test_another_salt_gives_another_split():
    other = [int(hashlib.sha256(f"other:{a}".encode()).hexdigest()[:8], 16) % 2 == 0 for a in range(1, 200)]
    assert other != [part(a) == "tuning" for a in range(1, 200)]


def test_select():
    apps = (220, 1091500, 292030, 413150)
    assert select(apps, "all") == apps
    assert select(apps, "tuning") == (220, 292030)
    assert select(apps, "validation") == (1091500, 413150)
    with pytest.raises(ValueError):
        select(apps, "test")
