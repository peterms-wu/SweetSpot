"""Load and validate sweetspot.toml, and read API keys from the environment only."""

import os
import re
import sys
import tomllib
from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TOML = """\
schema_version = 1

[wishlist]
# 由 uv run sweetspot setup 寫入；要換清單：uv run sweetspot setup --change
url = ""
max_items = 500
removed_tracking_months = 24

[market]
region = "TW"          # 固定值，不可更改（憲章 IX）
aux_region = "US"      # 輔助區域：只保存折扣百分比與時間

[storage]
data_dir = "data"      # 資料庫、鎖檔、日誌都放在這裡

[cache]
history_hours = 24
static_metadata_days = 30
volatile_metadata_days = 7
mapping_days = 7

[reference]
daily_budget_seconds = 120     # 0 表示停用日常小批次
seed = 20260924
per_publisher_cap = 30
broad_per_stratum = 25
min_total_reviews = 50
year_bins = [2015, 2018, 2020, 2022, 2024]
price_bins_twd = [300, 600, 1000]

[legacy]
cache_path = ''        # 只給前身專案 SteamSage 的使用者：它的快取資料夾（import-legacy 用）

# 甜蜜價的使用者偏好（不是模型事實；見 docs/model/model-definition.md 的決策規則）
[preferences]
wait_cost_twd = 20        # 等待成本：每多等一個月要多省的台幣（規則 3.0.0）
soon_sales = 1            # 甜蜜時點在前幾場季節特賣算「即將到價」
# 以下容許差距只用於規則 2.x（現行 2.1.0 的報告，以及 backtest-rule --rule 2.0.0／2.1.0 並列回測）
gap_pp_shallow = 10       # P_min 比分界淺時的折扣差距（百分點）
gap_pp_deep = 5           # P_min 達到分界或更深時的折扣差距（百分點）
gap_boundary_pct = 75     # 分界：P_min ≥ -75% 算「深」
tolerance_min_twd = 30    # 容許差距下限（元）
tolerance_max_twd = 100   # 容許差距上限（元）

# 指定要追蹤的購買選項（使用者偏好，不是模型事實）：App 編號 = "sub/<套件編號>" 或 "bundle/<組合包編號>"。
# 報告中每款遊戲的「其他版本」附有可以直接複製的設定行；刪掉一行就回到 Steam 預設的購買選項。
[purchase_options]
# 1091500 = "bundle/32470"   # 例：Cyberpunk 2077 → 《電馭叛客 2077：終極版》
"""

_WISHLIST_URL = re.compile(r"^https://store\.steampowered\.com/wishlist/profiles/(\d{17})/?$")
_OPTION_VALUE = re.compile(r"^(sub|bundle)/([1-9]\d*)$")
OPTIONS_SECTION = "purchase_options"      # feature 009: keys are App ids, so it has no fixed schema

# section -> key -> expected type
_SCHEMA: dict[str, dict[str, type | tuple[type, ...]]] = {
    "": {"schema_version": int},
    "wishlist": {"url": str, "max_items": int, "removed_tracking_months": int},
    "market": {"region": str, "aux_region": str},
    "storage": {"data_dir": str},
    "cache": {"history_hours": int, "static_metadata_days": int, "volatile_metadata_days": int,
              "mapping_days": int},
    "reference": {"daily_budget_seconds": int, "seed": int, "per_publisher_cap": int,
                  "broad_per_stratum": int, "min_total_reviews": int, "year_bins": list,
                  "price_bins_twd": list},
    "legacy": {"cache_path": str},
    "preferences": {"gap_pp_shallow": int, "gap_pp_deep": int, "gap_boundary_pct": int, "tolerance_min_twd": int,
                    "tolerance_max_twd": int, "soon_sales": int, "wait_cost_twd": int},
}


class ConfigError(Exception):
    pass


class ConfigMissing(ConfigError):
    """No settings file: only `sweetspot setup` creates one (014 FR-001)."""


@dataclass(frozen=True)
class CacheConfig:
    history_hours: int
    static_metadata_days: int
    volatile_metadata_days: int
    mapping_days: int


@dataclass(frozen=True)
class ReferenceConfig:
    daily_budget_seconds: int
    seed: int
    per_publisher_cap: int
    broad_per_stratum: int
    min_total_reviews: int
    year_bins: tuple[int, ...]
    price_bins_twd: tuple[int, ...]


TOLERANCE_KEYS = ("gap_pp_shallow", "gap_pp_deep", "gap_boundary_pct", "tolerance_min_twd", "tolerance_max_twd")


@dataclass(frozen=True)
class Preferences:
    """Sweet-price user preferences (feature 003 FR-036). Defaults are the values the user chose."""

    gap_pp_shallow: int = 10
    gap_pp_deep: int = 5
    gap_boundary_pct: int = 75
    tolerance_min_twd: int = 30
    tolerance_max_twd: int = 100
    soon_sales: int = 1
    wait_cost_twd: int = 20        # feature 005: NT$ a month of waiting must save (rule 3.0.0)

    def as_dict(self) -> dict[str, int]:
        return {k: getattr(self, k) for k in (*TOLERANCE_KEYS, "soon_sales", "wait_cost_twd")}

    def for_rule(self, version: str) -> dict[str, int]:
        """Only the preferences the rule version uses (005 research R5), for outputs, results and the report."""
        if version in ("1.0.0", "2.0.0", "2.1.0"):
            keys = (*TOLERANCE_KEYS, "soon_sales")
        elif version in ("3.0.0", "3.1.0"):
            keys = ("wait_cost_twd", "soon_sales")
        else:
            raise ValueError(f"未知的規則版本：{version}")
        return {k: getattr(self, k) for k in keys}


def _preferences(raw: dict) -> Preferences:
    prefs = Preferences(**raw)
    checks = [
        (1 <= prefs.gap_pp_shallow <= 50, "preferences.gap_pp_shallow 必須介於 1 到 50"),
        (1 <= prefs.gap_pp_deep <= 50, "preferences.gap_pp_deep 必須介於 1 到 50"),
        (5 <= prefs.gap_boundary_pct <= 95 and prefs.gap_boundary_pct % 5 == 0,
         "preferences.gap_boundary_pct 必須是 5 到 95 之間 5 的倍數"),
        (prefs.tolerance_max_twd >= 1, "preferences.tolerance_max_twd 必須 ≥ 1"),
        (0 <= prefs.tolerance_min_twd <= prefs.tolerance_max_twd,
         "preferences.tolerance_min_twd 必須介於 0 到 tolerance_max_twd"),
        (1 <= prefs.soon_sales <= 4, "preferences.soon_sales 必須介於 1 到 4"),
        (isinstance(prefs.wait_cost_twd, int) and not isinstance(prefs.wait_cost_twd, bool)
         and 0 <= prefs.wait_cost_twd <= 10000, "preferences.wait_cost_twd 必須是 0 到 10000 的整數"),
    ]
    for ok, message in checks:
        if not ok:
            raise ConfigError(message)
    return prefs


@dataclass(frozen=True)
class Config:
    path: Path
    wishlist_url: str
    steamid: str
    max_items: int
    removed_tracking_months: int
    region: str
    aux_region: str
    data_dir: Path
    cache: CacheConfig
    reference: ReferenceConfig
    legacy_cache_path: Path | None       # None: not set (014 FR-010)
    preferences: Preferences = Preferences()
    # feature 009 (data-model §3): app id -> ("sub" | "bundle", id); a user preference, not a model fact
    purchase_options: Mapping[int, tuple[str, int]] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "sweetspot.db"

    @property
    def extension_dir(self) -> Path:
        """The Chrome extension folder next to the config file (feature 011); the report writes its data/ file."""
        return self.path.parent / "extension"


class Secret:
    """Holds an API key; it is only exposed through reveal(), never through str/repr."""

    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret('***')"

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return repr(self)


@dataclass(frozen=True)
class Secrets:
    itad_api_key: Secret | None = None
    steam_web_api_key: Secret | None = None

    def redaction_values(self) -> list[str]:
        return [s.reveal() for s in (self.itad_api_key, self.steam_web_api_key) if s is not None]


def _read_user_registry(name: str) -> str | None:
    """Read a user-scope environment variable (HKCU\\Environment) that `setx` wrote but this
    process did not inherit yet."""
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value) if value else None
    except OSError:
        return None


def load_secrets(registry_reader: Callable[[str], str | None] | None = None) -> Secrets:
    # looked up at call time, so the test suite can turn the registry off (tests/conftest.py)
    reader = registry_reader or _read_user_registry

    def read(name: str) -> Secret | None:
        value = os.environ.get(name) or reader(name)
        return Secret(value.strip()) if value and value.strip() else None

    return Secrets(itad_api_key=read("ITAD_API_KEY"), steam_web_api_key=read("STEAM_WEB_API_KEY"))


def _purchase_options(raw: dict) -> tuple[dict[int, tuple[str, int]], list[str]]:
    """[purchase_options] (feature 009, contracts/cli-and-report.md): bad lines are ignored with a warning; an app
    written more than one way ("0123" and "123") is ignored entirely. Identical keys never get here: TOML itself
    rejects them."""
    warnings: list[str] = []
    seen: dict[int, list[str]] = {}
    parsed: dict[int, tuple[str, int]] = {}
    for key, value in raw.items():
        if not key.isdigit() or int(key) <= 0:
            warnings.append(f"{OPTIONS_SECTION}.{key}：鍵必須是 App 編號（正整數），已忽略")
            continue
        app = int(key)
        seen.setdefault(app, []).append(key)
        match = _OPTION_VALUE.match(value) if isinstance(value, str) else None
        if match is None:
            warnings.append(f'{OPTIONS_SECTION}.{key}：值必須是 "sub/<數字>" 或 "bundle/<數字>"，已忽略')
            continue
        parsed[app] = (match.group(1), int(match.group(2)))
    for app, keys in seen.items():
        if len(keys) > 1:
            parsed.pop(app, None)
            written = " 與 ".join(f'"{k}"' for k in keys)
            warnings.append(f"{OPTIONS_SECTION}.{app}：同一 App 出現多次（{written}），全部忽略")
    return parsed, warnings


def _validate_types(raw: dict) -> list[str]:
    warnings = []
    for key, value in raw.items():
        if isinstance(value, dict):
            if key == OPTIONS_SECTION:
                continue
            if key not in _SCHEMA:
                warnings.append(f"未知的設定區段 [{key}]，已忽略")
                continue
            for sub_key, sub_value in value.items():
                expected = _SCHEMA[key].get(sub_key)
                if expected is None:
                    warnings.append(f"未知的設定 {key}.{sub_key}，已忽略")
                elif not isinstance(sub_value, expected) or isinstance(sub_value, bool):
                    raise ConfigError(f"{key}.{sub_key} 型別錯誤：應為 {expected.__name__}")
        elif key not in _SCHEMA[""]:
            warnings.append(f"未知的設定 {key}，已忽略")
    return warnings


def _int_list(value: list, name: str) -> tuple[int, ...]:
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in value) or value != sorted(value):
        raise ConfigError(f"{name} 必須是遞增的整數清單")
    return tuple(value)


def data_dir_of(path: Path, raw: Mapping) -> Path:
    """[storage] data_dir of a parsed settings file at `path`; a relative one is relative to the file's folder.
    Shared with sweetspot.legacy, which reads it without load_config (that would create a missing file)."""
    value = Path(raw.get("storage", {}).get("data_dir", tomllib.loads(DEFAULT_TOML)["storage"]["data_dir"]))
    return value if value.is_absolute() else Path(path).parent / value


def load_config(path: Path) -> tuple[Config, list[str]]:
    """Load the config file. Returns (config, warnings). A missing file is an error: only `sweetspot setup`
    writes one, so no one silently gets the template (014 FR-001)."""
    path = Path(path)
    if not path.exists():
        raise ConfigMissing(f"找不到設定檔：{path}；請先執行 uv run sweetspot setup")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"設定檔格式錯誤：{exc}") from exc

    defaults = tomllib.loads(DEFAULT_TOML)
    warnings = _validate_types(raw)
    merged = {section: {**defaults.get(section, {}), **raw.get(section, {})}
              for section in _SCHEMA if section}

    wishlist, market = merged["wishlist"], merged["market"]
    if not wishlist["url"].strip():
        raise ConfigError("還沒設定願望清單（wishlist.url 是空的）：請執行 uv run sweetspot setup")
    match = _WISHLIST_URL.match(wishlist["url"])
    if not match:
        raise ConfigError("wishlist.url 格式錯誤：應為 https://store.steampowered.com/wishlist/profiles/<17 位數字>/")
    if market["region"] != "TW":
        raise ConfigError("market.region 只能是 TW（憲章 IX）")
    if not re.fullmatch(r"[A-Z]{2}", market["aux_region"]) or market["aux_region"] == "TW":
        raise ConfigError("market.aux_region 必須是 TW 以外的兩碼國家代碼")
    if not 1 <= wishlist["max_items"] <= 500:
        raise ConfigError("wishlist.max_items 必須介於 1 到 500")

    ref = merged["reference"]
    options_raw = raw.get(OPTIONS_SECTION, {})
    if not isinstance(options_raw, dict):
        raise ConfigError(f"[{OPTIONS_SECTION}] 必須是一個區段")
    purchase_options, option_warnings = _purchase_options(options_raw)
    warnings += option_warnings
    config = Config(
        path=path,
        wishlist_url=wishlist["url"],
        steamid=match.group(1),
        max_items=wishlist["max_items"],
        removed_tracking_months=wishlist["removed_tracking_months"],
        region="TW",
        aux_region=market["aux_region"],
        data_dir=data_dir_of(path, raw),
        cache=CacheConfig(**merged["cache"]),
        reference=ReferenceConfig(
            daily_budget_seconds=ref["daily_budget_seconds"],
            seed=ref["seed"],
            per_publisher_cap=ref["per_publisher_cap"],
            broad_per_stratum=ref["broad_per_stratum"],
            min_total_reviews=ref["min_total_reviews"],
            year_bins=_int_list(ref["year_bins"], "reference.year_bins"),
            price_bins_twd=_int_list(ref["price_bins_twd"], "reference.price_bins_twd"),
        ),
        legacy_cache_path=Path(merged["legacy"]["cache_path"]) if merged["legacy"]["cache_path"].strip() else None,
        preferences=_preferences({k: v for k, v in merged["preferences"].items() if k in _SCHEMA["preferences"]}),
        purchase_options=purchase_options,
    )
    return config, warnings
