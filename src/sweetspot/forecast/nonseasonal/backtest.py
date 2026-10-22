"""Backtest, comparison and grid for non-seasonal forecasts (feature 007 research R2, R3; contracts/cli-and-report.md).

A unit is game × as_of × h × d. It is scored only when the game's TW history is known through as_of + h, whether or
not the arrival already happened (unlike 002, where an early "occurred" is counted before the sale ends). The
reference score is the population share b(h, d) the model itself is smoothed toward.
"""

import hashlib
import json
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sweetspot import __version__
from sweetspot.calendar import SaleEvent
from sweetspot.config import Preferences
from sweetspot.forecast.backtest.compare import CompareError, bootstrap_interval
from sweetspot.forecast.backtest.dataset import BacktestDataset, RegionDataset
from sweetspot.forecast.backtest.split import SALT
from sweetspot.forecast.contract import LEVELS, iso, write_json_atomic
from sweetspot.forecast.engine import is_paid_at
from sweetspot.forecast.evidence import GameData, population_view
from sweetspot.forecast.nonseasonal import EARLIER_THRESHOLD, HORIZONS, TOL, build_ns_model
from sweetspot.forecast.nonseasonal.engine import predict_ns
from sweetspot.forecast.nonseasonal.events import arrived_levels
from sweetspot.forecast.nonseasonal.evidence import NSFrame, clock_state
from sweetspot.forecast.salepoints import sale_points
from sweetspot.timeutil import now_utc

SCHEMA = "steamsage.ns-backtest/1"
SCORING = "ns-fully-observed/1"
THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7)
COUNT_LABELS = ("0", "1-2", "3-4", "5+")
SIMPLER_MARGIN = 0.001                      # research R3: within this, the simpler setting wins


def ns_dataset_id(rd: RegionDataset) -> str:
    """The seasonal dataset's identity plus everything that decides the non-seasonal units."""
    header = {"dataset_id": rd.dataset_id, "horizons": list(HORIZONS), "tol_seconds": TOL.total_seconds(),
              "scoring": SCORING}
    return hashlib.sha256(json.dumps(header, sort_keys=True).encode("utf-8")).hexdigest()


def _present(games: Mapping[int, GameData], apps: Sequence[int], as_of: datetime) -> list[int]:
    return [a for a in apps if a in games and "TW" in games[a].series
            and games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]


def earlier_decisions(dataset: BacktestDataset, games: Mapping[int, GameData], events: Sequence[SaleEvent], *,
                      preferences: Preferences | None = None,
                      progress: Callable[[str], None] | None = None) -> dict[tuple[int, datetime], tuple]:
    """(group, sweet_pct, start of the sweet sale) of the current seasonal model and rule at every as_of."""
    from sweetspot.decision.backtest import decisions_multi
    from sweetspot.forecast.models import current_model

    rd = dataset.regions["TW"]
    model, prefs = current_model(), preferences or Preferences()
    out = {}
    for n, as_of in enumerate(rd.schedule, 1):
        if progress:
            progress(f"季節決策 {n}/{len(rd.schedule)}（{as_of:%Y-%m-%d}）")
        present = _present(games, rd.apps, as_of)
        points = sale_points([e for e in events if e.start <= as_of], as_of)
        if not present or not points:
            continue
        pool = _present(games, rd.population_apps, as_of)
        model.prepare(population_view((games[a] for a in pool), as_of, "TW"))
        for app, r in decisions_multi(games, present, as_of, points, model, [(prefs, None)])[0].items():
            if not isinstance(r, str):
                out[(app, as_of)] = (r.group, r.sweet_pct, points[r.sweet_index - 1].start)
    return out


class _Acc:
    """Per-game sums for one group; Brier = mean over games of each game's mean (every game weighs the same)."""

    def __init__(self):
        self.games: dict[int, list] = defaultdict(lambda: [0, 0.0, 0.0])

    def add(self, app: int, err: float, ref: float) -> None:
        g = self.games[app]
        g[0] += 1
        g[1] += err
        g[2] += ref

    def result(self) -> dict[str, Any]:
        rows = [g for g in self.games.values() if g[0]]
        if not rows:
            return {"brier": None, "reference_brier": None, "units": 0, "games": 0}
        return {"brier": sum(g[1] / g[0] for g in rows) / len(rows),
                "reference_brier": sum(g[2] / g[0] for g in rows) / len(rows),
                "units": sum(g[0] for g in rows), "games": len(rows)}


def _params6(params: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(dict(params), sort_keys=True).encode()).hexdigest()[:6]


def result_filename(model, ns_id: str, started: datetime) -> str:
    return (f"{started.strftime('%Y%m%dT%H%M%SZ')}_ns-{model.name}-{model.version}_{_params6(model.params)}"
            f"_TW_{ns_id[:8]}.json")


def build_frame(dataset: BacktestDataset, games: Mapping[int, GameData], events: Sequence[SaleEvent], history: str,
                share_cache: dict | None = None) -> NSFrame:
    rd = dataset.regions["TW"]
    needed = set(rd.apps) | set(rd.population_apps)
    return NSFrame({a: games[a] for a in needed if a in games}, events, history, population=list(rd.population_apps),
                   share_cache=share_cache)


def run_ns_backtest(dataset: BacktestDataset, games: Mapping[int, GameData], events: Sequence[SaleEvent], model, *,
                    earlier: bool = True, decisions: Mapping | None = None, frame: NSFrame | None = None,
                    out_dir: Path | None = None, progress: Callable[[str], None] | None = None,
                    now: datetime | None = None) -> tuple[dict[str, Any], Path | None]:
    started_at = now or now_utc()
    clock = time.monotonic()
    rd = dataset.regions["TW"]
    ns_id = ns_dataset_id(rd)
    if frame is None:
        frame = build_frame(dataset, games, events, model.params["history"])
    if earlier and decisions is None:
        decisions = earlier_decisions(dataset, games, events, progress=progress)
    overall, by_h = _Acc(), defaultdict(_Acc)
    by_conf, by_count = defaultdict(_Acc), defaultdict(_Acc)
    scored, skipped = Counter(), Counter()
    calib = defaultdict(lambda: [0, 0.0, 0])
    point = [0, 0]
    early = Counter()
    said = {th: [0, 0] for th in THRESHOLDS}
    errors = []
    for n, as_of in enumerate(rd.schedule, 1):
        if progress:
            progress(f"非季節回測 分析時點 {n}/{len(rd.schedule)}（{as_of:%Y-%m-%d}）")
        present = _present(games, rd.apps, as_of)
        if not present:
            continue
        pool = _present(games, rd.population_apps, as_of)
        population = frame.population_at(as_of, pool)
        model.prepare(population)
        for app in present:
            ev = frame.evidence(app, as_of)
            out = predict_ns(model, ev)
            if isinstance(out, str):
                errors.append({"app_id": app, "as_of": as_of.strftime("%Y-%m-%d"), "reason": out})
                continue
            count = COUNT_LABELS[clock_state([a.at for a in ev.arrivals if a.from_cut == 0], as_of)[0]]
            g = frame.games[app]
            known = g.tw.known_until
            reached = {}
            for i, h in enumerate(HORIZONS):
                hi = as_of + timedelta(days=h)
                if known is None or known < hi:
                    skipped[h] += len(LEVELS)
                    continue
                got = reached[h] = arrived_levels(g.tw_arrivals, as_of, hi, LEVELS)
                for j, d in enumerate(LEVELS):
                    p, r, o = out.probabilities[i][j], population.share.get((h, d), 0.0), d in got
                    err, ref = (p - o) ** 2, (r - o) ** 2
                    for acc in (overall, by_h[h], by_conf[out.confidence], by_count[count]):
                        acc.add(app, err, ref)
                    scored[h] += 1
                    b = calib[min(int(p * 10), 9)]
                    b[0] += 1
                    b[1] += p
                    b[2] += o
                    if p >= 0.5:
                        point[0] += 1
                        point[1] += o
            if decisions is None or (app, as_of) not in decisions:
                continue
            group, pct, sale_start = decisions[(app, as_of)]
            if group == "now":
                continue
            hs = [h for h in HORIZONS if as_of + timedelta(days=h) <= sale_start]
            if not hs:
                early["no_horizon"] += 1
                continue
            h = hs[-1]
            if h not in reached:
                early["censored"] += 1
                continue
            if out.confidence != "normal":
                early["low_confidence"] += 1
                continue
            hit = pct in reached[h]
            early["eligible"] += 1
            early["eligible_hit"] += hit
            p = out.probabilities[HORIZONS.index(h)][LEVELS.index(pct)]
            for th in THRESHOLDS:
                if p >= th:
                    said[th][0] += 1
                    said[th][1] += hit
    main = overall.result()
    result = {
        "schema": SCHEMA,
        "model": {"name": model.name, "version": model.version, "params": dict(model.params)},
        "dataset": {"cutoff": iso(dataset.cutoff), "split": {"name": dataset.split, "salt": SALT},
                    "schedule": [t.strftime("%Y-%m-%d") for t in rd.schedule], "horizons": list(HORIZONS),
                    "levels": list(LEVELS), "dataset_id": rd.dataset_id, "ns_dataset_id": ns_id,
                    "scoring": SCORING, "games": len(rd.apps), "population_games": len(rd.population_apps)},
        "units": {"scored": {str(h): scored[h] for h in HORIZONS}, "not_scored": {str(h): skipped[h] for h in HORIZONS}},
        "brier": main["brier"], "reference_brier": main["reference_brier"], "games": main["games"],
        "by_horizon": {str(h): by_h[h].result() for h in HORIZONS},
        "by_confidence": {k: v.result() for k, v in sorted(by_conf.items())},
        "by_count": {k: by_count[k].result() for k in COUNT_LABELS if k in by_count},
        "calibration": [{"bin": f"{b / 10:.1f}", "n": v[0], "predicted": v[1] / v[0], "actual": v[2] / v[0]}
                        for b, v in sorted(calib.items())],
        "point_hit_rate": {"n": point[0], "hits": point[1], "rate": point[1] / point[0] if point[0] else None},
        "earlier": None if decisions is None else {
            "eligible": early["eligible"], "eligible_hit": early["eligible_hit"], "no_horizon": early["no_horizon"],
            "censored": early["censored"], "low_confidence": early["low_confidence"],
            "thresholds": [{"threshold": th, "said": s, "hit": x, "rate": x / s if s else None}
                           for th, (s, x) in said.items()]},
        "per_game": {str(app): list(v) for app, v in sorted(overall.games.items()) if v[0]},
        "errors": errors,
        "run": {"started_at": iso(started_at), "finished_at": iso(now_utc()),
                "seconds": round(time.monotonic() - clock, 1), "steamsage_version": __version__},
    }
    path = None
    if out_dir is not None:
        path = write_json_atomic(Path(out_dir) / result_filename(model, ns_id, started_at), result)
    return result, path


# --- comparison --------------------------------------------------------------------------------------------

REFERENCE = "整體比例"
VALIDATION_TITLE = "（非季節驗證組 · 第 {n} 次）"


def model_label(model: Mapping[str, Any]) -> str:
    params = ", ".join(f"{k}={v}" for k, v in sorted(model["params"].items()))
    return f"{model['name']} {model['version']} {{{params}}}"


@dataclass(frozen=True)
class NSComparison:
    model: dict[str, Any]
    against: str                     # 整體比例, or the other model's label
    split: str
    ns_dataset_id: str
    cutoff: str | None
    brier: float
    brier_against: float
    diff: float                      # model − against, per-game mean
    low: float
    high: float
    games: int
    by_horizon: dict[str, tuple[float | None, float | None]]
    earlier: dict[str, Any] | None
    verdict: str | None              # 優於 / 未優於 on the validation part; None elsewhere


def _split(r: Mapping[str, Any]) -> str:
    return (r["dataset"].get("split") or {}).get("name", "all")


def compare_ns(result: Mapping[str, Any], against: Mapping[str, Any] | None = None) -> NSComparison:
    """`result` against its own reference (the population share), or against another result."""
    ns_id = result["dataset"]["ns_dataset_id"]
    mine = {app: v for app, v in result["per_game"].items() if v[0]}
    if against is None:
        other, label = {app: (v[0], v[2]) for app, v in mine.items()}, REFERENCE
        other_brier = result["reference_brier"]
        by_h = {h: (v.get("brier"), v.get("reference_brier")) for h, v in result["by_horizon"].items()}
    else:
        if against["dataset"]["ns_dataset_id"] != ns_id:
            raise CompareError(f"非季節資料集不同：{ns_id[:12]}… ≠ {against['dataset']['ns_dataset_id'][:12]}…")
        if _split(against) != _split(result):
            raise CompareError(f"兩份結果的切分不同：{_split(result)} ≠ {_split(against)}")
        other = {app: (v[0], v[1]) for app, v in against["per_game"].items() if v[0]}
        for app in sorted(set(mine) | set(other), key=int):
            if app not in mine or app not in other or mine[app][0] != other[app][0]:
                raise CompareError(f"評分單位不同：遊戲 {app}")
        label, other_brier = model_label(against["model"]), against["brier"]
        by_h = {h: (v.get("brier"), against["by_horizon"].get(h, {}).get("brier"))
                for h, v in result["by_horizon"].items()}
    apps = sorted(mine, key=int)
    if not apps:
        raise CompareError("沒有任何計分的遊戲，無法比較")
    diffs = [mine[a][1] / mine[a][0] - other[a][1] / other[a][0] for a in apps]
    low, high = bootstrap_interval(diffs, int(ns_id[:8], 16))
    split = _split(result)
    verdict = None if split != "validation" else ("優於" if high < 0 else "未優於")
    return NSComparison(dict(result["model"]), label, split, ns_id, result["dataset"].get("cutoff"),
                        result["brier"], other_brier, sum(diffs) / len(diffs), low, high, len(apps), by_h,
                        result.get("earlier"), verdict)


def check_ns_attempt(path: Path, c: NSComparison, attempt: int | None, change: str | None) -> None:
    """At most 3 recorded validation comparisons per model version, counted apart from 004 and 005 (spec FR-009)."""
    if c.split != "validation":
        return
    if attempt is None:
        raise CompareError("非季節驗證組的比較紀錄必須加上 --attempt（第幾次，1–3）")
    if not 1 <= attempt <= 3:
        raise CompareError("非季節驗證組最多比較 3 次：--attempt 必須是 1–3")
    if attempt >= 2 and not (change or "").strip():
        raise CompareError("第 2、3 次比較必須用 --change 說明這次改了什麼、為什麼改")
    path = Path(path)
    if not path.exists():
        return
    title = VALIDATION_TITLE.format(n=attempt)
    name = f"· {c.model['name']} {c.model['version']} "
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## ") and name in line and line.endswith(title):
            raise CompareError(f"比較文件中已有 {c.model['name']} {c.model['version']} 的非季節驗證組第 {attempt} 次紀錄")


def _f(value: float | None) -> str:
    return "—" if value is None else f"{value:.4f}"


def _earlier_line(earlier: Mapping[str, Any] | None) -> str | None:
    if not earlier:
        return None
    row = next((r for r in earlier["thresholds"] if r["threshold"] == EARLIER_THRESHOLD), None)
    if row is None:
        return None
    rate = "—" if row["rate"] is None else f"{row['rate']:.1%}"
    return (f"- 可能更早到價（門檻 {EARLIER_THRESHOLD:.0%}：說 {row['said']} 次，實際到價 {row['hit']} 次，{rate}；"
            f"可判斷 {earlier['eligible']} 次）")


def format_ns_compare_record(c: NSComparison, *, date: str, files: Sequence[str], attempt: int | None = None,
                             change: str | None = None) -> str:
    suffix = VALIDATION_TITLE.format(n=attempt) if c.split == "validation" and attempt else f"（{c.split}）"
    lines = [f"## {date} · {model_label(c.model)} vs {c.against}{suffix}", "",
             f"- 非季節資料集 `{c.ns_dataset_id[:8]}…`（截止 {(c.cutoff or '')[:10]}，切分 {c.split}）",
             f"- 結果檔：{'、'.join(f'`{f}`' for f in files)}"]
    if change:
        lines.append(f"- 這次的修改：{change}")
    earlier = _earlier_line(c.earlier)
    if earlier:
        lines.append(earlier)
    lines += ["", f"| 期間 | {model_label(c.model).split(' {')[0]} Brier | {c.against} Brier |", "|---|---|---|"]
    for h, (a, b) in c.by_horizon.items():
        lines.append(f"| {h} 天 | {_f(a)} | {_f(b)} |")
    lines += [f"| 全體 | {_f(c.brier)} | {_f(c.brier_against)} |", "",
              f"差距（每款遊戲平均，模型 − {c.against}）{c.diff:+.4f}，95% 區間 [{c.low:+.4f}, {c.high:+.4f}]，{c.games} 款。"]
    if c.verdict:
        reason = "上限 < 0，顯著較好" if c.verdict == "優於" else "區間沒有全部低於 0"
        lines.append(f"**判定：{c.verdict}**（{reason}）。")
    else:
        lines.append("只報告，不判定（非驗證組）。")
    lines.append("")
    return "\n".join(lines)


# --- grid --------------------------------------------------------------------------------------------------

def _simplicity(params: Mapping[str, Any]) -> tuple:
    """Smaller is simpler: no clock, heavier smoothing, TW only."""
    return (bool(params.get("clock")), -int(params.get("smoothing", 0)), params.get("history") != "TW")


def select_ns(rows: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]]) -> tuple[dict | None, list[str]]:
    """Lowest Brier; within SIMPLER_MARGIN of it the simplest setting (research R3)."""
    valid = [(dict(p), r) for p, r in rows if r.get("brier") is not None and not r.get("errors")]
    if not valid:
        return None, ["沒有任何一組完整完成"]
    best = min(r["brier"] for _, r in valid)
    close = [(p, r) for p, r in valid if r["brier"] - best <= SIMPLER_MARGIN]
    chosen = min(close, key=lambda pr: (_simplicity(pr[0]), pr[1]["brier"]))[0]
    notes = [f"最低 Brier {best:.4f}"]
    if len(close) > 1:
        notes.append(f"{len(close)} 組在 {SIMPLER_MARGIN} 以內，選較簡單的（不用時鐘 > 較強的平滑 > 只用台灣區）")
    return chosen, notes


def run_ns_grid(dataset: BacktestDataset, games: Mapping[int, GameData], events: Sequence[SaleEvent], name: str,
                fixed: Mapping[str, str], grid: Sequence[tuple[str, Sequence[str]]], *, earlier: bool = True,
                out_dir: Path | None = None, progress: Callable[[str], None] | None = None):
    """Every combination of the grid; frames and the seasonal decisions are built once and shared."""
    combos = [dict(fixed)]
    for key, values in grid:
        combos = [c | {key: v} for c in combos for v in values]
    decisions = earlier_decisions(dataset, games, events, progress=progress) if earlier else None
    frames: dict[str, NSFrame] = {}
    share_cache: dict = {}
    rows = []
    for n, raw in enumerate(combos, 1):
        model = build_ns_model(name, raw)
        if progress:
            progress(f"網格 {n}/{len(combos)}：{model_label({'name': model.name, 'version': model.version, 'params': model.params})}")
        history = model.params["history"]
        if history not in frames:
            frames[history] = build_frame(dataset, games, events, history, share_cache)
        result, path = run_ns_backtest(dataset, games, events, model, earlier=earlier, decisions=decisions,
                                       frame=frames[history], out_dir=out_dir)
        rows.append((dict(model.params), result, path))
    return rows


def format_ns_grid_record(*, date: str, split: str, rows, chosen, notes, files: Sequence[str]) -> str:
    lines = [f"## {date} · non-seasonal 調參組網格（{split}）", "",
             "| 參數 | Brier | 30 天 | 60 天 | 90 天 | 整體比例 | 差距（95% 區間） | 結果檔 |",
             "|---|---|---|---|---|---|---|---|"]
    for (params, result), file in zip(rows, files):
        c = compare_ns(result)
        h = result["by_horizon"]
        label = ", ".join(f"{k}={v}" for k, v in sorted(params.items()))
        mark = " ✅" if params == chosen else ""
        lines.append(f"| `{label}`{mark} | {_f(result['brier'])} | {_f(h['30']['brier'])} | {_f(h['60']['brier'])} | "
                     f"{_f(h['90']['brier'])} | {_f(result['reference_brier'])} | "
                     f"{c.diff:+.4f} [{c.low:+.4f}, {c.high:+.4f}] | {file} |")
    lines += ["", f"**選定**：`{', '.join(f'{k}={v}' for k, v in sorted((chosen or {}).items()))}`。"
              + "；".join(notes) + "。", ""]
    return "\n".join(lines)
