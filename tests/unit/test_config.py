from pathlib import Path

import pytest

from sweetspot import config as cfg
from sweetspot.config import DEFAULT_TOML, ConfigError, load_config
from tests.config_builders import FAKE_STEAMID, FAKE_WISHLIST_URL, TEST_TOML


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_file_is_not_created(tmp_path):
    """014 FR-001: only `sweetspot setup` writes the settings file; loading never makes one from defaults."""
    path = tmp_path / "sweetspot.toml"
    with pytest.raises(cfg.ConfigMissing):
        cfg.load_config(path)
    assert list(tmp_path.iterdir()) == []


def test_template_values(tmp_path):
    config, warnings = cfg.load_config(write(tmp_path / "s.toml", TEST_TOML))
    assert warnings == []
    assert config.region == "TW"
    assert config.aux_region == "US"
    assert config.steamid == FAKE_STEAMID
    assert config.max_items == 500
    assert config.removed_tracking_months == 24
    assert config.reference.daily_budget_seconds == 120
    assert config.data_dir == tmp_path / "data"
    assert config.legacy_cache_path is None


def test_template_has_no_personal_values():
    """014 FR-001, FR-010: no SteamID-like number and no Windows absolute path in the defaults."""
    import re

    assert not re.search(r"7656119\d{10}", DEFAULT_TOML)
    assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", DEFAULT_TOML)
    assert 'url = ""' in DEFAULT_TOML and "cache_path = ''" in DEFAULT_TOML


def test_empty_wishlist_url_points_to_setup(tmp_path):
    with pytest.raises(cfg.ConfigError, match="sweetspot setup"):
        cfg.load_config(write(tmp_path / "s.toml", DEFAULT_TOML))


def test_a_legacy_path_is_kept(tmp_path):
    text = TEST_TOML.replace("cache_path = ''", "cache_path = 'D:\\\\Tools\\\\old\\\\cache'")
    config, _ = cfg.load_config(write(tmp_path / "s.toml", text))
    assert config.legacy_cache_path == Path("D:\\Tools\\old\\cache")


def test_unknown_keys_only_warn(tmp_path):
    path = write(tmp_path / "s.toml", TEST_TOML + "\n[extra]\nfoo = 1\n")
    config, warnings = cfg.load_config(path)
    assert config.region == "TW"
    assert any("extra" in w for w in warnings)


def test_region_must_be_tw(tmp_path):
    path = write(tmp_path / "s.toml", TEST_TOML.replace('region = "TW"', 'region = "US"'))
    with pytest.raises(cfg.ConfigError, match="market.region"):
        cfg.load_config(path)


@pytest.mark.parametrize(
    "url",
    [
        "https://store.steampowered.com/wishlist/profiles/123/",
        f"http://store.steampowered.com/wishlist/profiles/{FAKE_STEAMID}/",
        f"https://example.com/wishlist/profiles/{FAKE_STEAMID}/",
    ],
)
def test_wishlist_url_is_validated(tmp_path, url):
    text = TEST_TOML.replace(FAKE_WISHLIST_URL, url)
    with pytest.raises(cfg.ConfigError, match="wishlist.url"):
        cfg.load_config(write(tmp_path / "s.toml", text))


def test_wrong_type_is_an_error(tmp_path):
    text = TEST_TOML.replace("max_items = 500", 'max_items = "many"')
    with pytest.raises(cfg.ConfigError, match="wishlist.max_items"):
        cfg.load_config(write(tmp_path / "s.toml", text))


def test_secrets_from_process_env(monkeypatch):
    monkeypatch.setenv("ITAD_API_KEY", "itad-secret-value")
    monkeypatch.setenv("STEAM_WEB_API_KEY", "steam-secret-value")
    secrets = cfg.load_secrets(registry_reader=lambda name: None)
    assert secrets.itad_api_key.reveal() == "itad-secret-value"
    assert secrets.steam_web_api_key.reveal() == "steam-secret-value"


def test_secrets_fall_back_to_user_registry(monkeypatch):
    monkeypatch.delenv("ITAD_API_KEY", raising=False)
    monkeypatch.delenv("STEAM_WEB_API_KEY", raising=False)
    values = {"STEAM_WEB_API_KEY": "from-registry"}
    secrets = cfg.load_secrets(registry_reader=values.get)
    assert secrets.itad_api_key is None
    assert secrets.steam_web_api_key.reveal() == "from-registry"


def test_tests_never_see_the_real_keys():
    # tests/conftest.py no_real_secrets; only a count, so a failure cannot print a key
    found = len(cfg.load_secrets().redaction_values())
    assert found == 0


def test_secret_is_never_shown_in_repr_or_str(monkeypatch):
    monkeypatch.setenv("ITAD_API_KEY", "itad-secret-value")
    monkeypatch.delenv("STEAM_WEB_API_KEY", raising=False)   # a real key in the environment would leak into the failure message
    secrets = cfg.load_secrets(registry_reader=lambda name: None)
    for text in (repr(secrets), str(secrets), repr(secrets.itad_api_key), str(secrets.itad_api_key),
                 f"{secrets.itad_api_key}"):
        assert "itad-secret-value" not in text
    assert secrets.redaction_values() == ["itad-secret-value"]


# --- feature 003: [preferences] (tasks T003) -----------------------------------------------------------

def test_preferences_default_when_section_missing(tmp_path):
    path = write(tmp_path / "s.toml", 'schema_version = 1\n[wishlist]\nurl = '
                 '"https://store.steampowered.com/wishlist/profiles/76561197960265728/"\n')
    config, _ = cfg.load_config(path)
    p = config.preferences
    assert (p.gap_pp_shallow, p.gap_pp_deep, p.gap_boundary_pct) == (10, 5, 75)
    assert (p.tolerance_min_twd, p.tolerance_max_twd, p.soon_sales) == (30, 100, 1)


def test_default_toml_documents_preferences(tmp_path):
    assert "[preferences]" in cfg.DEFAULT_TOML
    config, warnings = cfg.load_config(write(tmp_path / "new.toml", TEST_TOML))
    assert warnings == [] and config.preferences == cfg.Preferences()


def test_partial_preferences_keep_other_defaults(tmp_path):
    path = write(tmp_path / "s.toml", TEST_TOML + "")
    text = path.read_text(encoding="utf-8").replace("tolerance_min_twd = 30", "tolerance_min_twd = 0")
    config, _ = cfg.load_config(write(path, text))
    assert config.preferences.tolerance_min_twd == 0
    assert config.preferences.gap_pp_deep == 5


def test_preferences_as_dict_round_trips():
    prefs = cfg.Preferences(gap_pp_deep=7)
    assert prefs.as_dict()["gap_pp_deep"] == 7
    assert set(prefs.as_dict()) == {"gap_pp_shallow", "gap_pp_deep", "gap_boundary_pct", "tolerance_min_twd",
                                     "tolerance_max_twd", "soon_sales", "wait_cost_twd"}


@pytest.mark.parametrize("key, value, message", [
    ("gap_pp_shallow", "0", "gap_pp_shallow"),
    ("gap_pp_deep", "51", "gap_pp_deep"),
    ("gap_boundary_pct", "72", "gap_boundary_pct"),
    ("gap_boundary_pct", "100", "gap_boundary_pct"),
    ("tolerance_min_twd", "-1", "tolerance_min_twd"),
    ("tolerance_min_twd", "150", "tolerance_min_twd"),
    ("tolerance_max_twd", "0", "tolerance_max_twd"),
    ("soon_sales", "5", "soon_sales"),
    ("soon_sales", "true", "soon_sales"),
    ("gap_pp_deep", '"5"', "gap_pp_deep"),
])
def test_invalid_preferences_are_rejected(tmp_path, key, value, message):
    import re
    text = re.sub(rf"^{key} = \S+", f"{key} = {value}", TEST_TOML, flags=re.M)
    assert text != TEST_TOML
    with pytest.raises(cfg.ConfigError, match=message):
        cfg.load_config(write(tmp_path / "s.toml", text))


def test_unknown_preference_only_warns(tmp_path):
    text = TEST_TOML.replace("[preferences]", "[preferences]\nfoo = 1")
    config, warnings = cfg.load_config(write(tmp_path / "s.toml", text))
    assert any("preferences.foo" in w for w in warnings)
    assert config.preferences == cfg.Preferences()


# --- feature 005: wait_cost_twd and preferences per rule (tasks T002) ------------------------------------------

def test_wait_cost_defaults_to_20(tmp_path):
    config, warnings = cfg.load_config(write(tmp_path / "new.toml", TEST_TOML))
    assert warnings == [] and config.preferences.wait_cost_twd == 20
    assert "wait_cost_twd = 20" in cfg.DEFAULT_TOML


def test_wait_cost_is_read(tmp_path):
    text = TEST_TOML.replace("wait_cost_twd = 20", "wait_cost_twd = 35")
    config, _ = cfg.load_config(write(tmp_path / "s.toml", text))
    assert config.preferences.wait_cost_twd == 35


@pytest.mark.parametrize("value", ["-1", "10001", "1.5", '"20"', "true"])
def test_invalid_wait_cost_is_rejected(tmp_path, value):
    text = TEST_TOML.replace("wait_cost_twd = 20", f"wait_cost_twd = {value}")
    with pytest.raises(cfg.ConfigError, match="preferences.wait_cost_twd"):
        cfg.load_config(write(tmp_path / "s.toml", text))


def test_range_message():
    with pytest.raises(cfg.ConfigError, match="preferences.wait_cost_twd 必須是 0 到 10000 的整數"):
        cfg._preferences({"wait_cost_twd": 10001})
    assert cfg._preferences({"wait_cost_twd": 0}).wait_cost_twd == 0
    assert cfg._preferences({"wait_cost_twd": 10000}).wait_cost_twd == 10000


def test_preferences_for_rule():
    p = cfg.Preferences(wait_cost_twd=30)
    old = {"gap_pp_shallow", "gap_pp_deep", "gap_boundary_pct", "tolerance_min_twd", "tolerance_max_twd", "soon_sales"}
    assert set(p.for_rule("2.0.0")) == old and set(p.for_rule("1.0.0")) == old
    assert p.for_rule("3.0.0") == {"wait_cost_twd": 30, "soon_sales": 1}
    with pytest.raises(ValueError):
        p.for_rule("9.9.9")


# --- feature 009: [purchase_options] (data-model §3, contracts/cli-and-report.md) -----------------------------

def _load_with(tmp_path, body):
    path = tmp_path / "sweetspot.toml"
    assert DEFAULT_TOML.rstrip().splitlines()[-2] == "[purchase_options]"   # the template ends in that section
    path.write_text(TEST_TOML + body, encoding="utf-8")
    return load_config(path)


def test_purchase_options_parse_valid_entries(tmp_path):
    config, warnings = _load_with(tmp_path, '1091500 = "bundle/32470"\n812140 = "sub/349020"\n')
    assert config.purchase_options == {1091500: ("bundle", 32470), 812140: ("sub", 349020)}
    assert warnings == []


@pytest.mark.parametrize("body,warning", [
    ('abc = "sub/1"\n', "purchase_options.abc：鍵必須是 App 編號（正整數），已忽略"),
    ('0 = "sub/1"\n', "purchase_options.0：鍵必須是 App 編號（正整數），已忽略"),
    ('5 = "package/1"\n', 'purchase_options.5：值必須是 "sub/<數字>" 或 "bundle/<數字>"，已忽略'),
    ('5 = "sub/x"\n', 'purchase_options.5：值必須是 "sub/<數字>" 或 "bundle/<數字>"，已忽略'),
    ('5 = 7\n', 'purchase_options.5：值必須是 "sub/<數字>" 或 "bundle/<數字>"，已忽略'),
])
def test_purchase_options_bad_entries_are_ignored_with_a_warning(tmp_path, body, warning):
    config, warnings = _load_with(tmp_path, body + '9 = "sub/2"\n')
    assert config.purchase_options == {9: ("sub", 2)}
    assert warnings == [warning]


def test_same_app_written_two_ways_is_ignored_entirely(tmp_path):
    config, warnings = _load_with(tmp_path, '"0123" = "sub/1"\n123 = "sub/2"\n9 = "sub/3"\n')
    assert config.purchase_options == {9: ("sub", 3)}
    assert warnings == ['purchase_options.123：同一 App 出現多次（"0123" 與 "123"），全部忽略']


def test_identical_duplicate_keys_are_a_toml_error(tmp_path):
    with pytest.raises(ConfigError, match="設定檔格式錯誤"):
        _load_with(tmp_path, '5 = "sub/1"\n5 = "sub/2"\n')


def test_default_template_has_no_active_choice(tmp_path):
    path = tmp_path / "sweetspot.toml"
    path.write_text(TEST_TOML, encoding="utf-8")
    config, warnings = load_config(path)
    assert config.purchase_options == {} and warnings == []
    assert "[purchase_options]" in DEFAULT_TOML and '# 1091500 = "bundle/32470"' in DEFAULT_TOML
