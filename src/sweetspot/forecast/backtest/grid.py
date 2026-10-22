"""Parameter grid on the tuning part and the choice rule of spec FR-011 (feature 004 research R7).

1. Drop settings whose US Brier is significantly worse than the current model (95% interval above 0).
2. Take the lowest TW Brier (ties: the earlier setting).
3. A setting with a smaller `min_sales` than the current model turns some low-confidence games normal; their
   TW Brier (by_own_sales groups) must not be worse than the current model's, or the best setting with
   min_sales ≥ the current one is taken instead.
"""

import itertools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from sweetspot.forecast.backtest.compare import GROUP_LABEL, Comparison, compare_results, group_comparison
from sweetspot.forecast.backtest.dataset import BacktestDataset
from sweetspot.forecast.backtest.runner import run_backtest
from sweetspot.forecast.models import build_model, current_model, model_class

FR004_GROUPS = ("2", "3-5", "6+")      # feature 008 FR-004: games with more records must not get significantly worse


class GridError(ValueError):
    pass


@dataclass
class GridRow:
    params: dict[str, Any]
    result: dict[str, Any]              # TW and US merged
    comparison: Comparison              # against the current model on the same part
    files: tuple[str, ...]
    excluded: bool = field(default=False)
    excluded_reason: str | None = field(default=None)    # us-worse | fr-003 | own-sales-worse:<group>


def expand(grid: Sequence[tuple[str, Sequence[str]]]) -> list[dict[str, str]]:
    keys = [k for k, _ in grid]
    return [dict(zip(keys, values)) for values in itertools.product(*(v for _, v in grid))]


def _only(dataset: BacktestDataset, region: str) -> BacktestDataset:
    return replace(dataset, regions={region: dataset.regions[region]})


def _merge(parts: Sequence[dict[str, Any]]) -> dict[str, Any]:
    merged = {**parts[0], "regions": {}, "per_game": {}, "per_game_by_own_sales": {}, "errors": [],
              "dataset": {**parts[0]["dataset"], "regions": {}}}
    for part in parts:
        merged["regions"].update(part["regions"])
        merged["per_game"].update(part["per_game"])
        merged["per_game_by_own_sales"].update(part.get("per_game_by_own_sales", {}))
        merged["dataset"]["regions"].update(part["dataset"]["regions"])
        merged["errors"] += part.get("errors", [])
    return merged


def run_grid(store, dataset: BacktestDataset, games, events, name: str, fixed: Mapping[str, str],
             grid: Sequence[tuple[str, Sequence[str]]], *, out_dir: Path | None,
             progress: Callable[[str], None] | None = None,
             runner=run_backtest) -> tuple[dict[str, Any], list[GridRow]]:
    if dataset.split == "validation":
        raise GridError("網格只能在調參組或全部資料上執行，不能用驗證組選參數（FR-011）")
    settings = expand(grid)
    note = progress or (lambda message: None)
    note("網格：現行模型")
    current, _ = runner(store, dataset, games, events, current_model(), out_dir=out_dir, progress=progress)
    us_cache: dict[tuple, tuple[dict[str, Any], str]] = {}
    rows = []
    for n, setting in enumerate(settings, 1):
        model = build_model(name, {**fixed, **setting})
        note(f"網格 {n}/{len(settings)}：" + ", ".join(f"{k}={v}" for k, v in model.params.items()))
        parts, files = [], []
        if "TW" in dataset.regions:
            tw, path = runner(store, _only(dataset, "TW"), games, events, model, out_dir=out_dir, progress=progress)
            parts.append(tw)
            files.append(str(path))
        if "US" in dataset.regions:
            key = tuple(sorted((k, v) for k, v in model.params.items() if k not in model.tw_only_params))
            if key not in us_cache:
                us, path = runner(store, _only(dataset, "US"), games, events, model, out_dir=out_dir,
                                  progress=progress)
                us_cache[key] = (us, str(path))
            parts.append(us_cache[key][0])
            files.append(us_cache[key][1])
        merged = _merge(parts)
        merged["model"] = {"name": model.name, "version": model.version, "params": dict(model.params)}
        rows.append(GridRow(dict(model.params), merged, compare_results(current, merged), tuple(files)))
    return current, rows


def _tw_brier(row: GridRow) -> float:
    return row.result["regions"]["TW"]["brier"]


def _sales_groups(result: dict[str, Any]) -> dict[str, float]:
    return {g["group"]: g["brier"] for g in result["regions"]["TW"].get("by_own_sales", []) if g["brier"] is not None}


def _exclusion(current: dict[str, Any], row: GridRow) -> str | None:
    us = row.comparison.regions.get("US")
    if us and not us.omitted and us.low > 0:
        return "us-worse"
    model = row.result.get("model") or {}
    try:
        cls = model_class(model["name"], model.get("version"))
    except (KeyError, ValueError):
        cls = None
    reason = cls.grid_exclusion(row.params) if cls is not None and hasattr(cls, "grid_exclusion") else None
    if reason:
        return reason
    if "per_game_by_own_sales" in current and "per_game_by_own_sales" in row.result:
        for group in FR004_GROUPS:
            gc = group_comparison(current, row.result, "TW", group)
            if gc is not None and gc.low > 0:
                return f"own-sales-worse:{group}"
    return None


def select(current: dict[str, Any], current_params: Mapping[str, Any],
           rows: Sequence[GridRow]) -> tuple[GridRow | None, list[str]]:
    for row in rows:
        row.excluded_reason = _exclusion(current, row)
        row.excluded = row.excluded_reason is not None
    kept = [r for r in rows if not r.excluded]
    if not kept:
        if all(r.excluded_reason == "us-worse" for r in rows):
            return None, ["每個設定的美國區都比現行模型顯著變差，不推薦任何設定"]
        return None, ["每個設定都被排除（美國區、FR-003 或 FR-004），不推薦任何設定"]
    chosen = min(kept, key=_tw_brier)                  # min() keeps the first of equal values
    notes = []
    floor = current_params.get("min_sales")
    lowered = chosen.params.get("min_sales")
    if isinstance(floor, int) and isinstance(lowered, int) and lowered < floor:
        base, mine = _sales_groups(current), _sales_groups(chosen.result)
        groups = [str(k) if k < 3 else "3+" for k in range(lowered, floor)]
        worse = [g for g in groups if g in base and g in mine and mine[g] > base[g]]
        if worse:
            g = worse[0]
            fallback = [r for r in kept if r.params.get("min_sales", floor) >= floor]
            notes.append(f"min_sales={lowered} 讓本身只有 {g} 場的遊戲變成一般信心，但這一組的台灣區 Brier "
                         f"{mine[g]:.4f} 比現行模型的 {base[g]:.4f} 差（FR-011 第 3 步），改選 min_sales ≥ {floor} 中最好的")
            chosen = min(fallback, key=_tw_brier) if fallback else None
            if chosen is None:
                notes.append(f"沒有 min_sales ≥ {floor} 的設定可選")
    return chosen, notes


def _status(reason: str | None) -> str:
    if reason == "fr-003":
        return "違反 FR-003（見過的等級沒有收縮），僅供對照"
    if reason and reason.startswith("own-sales-worse:"):
        return f"{GROUP_LABEL[reason.split(':', 1)[1]]}顯著變差（FR-004），排除"
    return "美國區顯著變差，排除"


def _label(params: Mapping[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in params.items())


def format_grid_record(*, date: str, name: str, split: str, current: dict[str, Any], rows: Sequence[GridRow],
                       chosen: GridRow | None, notes: Sequence[str]) -> str:
    part = {"tuning": "調參組", "all": "全部資料"}.get(split, split)
    ds = current["dataset"]
    ids = "、".join(f"{'台灣區' if r == 'TW' else '美國區'} `{v['dataset_id'][:8]}…`" for r, v in sorted(ds["regions"].items()))
    cur = current["model"]
    lines = [f"## {date} · {name} {part}網格", "",
             f"- 資料集：{ids}（截止 {(ds.get('cutoff') or '')[:10]}）",
             f"- 現行：{cur['name']} {cur['version']} {{{_label(cur['params'])}}}，台灣區 "
             f"{current['regions']['TW']['brier']:.4f}" + (f"、美國區 {current['regions']['US']['brier']:.4f}"
                                                          if "US" in current["regions"] else ""), "",
             "| 設定 | 台灣區 Brier | 差距 [95% 區間] | 美國區 Brier | 差距 [95% 區間] | 結果 |",
             "|---|---|---|---|---|---|"]
    for row in rows:
        tw, us = row.comparison.regions["TW"], row.comparison.regions.get("US")
        us_cells = ("— | —" if us is None or us.omitted else
                    f"{us.brier_b:.4f} | {us.diff:+.4f} [{us.low:+.4f}, {us.high:+.4f}]")
        status = _status(row.excluded_reason) if row.excluded else ("**選中**" if row is chosen else "")
        lines.append(f"| `{_label(row.params)}` | {tw.brier_b:.4f} | {tw.diff:+.4f} [{tw.low:+.4f}, {tw.high:+.4f}] | "
                     f"{us_cells} | {status} |")
    lines.append("")
    lines += [f"- {n}" for n in notes]
    lines.append(f"**選中：`{_label(chosen.params)}`**。" if chosen else "**選中：無**。")
    lines.append("")
    return "\n".join(lines)
