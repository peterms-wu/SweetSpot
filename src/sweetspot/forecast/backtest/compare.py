"""Compare two backtest results (FR-028-FR-030; contracts/backtest-result.md).

Per region: paired bootstrap over games of (candidate − current) per-game mean Brier. 優於 needs the TW interval
entirely below 0 and the US interval not entirely above 0. Records are appended, never rewritten.
"""

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RESAMPLES = 2000
REGION_TITLE = {"TW": "台灣區（≤12 個月）", "US": "美國區（1–5 年）"}


class CompareError(ValueError):
    pass


@dataclass(frozen=True)
class RegionComparison:
    region: str
    brier_a: float | None
    brier_b: float | None
    diff: float
    low: float
    high: float
    games: int
    omitted: bool = False          # US skipped because the models differ only in TW-only params


@dataclass
class Comparison:
    model_a: dict[str, Any]
    model_b: dict[str, Any]
    cutoff: str | None
    dataset_ids: dict[str, str]
    regions: dict[str, RegionComparison]
    verdict: str
    reasons: list[str] = field(default_factory=list)
    split: str = "all"
    deeper: dict[str, tuple[float, float]] = field(default_factory=dict)   # region → (current, candidate)
    groups: dict[str, "GroupComparison"] = field(default_factory=dict)     # feature 008: --target-groups
    target_groups: tuple[str, ...] = ()


# --- feature 008: own-sales groups (spec FR-004, FR-009; research R6) --------------------------------------------

OWN_SALES_GROUPS = ("0", "1", "2", "3-5", "6+")
GROUP_LABEL = {"0": "0 場（低信心）", "1": "1 場", "2": "2 場", "3-5": "3–5 場", "6+": "6 場以上"}


@dataclass(frozen=True)
class GroupComparison:
    group: str
    brier_a: float
    brier_b: float
    diff: float
    low: float
    high: float
    games: int
    finished: tuple[tuple[float, float] | None, tuple[float, float] | None] = (None, None)  # (predicted, actual)


def _finished_group(result: dict[str, Any], region: str, group: str) -> tuple[float, float] | None:
    fc = (result.get("regions", {}).get(region) or {}).get("finished_calibration") or {}
    row = next((g for g in fc.get("groups", {}).get("own_sales", []) if g["group"] == group), None)
    return None if row is None else (row["predicted"], row["actual"])


def group_comparison(a: dict[str, Any], b: dict[str, Any], region: str, group: str) -> GroupComparison | None:
    """Game-paired comparison of one own-sales group (per_game_by_own_sales); None when no game has the group in
    both results. Same resampling as the region comparison, seeded by the region's dataset id."""
    ga = (a.get("per_game_by_own_sales") or {}).get(region, {})
    gb = (b.get("per_game_by_own_sales") or {}).get(region, {})
    apps = sorted((app for app in ga if group in ga[app] and group in gb.get(app, {})), key=int)
    if not apps:
        return None
    means_a = [ga[app][group][1] / ga[app][group][0] for app in apps]
    means_b = [gb[app][group][1] / gb[app][group][0] for app in apps]
    diffs = [y - x for x, y in zip(means_a, means_b)]
    low, high = bootstrap_interval(diffs, int(a["dataset"]["regions"][region]["dataset_id"][:8], 16))
    return GroupComparison(group, sum(means_a) / len(apps), sum(means_b) / len(apps), sum(diffs) / len(apps), low,
                           high, len(apps), (_finished_group(a, region, group), _finished_group(b, region, group)))


def _groups_phrase(groups) -> str:
    names = "、".join(GROUP_LABEL[g].split("（")[0] for g in groups)
    return f"本身 {names}" + ("兩組" if len(groups) == 2 else f"這 {len(groups)} 組" if len(groups) > 2 else "這一組")


def _tw_only_params(model: dict[str, Any]) -> frozenset[str]:
    from sweetspot.forecast.models import model_class

    try:
        cls = model_class(model["name"], model.get("version"))
    except ValueError:
        return frozenset()
    return frozenset(getattr(cls, "tw_only_params", ()))


def _only_tw_only_changes(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if (a["name"], a["version"]) != (b["name"], b["version"]):
        return False
    keys = set(a["params"]) | set(b["params"])
    changed = {k for k in keys if a["params"].get(k) != b["params"].get(k)}
    return changed <= _tw_only_params(a)


def _split(result: dict[str, Any]) -> str:
    return (result["dataset"].get("split") or {}).get("name", "all")


def _deeper(a: dict[str, Any], b: dict[str, Any], regions) -> dict[str, tuple[float, float]]:
    out = {}
    for region in regions:
        pair = tuple((r["regions"].get(region) or {}).get("deeper_than_past", {}).get("brier") for r in (a, b))
        if None not in pair:
            out[region] = pair
    return out


def _game_means(result: dict[str, Any], region: str) -> dict[str, tuple[int, float]]:
    return {app: (n, sse) for app, (n, sse) in result["per_game"][region].items()}


def bootstrap_interval(diffs: list[float], seed: int) -> tuple[float, float]:
    """2.5% / 97.5% of the mean over RESAMPLES resamples (one value per game; the seed makes it reproducible).
    Shared by the model, non-seasonal and post-sale comparisons."""
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(RESAMPLES))
    return means[round(0.025 * (RESAMPLES - 1))], means[round(0.975 * (RESAMPLES - 1))]


def _compare_region(region: str, a: dict[str, Any], b: dict[str, Any]) -> RegionComparison:
    id_a = a["dataset"]["regions"][region]["dataset_id"]
    id_b = b["dataset"]["regions"][region]["dataset_id"]
    if id_a != id_b:
        raise CompareError(f"{REGION_TITLE[region]}的資料集不同：{id_a[:12]}… ≠ {id_b[:12]}…")
    ga, gb = _game_means(a, region), _game_means(b, region)
    for app in sorted(set(ga) | set(gb), key=int):
        if app not in ga or app not in gb or ga[app][0] != gb[app][0]:
            raise CompareError(f"{REGION_TITLE[region]}的評分單位不同：遊戲 {app} "
                               f"（{ga.get(app, (0,))[0]} ≠ {gb.get(app, (0,))[0]}）")
    apps = sorted(ga, key=int)
    if not apps:
        raise CompareError(f"{REGION_TITLE[region]}沒有任何計分的遊戲，無法比較")
    diffs = [gb[app][1] / gb[app][0] - ga[app][1] / ga[app][0] for app in apps]
    low, high = bootstrap_interval(diffs, int(id_a[:8], 16))
    return RegionComparison(region, a["regions"][region]["brier"], b["regions"][region]["brier"],
                            sum(diffs) / len(diffs), low, high, len(apps))


def compare_results(a: dict[str, Any], b: dict[str, Any], target_groups: tuple[str, ...] = ()) -> Comparison:
    """`a` is the current model (or baseline for the comparison), `b` the candidate. With `target_groups`
    (feature 008 FR-009) the candidate must also have a lower TW Brier (point estimate) in each of those groups."""
    unknown = [g for g in target_groups if g not in OWN_SALES_GROUPS]
    if unknown:
        raise CompareError(f"未知的場數組：{', '.join(unknown)}（可用：{', '.join(OWN_SALES_GROUPS)}）")
    for which, r in (("現行", a), ("候選", b)):
        if "TW" not in r.get("per_game", {}):
            raise CompareError(f"{which}結果沒有台灣區，無法比較（FR-028）")
    if _split(a) != _split(b):
        raise CompareError(f"兩份結果的切分不同：{_split(a)} ≠ {_split(b)}（004 FR-010）")
    regions = {"TW": _compare_region("TW", a, b)}
    has_us = ["US" in r.get("per_game", {}) for r in (a, b)]
    if all(has_us):
        regions["US"] = _compare_region("US", a, b)
    elif _only_tw_only_changes(a["model"], b["model"]):
        games = len((a if has_us[0] else b)["per_game"].get("US", {}))
        brier = (a if has_us[0] else b)["regions"].get("US", {}).get("brier")
        regions["US"] = RegionComparison("US", brier if has_us[0] else None, brier if has_us[1] else None,
                                         0.0, 0.0, 0.0, games, omitted=True)
    else:
        raise CompareError("只有一份結果有美國區，而兩個模型的差異不只在「只影響台灣區」的參數；"
                           "請兩份都跑美國區（FR-028）")

    reasons = []
    tw, us = regions["TW"], regions["US"]
    tw_ok = tw.high < 0
    us_ok = us.omitted or us.low <= 0
    tw_verdict = "，上限 < 0，顯著較好" if tw_ok else ("，下限 > 0，顯著較差" if tw.low > 0 else "，區間包含 0，沒有顯著差異")
    reasons.append(f"台灣區差距 {tw.diff:+.4f}，95% 區間 [{tw.low:+.4f}, {tw.high:+.4f}]{tw_verdict}")
    if us.omitted:
        reasons.append("美國區：兩個模型只差「只影響台灣區」的參數，結果依構造相同，未重跑，視為沒有變差")
    else:
        reasons.append(f"美國區差距 {us.diff:+.4f}，95% 區間 [{us.low:+.4f}, {us.high:+.4f}]"
                       + ("，沒有顯著變差" if us_ok else "，下限 > 0，顯著變差"))
    groups, groups_ok = {}, True
    for g in target_groups:
        gc = group_comparison(a, b, "TW", g)
        if gc is None:
            raise CompareError(f"結果沒有 {GROUP_LABEL[g]}的逐遊戲分數（per_game_by_own_sales），無法判定")
        groups[g] = gc
        lower = gc.brier_b < gc.brier_a
        groups_ok = groups_ok and lower
        reasons.append(f"{GROUP_LABEL[g]}：台灣區 Brier {gc.brier_a:.4f} → {gc.brier_b:.4f}，" +
                       ("較低" if lower else "沒有比現行低"))
    return Comparison(model_a=a["model"], model_b=b["model"], cutoff=a["dataset"].get("cutoff"),
                      dataset_ids={r: a["dataset"]["regions"][r]["dataset_id"]
                                   for r in a["dataset"]["regions"] if r in b["dataset"]["regions"]},
                      regions=regions, verdict="優於" if tw_ok and us_ok and groups_ok else "未優於", reasons=reasons,
                      split=_split(a), deeper=_deeper(a, b, [r for r in regions if not regions[r].omitted]),
                      groups=groups, target_groups=tuple(target_groups))


VALIDATION_TITLE = "（驗證組 · 第 {n} 次）"


def check_attempt(path: Path, c: Comparison, attempt: int | None, change: str | None) -> None:
    """Validation-part comparisons are limited to 3 recorded attempts (004 spec FR-013)."""
    if c.split != "validation":
        return
    if attempt is None:
        raise CompareError("驗證組的比較紀錄必須加上 --attempt（第幾次，1–3）")
    if not 1 <= attempt <= 3:
        raise CompareError("驗證組最多比較 3 次：--attempt 必須是 1–3")
    if attempt >= 2 and not (change or "").strip():
        raise CompareError("第 2、3 次比較必須用 --change 說明這次改了什麼、為什麼改")
    path = Path(path)
    if path.exists():
        title = VALIDATION_TITLE.format(n=attempt)
        name = f"· {c.model_b['name']} {c.model_b['version']} "      # attempts count per model version (008 FR-010)
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## ") and name in line and line.endswith(title):
                raise CompareError(f"比較文件中已有 {c.model_b['name']} {c.model_b['version']} 的驗證組第 {attempt} 次紀錄")


def _model_label(model: dict[str, Any]) -> str:
    params = ", ".join(f"{k}={v}" for k, v in sorted(model["params"].items()))
    return f"{model['name']} {model['version']} {{{params}}}"


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.4f}"


def format_record(c: Comparison, *, date: str, files: tuple[str, str], attempt: int | None = None,
                  change: str | None = None) -> str:
    ids = "、".join(f"{'台灣區' if r == 'TW' else '美國區'} `{i[:8]}…`" for r, i in sorted(c.dataset_ids.items()))
    suffix = VALIDATION_TITLE.format(n=attempt) if c.split == "validation" and attempt else ""
    lines = [f"## {date} · {_model_label(c.model_b)} vs 現行 {_model_label(c.model_a)}{suffix}", "",
             f"- 資料集：{ids}（截止 {(c.cutoff or '')[:10]}）",
             f"- 結果檔：`{files[0]}`、`{files[1]}`"]
    if change:
        lines.append(f"- 這次的修改：{change}")
    if c.deeper:
        parts = "；".join(f"{'台灣區' if r == 'TW' else '美國區'} {a:.4f} → {b:.4f}" for r, (a, b) in c.deeper.items())
        lines.append(f"- 「比過去更深」的 Brier：{parts}（不影響判定）")
    lines += ["",
             "| 區域 | 現行 Brier | 候選 Brier | 差距（候選 − 現行） | 95% 區間 | 遊戲數 |",
             "|---|---|---|---|---|---|"]
    for region in ("TW", "US"):
        r = c.regions.get(region)
        if r is None:
            continue
        if r.omitted:
            lines.append(f"| {REGION_TITLE[region]} | {_fmt(r.brier_a)} | —（未重跑） | 0（依構造相同，未重跑） | — | {r.games} |")
        else:
            lines.append(f"| {REGION_TITLE[region]} | {_fmt(r.brier_a)} | {_fmt(r.brier_b)} | {r.diff:+.4f} | "
                         f"[{r.low:+.4f}, {r.high:+.4f}] | {r.games} |")
    if c.target_groups:
        lines += ["", f"另外要求{_groups_phrase(c.target_groups)}的台灣區 Brier 都比現行低（點估計）（feature 008 FR-009）：", "",
                  "| 場數組 | 現行 Brier | 候選 Brier | 差距 | 95% 區間 | 遊戲數 | 只計已結束：預測 − 實際（百分點） |",
                  "|---|---|---|---|---|---|---|"]
        for g in c.target_groups:
            gc = c.groups[g]
            fa, fb = gc.finished
            gap = "—" if fa is None or fb is None else f"{(fa[0] - fa[1]) * 100:+.1f} → {(fb[0] - fb[1]) * 100:+.1f}"
            lines.append(f"| {GROUP_LABEL[g]} | {gc.brier_a:.4f} | {gc.brier_b:.4f} | {gc.diff:+.4f} | "
                         f"[{gc.low:+.4f}, {gc.high:+.4f}] | {gc.games} | {gap} |")
    lines += ["", f"**判定：{c.verdict}**。" + "；".join(c.reasons) + "。", ""]
    return "\n".join(lines)


def baseline_record(result: dict[str, Any], *, date: str, file: str, reason: str) -> str:
    """The first current model has nothing to beat (FR-031): record it as the floor."""
    lines = [f"## {date} · {_model_label(result['model'])}（建立下限）", "",
             f"- 資料截止：{result['dataset'].get('cutoff', '')[:10]}",
             f"- 結果檔：`{file}`", "",
             "| 區域 | Brier | 參照分數 | 遊戲數 | 資料集 |", "|---|---|---|---|---|"]
    for region in ("TW", "US"):
        r = result["regions"].get(region)
        if r:
            ds = result["dataset"]["regions"][region]["dataset_id"]
            lines.append(f"| {REGION_TITLE[region]} | {_fmt(r['brier'])} | {_fmt(r.get('reference_brier'))} | "
                         f"{r['games']} | `{ds[:8]}…` |")
    lines += ["", f"**判定：建立下限**。{reason}。", ""]
    return "\n".join(lines)


def append_record(path: Path, text: str) -> None:
    """Append only: the existing bytes are never rewritten (FR-030)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_bytes() if path.exists() else b""
    separator = b"" if not existing or existing.endswith(b"\n") else b"\n"
    with path.open("ab") as fh:
        fh.write(separator + b"\n" + text.encode("utf-8"))
