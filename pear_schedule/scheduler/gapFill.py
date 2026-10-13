"""
Exact gap filling for one patient-day.

Fills a day's empty slots with individual activities, no repeats, fixed ones only
at their fixed slots. Maximises (slots filled, liked slots, variety) exactly with a
DP over slot positions, and never returns worse than the seed (the greedy result).
"""

import datetime

import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

DEFAULT_NODE_BUDGET = 200_000


@dataclass(frozen=True)
class Candidate:
    activity_id: int
    title: str
    length: int                              # slots occupied
    starts: Optional[FrozenSet[int]] = None  # allowed start slots today, None = anywhere
    liked: bool = False
    bonus: float = 0.0                       # variety score, higher = prefer

    def can_start_at(self, slot: int) -> bool:
        return self.starts is None or slot in self.starts


Assignment = Dict[int, Candidate]  # start slot -> candidate


@dataclass
class SolveResult:
    assignment: Assignment
    score: Tuple[int, int, float]
    nodes: int
    exhausted_budget: bool
    seed_score: Optional[Tuple[int, int, float]] = None


def score(assignment: Assignment) -> Tuple[int, int, float]:
    filled = sum(c.length for c in assignment.values())
    liked = sum(c.length for c in assignment.values() if c.liked)
    bonus = round(sum(c.bonus for c in assignment.values()), 9)
    return (filled, liked, bonus)


def is_valid(assignment: Assignment, free: Sequence[bool]) -> bool:
    used_ids = set()
    taken = set()
    for start, c in assignment.items():
        if c.activity_id in used_ids or not c.can_start_at(start):
            return False
        span = range(start, start + c.length)
        if start < 0 or start + c.length > len(free) or any(not free[s] or s in taken for s in span):
            return False
        used_ids.add(c.activity_id)
        taken.update(span)
    return True


def _add(a: Tuple[int, int, float], b: Tuple[int, int, float]) -> Tuple[int, int, float]:
    return (a[0] + b[0], a[1] + b[1], round(a[2] + b[2], 9))


def solve_day(
    free: Sequence[bool],
    candidates: Iterable[Candidate],
    seed: Optional[Assignment] = None,
    node_budget: int = DEFAULT_NODE_BUDGET,
) -> SolveResult:
    """free[i] is True when slot i is empty and may be filled."""
    n = len(free)
    cands = list(candidates)

    # flexible ones with the same length + liked flag are interchangeable, so just track
    # how many of each group got used, highest bonus first
    groups: Dict[Tuple[int, bool], List[Candidate]] = {}
    for c in cands:
        if c.starts is None:
            groups.setdefault((c.length, c.liked), []).append(c)
    group_keys = sorted(groups, key=lambda k: (-k[1], -k[0]))
    for k in group_keys:
        groups[k].sort(key=lambda c: (-c.bonus, c.activity_id))
    fixed = sorted((c for c in cands if c.starts is not None), key=lambda c: (-c.liked, -c.bonus, c.activity_id))

    def fits(i: int, length: int) -> bool:
        return i + length <= n and all(free[s] for s in range(i, i + length))

    memo: Dict[Tuple, Tuple[Tuple[int, int, float], Optional[Tuple[str, int]]]] = {}
    nodes = 0

    class Budget(Exception):
        pass

    def best(i: int, used: Tuple[int, ...], used_fixed: FrozenSet[int]):
        nonlocal nodes
        while i < n and not free[i]:
            i += 1
        if i >= n:
            return (0, 0, 0.0), None
        # a used fixed activity only matters while it still has a start ahead
        used_fixed = frozenset(f for f in used_fixed if fixed[f].starts and max(fixed[f].starts) >= i)
        key = (i, used, used_fixed)
        if key in memo:
            return memo[key]
        nodes += 1
        if nodes > node_budget:
            raise Budget

        top, choice = None, None
        for f_idx, c in enumerate(fixed):
            if f_idx in used_fixed or i not in c.starts or not fits(i, c.length):
                continue
            rest = best(i + c.length, used, used_fixed | {f_idx})[0]
            val = _add(rest, (c.length, c.length if c.liked else 0, c.bonus))
            if top is None or val > top:
                top, choice = val, ("fixed", f_idx)
        for g_idx, k in enumerate(group_keys):
            length, liked = k
            if used[g_idx] >= len(groups[k]) or not fits(i, length):
                continue
            c = groups[k][used[g_idx]]
            nxt = used[:g_idx] + (used[g_idx] + 1,) + used[g_idx + 1:]
            rest = best(i + length, nxt, used_fixed)[0]
            val = _add(rest, (length, length if liked else 0, c.bonus))
            if top is None or val > top:
                top, choice = val, ("group", g_idx)
        # Free and Easy only if strictly better, ties go to placing earlier
        skip = best(i + 1, used, used_fixed)[0]
        if top is None or skip > top:
            top, choice = skip, ("skip", -1)
        memo[key] = (top, choice)
        return memo[key]

    seed_score = score(seed) if seed and is_valid(seed, free) else None
    try:
        best_score, _ = best(0, tuple(0 for _ in group_keys), frozenset())
    except Budget:
        fallback = dict(seed) if seed_score is not None else {}
        return SolveResult(fallback, score(fallback), nodes, True, seed_score)

    # walk the choices back into an assignment
    assignment: Assignment = {}
    i, used, used_fixed = 0, tuple(0 for _ in group_keys), frozenset()
    while True:
        while i < n and not free[i]:
            i += 1
        if i >= n:
            break
        used_fixed = frozenset(f for f in used_fixed if fixed[f].starts and max(fixed[f].starts) >= i)
        _, (kind, idx) = memo[(i, used, used_fixed)]
        if kind == "skip":
            i += 1
        elif kind == "fixed":
            c = fixed[idx]
            assignment[i] = c
            used_fixed = used_fixed | {idx}
            i += c.length
        else:
            c = groups[group_keys[idx]][used[idx]]
            assignment[i] = c
            used = used[:idx] + (used[idx] + 1,) + used[idx + 1:]
            i += c.length

    if seed_score is not None and seed_score > score(assignment):
        assignment = dict(seed)
    return SolveResult(assignment, score(assignment), nodes, False, seed_score)


def slots_for(min_duration: int, min_activity_duration: int) -> int:
    return max(1, -(-int(min_duration) // int(min_activity_duration)))


def is_excluded(activity_id: int, exclusions: Mapping[int, Optional[datetime.datetime]], day: int,
                week_start: datetime.datetime) -> bool:
    # same as checkActivityExcluded
    if activity_id not in exclusions:
        return False
    end = exclusions[activity_id]
    # NaT is how pandas reads a NULL end date, same as None: no end
    return end is None or pd.isna(end) or end >= week_start + datetime.timedelta(days=day)


@dataclass
class PoolActivity:
    """Individual activity that gap filling can use."""
    activity_id: int
    title: str
    min_duration: int
    fixed_slots: FrozenSet[Tuple[int, int]] = field(default_factory=frozenset)  # (day, slot); empty = flexible


def build_candidates(
    pool: Iterable[PoolActivity],
    day: int,
    *,
    min_activity_duration: int,
    week_start: datetime.datetime,
    exclusions: Mapping[int, Optional[datetime.datetime]],
    liked: Set[int],
    blocked: Set[int],
    used_titles_today: Set[str],
    week_counts: Optional[Mapping[str, int]] = None,
) -> List[Candidate]:
    """Activities this patient can get in today's gaps. blocked = dislikes + not recommended."""
    week_counts = week_counts or {}
    out = []
    for a in pool:
        if a.activity_id in blocked or a.title in used_titles_today:
            continue
        if is_excluded(a.activity_id, exclusions, day, week_start):
            continue
        starts = None
        if a.fixed_slots:
            starts = frozenset(s for d, s in a.fixed_slots if d == day)
            if not starts:
                continue
        out.append(Candidate(
            activity_id=a.activity_id,
            title=a.title,
            length=slots_for(a.min_duration, min_activity_duration),
            starts=starts,
            liked=a.activity_id in liked,
            bonus=1.0 / (1 + week_counts.get(a.title, 0)),
        ))
    return out
