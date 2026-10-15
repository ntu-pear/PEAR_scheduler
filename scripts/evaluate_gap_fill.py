"""
Compares gap filling on random centres: Free and Easy, avoidable Free and Easy, rule
violations, liked activities, variety and run time.

    python scripts/evaluate_gap_fill.py --seeds 20 --out gap_fill.csv
    python scripts/evaluate_gap_fill.py --baseline-repo ../baseline   # also run older code

--baseline-repo is a checkout of older scheduler code (e.g. git worktree add ../baseline
scheduler_staging, plus its pear_schedule/logger/config.py). It runs in its own process
on the same scenarios and is labelled "baseline". Needs the same env vars as the unit tests.
"""

import argparse
import csv
import logging
import os
import pickle
import random
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pear_schedule.scheduler.invariants import FREE_AND_EASY, analyse_free_and_easy, base_title, check_rules  # noqa: E402
from pear_schedule.scheduler.explain import gap_filled_slots  # noqa: E402
from tests.utils.schedule_scenarios import WEEK_START, make_scenario, patched, run  # noqa: E402

FLEXIBLE_SHARES = [0.0, 0.25, 0.5, 0.75, 1.0]
CENTRE = dict(patients=6, days=5, slots=14, pool_size=10, short_share=0.4, compulsory=3)

# runs inside the baseline checkout, no trace/explain there
BASELINE_RUNNER = r'''
import datetime, pickle, sys, time, types, logging
from contextlib import ExitStack
from unittest.mock import patch, MagicMock
logging.disable(logging.CRITICAL)
from pear_schedule.scheduler.utils import build_schedules
from pear_schedule.scheduler.adhocScheduling import AdhocScheduler
from pear_schedule.scheduler.compulsoryScheduling import CompulsoryActivityScheduler
from pear_schedule.scheduler.groupScheduling import GroupActivityScheduler
from pear_schedule.scheduler.individualScheduling import PreferredActivityScheduler, RecommendedRoutineActivityScheduler
from pear_schedule.scheduler.medicationScheduling import medicationScheduler

scenarios, week_start = pickle.load(open(sys.argv[1], "rb"))
now = week_start + datetime.timedelta(hours=8)
class _Now(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return now
fake_dt = types.SimpleNamespace(datetime=_Now, date=datetime.date, timedelta=datetime.timedelta)
out = []
for config, views in scenarios:
    with ExitStack() as stack:
        for name, df in views.items():
            stack.enter_context(patch(f"pear_schedule.db_utils.views.{name}.get_data", return_value=df))
        stack.enter_context(patch("pear_schedule.scheduler.individualScheduling.DB.get_engine", return_value=MagicMock()))
        for mod in ("individualScheduling", "adhocScheduling", "medicationScheduling"):
            stack.enter_context(patch(f"pear_schedule.scheduler.{mod}.datetime", fake_dt))
        for cls in (CompulsoryActivityScheduler, RecommendedRoutineActivityScheduler, GroupActivityScheduler,
                    PreferredActivityScheduler, AdhocScheduler, medicationScheduler):
            stack.enter_context(patch.object(cls, "config", config, create=True))
        schedules = {}
        t = time.perf_counter()
        try:
            build_schedules(config, schedules)
            out.append((schedules, time.perf_counter() - t, None))
        except Exception as e:
            out.append((None, time.perf_counter() - t, repr(e)))
pickle.dump(out, open(sys.argv[2], "wb"))
'''


def run_baseline(repo, scenarios):
    with tempfile.TemporaryDirectory() as tmp:
        src, dst, runner = (os.path.join(tmp, n) for n in ("in.pkl", "out.pkl", "runner.py"))
        pickle.dump(([(s.config, s.views) for s in scenarios], WEEK_START), open(src, "wb"))
        open(runner, "w").write(BASELINE_RUNNER)
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [os.path.abspath(repo), os.environ.get("PYTHONPATH")]))}
        subprocess.run([sys.executable, runner, src, dst], cwd=repo, env=env, check=True)
        return pickle.load(open(dst, "rb"))


def measure(schedules, inputs, gap_filled=None):
    # blank slots get saved as Free and Easy by the writer
    schedules = {pid: [[v or FREE_AND_EASY for v in day] for day in days] for pid, days in schedules.items()}
    inputs.gap_filled = gap_filled or set()
    fe = analyse_free_and_easy(schedules, inputs)
    violations = [v for v in check_rules(schedules, inputs) if v.rule != "R8"]
    pool = {a.title: a.activity_id for a in inputs.pool}
    filled = liked = 0
    distinct = []
    for pid, days in schedules.items():
        likes = inputs.patients[pid].likes if pid in inputs.patients else set()
        titles = [base_title(v) for day in days for v in day if base_title(v) in pool]
        filled += len(titles)
        liked += sum(1 for t in titles if pool[t] in likes)
        distinct.append(len(set(titles)))
    total = sum(len(day) for days in schedules.values() for day in days)
    return {
        "slots": total,
        "free_and_easy": fe.total,
        "free_and_easy_pct": round(100 * fe.total / total, 2) if total else 0,
        "avoidable": fe.avoidable,
        # needs a trace, so not for baseline
        "avoidable_rearranged": fe.avoidable_rearranged if gap_filled is not None else "",
        "violations": len(violations),
        "liked_share_pct": round(100 * liked / filled, 2) if filled else 0,
        "liked_per_patient": round(liked / len(schedules), 2) if schedules else 0,
        "distinct_per_patient": round(statistics.mean(distinct), 2) if distinct else 0,
        **{f"data_{k}": v for k, v in fe.unavoidable.items()},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--out", default="gap_fill_evaluation.csv")
    parser.add_argument("--baseline-repo")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)

    scenarios = []
    for share in FLEXIBLE_SHARES:
        for seed in range(args.seeds):
            scenarios.append((share, seed, make_scenario(random.Random(seed), flexible_share=share, **CENTRE)))

    rows = []
    baseline = run_baseline(args.baseline_repo, [s for _, _, s in scenarios]) if args.baseline_repo else None
    for i, (share, seed, scenario) in enumerate(scenarios):
        with patched(scenario):
            from pear_schedule.scheduler.explain import collect_rule_inputs
            inputs = collect_rule_inputs(scenario.config, WEEK_START)
        results = {}
        if baseline:
            results["baseline"] = (*baseline[i], None)
        for strategy in ("greedy", "optimal"):
            t = time.perf_counter()
            schedules, tr, _ = run(scenario, strategy)
            results[strategy] = (schedules, time.perf_counter() - t, None, gap_filled_slots(tr))
        for strategy, (schedules, seconds, error, gap_filled) in results.items():
            row = {"flexible_share": share, "seed": seed, "strategy": strategy, "seconds": round(seconds, 4),
                   "crashed": int(error is not None), "error": error or ""}
            # a crashed run has no schedule to measure
            rows.append({**row, **(measure(schedules, inputs, gap_filled) if error is None else {})})

    keys = list(rows[0]) + sorted({k for r in rows for k in r} - set(rows[0]))
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys, restval=0)
        writer.writeheader()
        writer.writerows(rows)

    groups = defaultdict(list)
    for r in rows:
        groups[(r["flexible_share"], r["strategy"])].append(r)
    cols = ["free_and_easy_pct", "avoidable", "avoidable_rearranged", "violations", "liked_per_patient",
            "distinct_per_patient", "seconds"]
    print(f"{'flexible':>8} {'strategy':>9} {'crashed':>8} " + " ".join(f"{c:>20}" for c in cols))
    for (share, strategy), rs in sorted(groups.items()):
        ok = [r for r in rs if not r["crashed"]]
        means = " ".join(f"{statistics.mean(r[c] for r in ok):>20.2f}" if ok and ok[0][c] != "" else f"{'-':>20}" for c in cols)
        print(f"{share:>8} {strategy:>9} {len(rs) - len(ok):>4}/{len(rs):<3} {means}")
    print(f"\nWrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
