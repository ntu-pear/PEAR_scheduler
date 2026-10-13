"""
Exact gap filling for one patient-day.

Fills a day's empty slots with individual activities, no repeats, fixed ones only
at their fixed slots. Maximises (slots filled, liked slots, variety) with a branch
and bound, seeded with the greedy result so it's never worse than greedy.
"""

import datetime
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


def _order(candidates: Iterable[Candidate]) -> List[Candidate]:
    # good ones first so pruning kicks in early, ActivityID keeps it deterministic
    return sorted(candidates, key=lambda c: (-c.liked, -c.bonus, -c.length, c.activity_id))


def solve_day(
    free: Sequence[bool],
    candidates: Iterable[Candidate],
    seed: Optional[Assignment] = None,
    node_budget: int = DEFAULT_NODE_BUDGET,
) -> SolveResult:
    """free[i] is True when slot i is empty and may be filled."""
    n = len(free)
    cands = _order(candidates)
    max_bonus = max((c.bonus for c in cands), default=0.0)

    # suffix count of free slots, for the bound
    remaining = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        remaining[i] = remaining[i + 1] + (1 if free[i] else 0)

    best: Assignment = {}
    best_score = score(best)
    seed_score = None
    if seed and is_valid(seed, free):
        best = dict(seed)
        best_score = seed_score = score(best)

    current: Assignment = {}
    used: Set[int] = set()
    nodes = 0
    exhausted = False

    def dfs(i: int, filled: int, liked: int, bonus: float) -> None:
        nonlocal best, best_score, nodes, exhausted
        if exhausted:
            return
        nodes += 1
        if nodes > node_budget:
            exhausted = True
            return

        while i < n and not free[i]:
            i += 1

        cur = (filled, liked, round(bonus, 9))
        if cur > best_score:
            best, best_score = dict(current), cur

        if i >= n:
            return

        rem = remaining[i]
        bound = (filled + rem, liked + rem, round(bonus + rem * max_bonus, 9))
        if bound <= best_score:
            return

        for c in cands:
            if c.activity_id in used or not c.can_start_at(i) or i + c.length > n:
                continue
            if any(not free[s] for s in range(i, i + c.length)):
                continue
            current[i] = c
            used.add(c.activity_id)
            dfs(i + c.length, filled + c.length, liked + (c.length if c.liked else 0), bonus + c.bonus)
            del current[i]
            used.discard(c.activity_id)
            if exhausted:
                return

        # leave slot i as Free and Easy
        dfs(i + 1, filled, liked, bonus)

    dfs(0, 0, 0, 0.0)
    return SolveResult(best, best_score, nodes, exhausted, seed_score)


def slots_for(min_duration: int, min_activity_duration: int) -> int:
    return max(1, -(-int(min_duration) // int(min_activity_duration)))


def is_excluded(activity_id: int, exclusions: Mapping[int, Optional[datetime.datetime]], day: int,
                week_start: datetime.datetime) -> bool:
    # same as checkActivityExcluded
    if activity_id not in exclusions:
        return False
    end = exclusions[activity_id]
    return end is None or end >= week_start + datetime.timedelta(days=day)


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
