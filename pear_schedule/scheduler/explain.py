"""
Explains a schedule run: which stage placed each slot and why, rule violations,
and whether each Free and Easy was avoidable. Read-only.
"""

import copy
import datetime
import json
import math
import os
from collections import Counter, defaultdict
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

from pear_schedule.db_utils.utils import building_for, building_week, day_timeslot_labels, next_week_start, schedule_day_columns
from pear_schedule.scheduler import trace as schedule_trace
from pear_schedule.scheduler.gapFill import PoolActivity, is_excluded
from pear_schedule.scheduler.invariants import (
    FREE_AND_EASY, LOGIC, PatientRules, RuleInputs, analyse_free_and_easy, base_title, check_rules,
)
from pear_schedule.scheduler.what_if import format_what_if, what_if

STAGE_ORDER = [
    schedule_trace.STAGE_COMPULSORY, schedule_trace.STAGE_RECOMMENDED, schedule_trace.STAGE_GROUP,
    schedule_trace.STAGE_PREFERRED, schedule_trace.STAGE_ADHOC, schedule_trace.STAGE_MEDICATION,
]


def parse_slots(value) -> FrozenSet[Tuple[int, int]]:
    """'0-1,2-3' -> {(0, 1), (2, 3)}; None/'' -> empty (flexible activity)."""
    if value is None or not str(value).strip() or str(value).strip().lower() in ("none", "nan"):
        return frozenset()
    out = set()
    for part in str(value).split(","):
        d, s = part.strip().split("-")
        out.add((int(d), int(s)))
    return frozenset(out)


def current_week_start() -> datetime.datetime:
    # same as the stages
    now = building_for() or datetime.datetime.now()
    return now - datetime.timedelta(days=now.weekday())


def collect_rule_inputs(config: Mapping[str, Any], week_start: Optional[datetime.datetime] = None) -> RuleInputs:
    """Rule inputs from the same views the scheduler reads."""
    from pear_schedule.db_utils.views import (
        ActivitiesView, CompulsoryActivitiesOnlyView, DisrecommendedActivitiesView,
        GroupActivitiesOnlyView, GroupActivitiesRecommendationView, RecommendedActivitiesView,
    )
    from pear_schedule.scheduler.individualScheduling import IndividualActivityScheduler

    week_start = week_start or current_week_start()

    pool = [
        PoolActivity(int(r["ActivityID"]), r["ActivityTitle"], int(r["MinDuration"]), parse_slots(r["FixedTimeSlots"]))
        for _, r in ActivitiesView.get_data().iterrows()
    ]
    compulsory = [
        PoolActivity(-(i + 1), r["ActivityTitle"], int(r["MinDuration"]), parse_slots(r["FixedTimeSlots"]))
        for i, (_, r) in enumerate(CompulsoryActivitiesOnlyView.get_data().iterrows())
    ]

    titles: Dict[str, int] = {a.title: a.activity_id for a in pool}
    group_activity_ids = {}  # CentreActivityID -> ActivityID
    for _, r in GroupActivitiesOnlyView.get_data().iterrows():
        titles.setdefault(r["ActivityTitle"], int(r["ActivityID"]))
        group_activity_ids[int(r["CentreActivityID"])] = int(r["ActivityID"])

    recommended = defaultdict(set)
    for _, r in RecommendedActivitiesView.get_data().iterrows():
        recommended[r["PatientID"]].add(int(r["ActivityID"]))
        titles.setdefault(r["ActivityTitle"], int(r["ActivityID"]))
    not_recommended = defaultdict(set)
    for _, r in DisrecommendedActivitiesView.get_data().iterrows():
        not_recommended[r["PatientID"]].add(int(r["ActivityID"]))
    # group recommendations count too, a recommendation beats a dislike
    for _, r in GroupActivitiesRecommendationView.get_data().iterrows():
        aid = group_activity_ids.get(int(r["CentreActivityID"]))
        if aid is None:
            continue
        if int(r["DoctorRecommendation"]) == 1:
            recommended[r["PatientID"]].add(aid)
        elif int(r["DoctorRecommendation"]) == -1:
            not_recommended[r["PatientID"]].add(aid)

    patients = {}
    for pid, p in IndividualActivityScheduler._get_patient_data().items():
        patients[pid] = PatientRules(
            likes=set(p["preferences"]),
            dislikes=set(p["dispreferences"]),
            recommended=recommended.get(pid, set()),
            not_recommended=not_recommended.get(pid, set()),
            exclusions=dict(p["exclusions"]),
        )
    for pid in set(recommended) - set(patients):
        patients[pid] = PatientRules(recommended=recommended[pid], not_recommended=not_recommended.get(pid, set()))

    return RuleInputs(
        slots_per_day=[config["SLOTS_PER_DAY"].get(d) for d in config["OPEN_DAYS"]],
        min_activity_duration=config["MIN_ACTIVITY_DURATION"],
        week_start=week_start,
        pool=pool,
        patients=patients,
        compulsory=compulsory,
        activity_ids_by_title=titles,
    )


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):  # numpy scalars
        value = value.item()
    # NaN isn't valid JSON, the browser can't parse it
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def gap_filled_slots(trace: schedule_trace.ScheduleTrace) -> set:
    """(pid, day, slot) whose activity was decided by gap filling."""
    out = set()
    for key, writes in trace.provenance.items():
        decided = [w for w in writes if w.stage != schedule_trace.STAGE_MEDICATION]
        if decided and decided[-1].stage == schedule_trace.STAGE_PREFERRED and base_title(decided[-1].activity) != "Free and Easy":
            out.add(key)
    return out


def build_explanation(
    schedules: Mapping[Any, List[List[str]]],
    trace: schedule_trace.ScheduleTrace,
    inputs: RuleInputs,
    config: Mapping[str, Any],
    patient_ids: Optional[Iterable[Any]] = None,
    with_what_if: bool = False,
) -> Dict[str, Any]:
    """Schedules + trace + rule inputs -> JSON-able explanation."""
    # adhoc overrides are deliberate, skip them in the rule checks
    inputs.exempt = {
        (pid, d, s) for (pid, d, s), writes in trace.provenance.items()
        if any(w.stage == schedule_trace.STAGE_ADHOC for w in writes)
    }
    inputs.gap_filled = gap_filled_slots(trace)
    violations = check_rules(schedules, inputs)
    fe = analyse_free_and_easy(schedules, inputs)

    wanted = set(patient_ids) if patient_ids else None
    open_days = list(config["OPEN_DAYS"])
    labels = [
        day_timeslot_labels(day, config["SLOTS_PER_DAY"].get(day), config["WORKING_HOURS"], config["MIN_ACTIVITY_DURATION"])
        for day in open_days
    ]

    events_by_slot = defaultdict(list)
    notes_by_patient = defaultdict(list)
    centre_events = []
    for e in trace.events:
        if e.patient_id is None:
            centre_events.append(e.to_dict())
        elif e.day is not None and e.slot is not None:
            events_by_slot[(e.patient_id, e.day, e.slot)].append(e.to_dict())
        else:
            notes_by_patient[e.patient_id].append(e.to_dict())

    violations_by_patient = defaultdict(list)
    for v in violations:
        violations_by_patient[v.patient_id].append(vars(v))

    patients_out = {}
    for pid, days in schedules.items():
        if wanted is not None and pid not in wanted:
            continue
        prov = trace.provenance_for(pid)
        days_out = []
        for d, day in enumerate(days):
            fe_info = fe.by_patient_day.get((pid, d), {})
            slots_out = []
            for s, value in enumerate(day):
                writes = prov.get((d, s), [])
                slots_out.append({
                    "value": value,
                    "activity": base_title(value),
                    "stage": writes[-1].stage if writes else None,
                    # ignoring the medication suffix
                    "placed_by": next((w.stage for w in reversed(writes) if w.stage != schedule_trace.STAGE_MEDICATION), None),
                    "history": [vars(w) for w in writes],
                    "events": events_by_slot.get((pid, d, s), []),
                    "free_and_easy": fe_info.get("slot_reasons", {}).get(s),
                })
            days_out.append({"day": open_days[d] if d < len(open_days) else str(d), "labels": labels[d] if d < len(labels) else [], "slots": slots_out})

        pfe = [info for (p, _), info in fe.by_patient_day.items() if p == pid]
        patients_out[pid] = {
            "days": days_out,
            "notes": notes_by_patient.get(pid, []),
            "violations": violations_by_patient.get(pid, []),
            "free_and_easy": {
                "total": sum(len(i["slots"]) for i in pfe),
                "avoidable_logic": sum(i["avoidable"] for i in pfe),
                "avoidable_rearranging_gap_fill": sum(i["avoidable_rearranged"] for i in pfe),
                "unavoidable_by_reason": dict(sum((i["reasons"] for i in pfe), Counter())),
            },
        }

    total_slots = sum(len(day) for days in schedules.values() for day in days)
    out = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "week_start": inputs.week_start.date().isoformat(),
        "open_days": open_days,
        "slot_minutes": config["MIN_ACTIVITY_DURATION"],
        "stages": STAGE_ORDER,
        "summary": {
            "patients": len(schedules),
            "slots": total_slots,
            "free_and_easy": fe.as_dict(),
            "violations_by_rule": dict(Counter(v.rule for v in violations)),
            "trace": trace.summary()["by_outcome"],
        },
        "centre_events": centre_events,
        "patients": patients_out,
    }
    if with_what_if:
        out["what_if"] = what_if(schedules, inputs, config["MIN_ACTIVITY_DURATION"])
    return _jsonable(out)


def patient_names(config: Mapping[str, Any]) -> Dict[Any, str]:
    """PatientID -> preferred name, else name. Read-only."""
    from sqlalchemy import select
    from pear_schedule.db import DB

    patient = DB.schema.tables[config["DB_TABLES"].PATIENT_TABLE]
    with DB.get_engine().connect() as conn:
        rows = conn.execute(select(patient.c["PatientID"], patient.c["PreferredName"], patient.c["Name"])).all()
    return {r[0]: (r[1] or r[2] or "").strip() for r in rows}


def run_explanation(config: Mapping[str, Any], patient_ids: Optional[Iterable[Any]] = None,
                    with_names: bool = False, with_what_if: bool = False) -> Dict[str, Any]:
    """Builds this week's schedules under a trace, without writing, and explains them."""
    from pear_schedule.scheduler.utils import build_schedules

    schedules: Dict[Any, List[List[str]]] = {}
    with schedule_trace.tracing() as trace:
        build_schedules(config, schedules)
    explanation = build_explanation(schedules, trace, collect_rule_inputs(config), config, patient_ids, with_what_if)
    explanation["source"] = "built"
    if with_names:
        add_names(explanation, patient_names(config))
    return explanation


def preview_next_week(config: Mapping[str, Any], patient_ids: Optional[Iterable[Any]] = None,
                      with_names: bool = False, with_what_if: bool = False,
                      now: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    """Builds next week from today's data, the way Monday's generate would. Never saved."""
    with building_week(next_week_start(now)):
        explanation = run_explanation(config, patient_ids, with_names, with_what_if)
    explanation["source"] = "preview"
    return explanation


def schedule_rows(explanation: Mapping[str, Any], config: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The explained week as getSchedule rows, so the calendar can show it."""
    from pear_schedule.db_utils.writer import WEEKDAYS

    start = datetime.datetime.fromisoformat(explanation["week_start"])
    end = start + datetime.timedelta(days=6, hours=23, minutes=59, seconds=59)
    rows = []
    for pid, p in explanation["patients"].items():
        columns = schedule_day_columns([[s["value"] for s in day["slots"]] for day in p["days"]], config)
        rows.append({
            "PatientID": int(pid),
            "Name": p.get("name"),
            **{day: columns.get(day, "") for day in WEEKDAYS},
            "StartDate": start.isoformat(),
            "EndDate": end.isoformat(),
        })
    return rows


def _now_against(aid: Optional[int], rules: PatientRules, day: int, week_start: datetime.datetime) -> Optional[str]:
    """The rule a saved activity breaks with today's data, checked like R1-R3, or None."""
    if aid is None:
        return None
    if is_excluded(aid, rules.exclusions, day, week_start):
        return "now_excluded"
    if aid in rules.not_recommended:
        return "now_not_recommended"
    if aid in rules.dislikes and aid not in rules.recommended:
        return "now_disliked"
    return None


def saved_week_trace(saved: Mapping[Any, Optional[List[List[str]]]], data) -> schedule_trace.ScheduleTrace:
    """Why each saved slot holds what it does, worked out from current data, as a trace."""
    from pear_schedule.scheduler.repair import _Repair, _runs

    r = _Repair(saved, data, set())
    t = schedule_trace.ScheduleTrace()
    for pid, days in saved.items():
        if days is None:
            continue
        rules = r.rules(pid)
        for d, day in enumerate(r.grid[pid]):
            for s, title in enumerate(day):
                if title in ("", FREE_AND_EASY):
                    t.provenance[(pid, d, s)] = [schedule_trace.SlotWrite(schedule_trace.STAGE_PREFERRED, FREE_AND_EASY, "")]
            for s, e, title in _runs(day):
                kind = r.kind(pid, d, s)
                aid = data.inputs.activity_id(title)
                outcome = schedule_trace.PLACED
                if kind == "adhoc":
                    stage, outcome, reason = schedule_trace.STAGE_ADHOC, schedule_trace.REPLACED, "adhoc_request"
                elif kind == "compulsory":
                    stage, reason = schedule_trace.STAGE_COMPULSORY, "fixed_slot"
                elif kind == "routine":
                    stage, reason = schedule_trace.STAGE_RECOMMENDED, "routine_slot"
                elif kind == "recommended":
                    stage = schedule_trace.STAGE_RECOMMENDED
                    reason = "recommended_over_dislike" if aid in rules.dislikes else "doctor_recommended"
                elif kind == "group":
                    stage = schedule_trace.STAGE_GROUP
                    rec = pid in data.group_recommended.get(title, set())
                    reason = ("recommended_over_dislike" if rec and aid in rules.dislikes else "recommended" if rec
                              else "liked" if pid in data.group_liked.get(title, set()) else "group_timeslot")
                else:
                    stage, reason = schedule_trace.STAGE_PREFERRED, "preferred" if aid in rules.likes else "neutral"
                # data changed since it was saved, say so instead of calling it allowed
                now = None if kind in ("adhoc", "compulsory") else _now_against(aid, rules, d, data.inputs.week_start)
                if now == "now_disliked" and reason == "recommended_over_dislike":
                    now = None
                for k in range(s, e):
                    t.provenance[(pid, d, k)] = [schedule_trace.SlotWrite(stage, title, "")]
                if now and reason == "neutral":
                    reason, now = now, None
                t.add(schedule_trace.TraceEvent(stage, pid, outcome, reason, activity=title, day=d, slot=s))
                if now:
                    t.add(schedule_trace.TraceEvent(stage, pid, outcome, now, activity=title, day=d, slot=s))
    return t


def explain_saved_week(config: Mapping[str, Any], patient_ids: Optional[Iterable[Any]] = None,
                       with_names: bool = False, now: Optional[datetime.datetime] = None,
                       with_what_if: bool = False) -> Optional[Dict[str, Any]]:
    """
    Explains this week's saved schedule without building it again. Adds what repair
    regenerates changed this week, and what the next one would change. None if nothing is saved yet.
    """
    from pear_schedule.scheduler.repair import changes_this_week, load_repair_data, load_saved, locked_slots, repair_week

    now = now or datetime.datetime.now()
    week_start = now - datetime.timedelta(days=now.weekday())
    data = load_repair_data(config, week_start)
    saved = load_saved(config, data.patient_ids, now)
    have = {pid: days for pid, days in saved.items() if days is not None}
    if not have:
        return None

    # data that changed since it was saved
    locked = locked_slots(config, week_start, now)
    with schedule_trace.tracing() as dry:
        after = repair_week(copy.deepcopy(saved), data, locked)
    pending = {}
    for pid, days in after.items():
        before = saved.get(pid)
        if before is None or days != [[base_title(v) or FREE_AND_EASY for v in day] for day in before]:
            pending[pid] = [e.to_dict() for e in dry.events if e.patient_id == pid and e.stage == schedule_trace.STAGE_REPAIR]

    t = saved_week_trace(saved, data)
    for e in changes_this_week(week_start.date()):
        t.add(e)
    # what already passed can't change, so it's not flagged
    data.inputs.locked = {(pid, d, s) for pid in have for d, s in locked}
    explanation = build_explanation(have, t, data.inputs, config, patient_ids, with_what_if)
    explanation["source"] = "saved"
    explanation["pending"] = _jsonable(pending)
    if with_names:
        add_names(explanation, patient_names(config))
    return explanation


def add_names(explanation: Dict[str, Any], names: Mapping[Any, str]) -> None:
    # off by default so the output can be shared without patient names
    for pid, p in explanation["patients"].items():
        p["name"] = names.get(int(pid)) or names.get(pid) or None


def format_text(explanation: Mapping[str, Any], patient_ids: Optional[Iterable[Any]] = None) -> str:
    """Text summary for the terminal."""
    lines = []
    s = explanation["summary"]
    fe = s["free_and_easy"]
    preview = " (preview from today's data, not saved)" if explanation.get("source") == "preview" else ""
    lines.append(f"Week of {explanation['week_start']}{preview}: {s['patients']} patients, {s['slots']} slots")
    pct = (100 * fe["total"] / s["slots"]) if s["slots"] else 0
    lines.append(
        f"Free and Easy: {fe['total']} slots ({pct:.0f}%), avoidable (LOGIC) {fe['avoidable_logic']}, "
        f"{fe['avoidable_rearranging_gap_fill']} if gap filling re-arranged, "
        f"unavoidable (DATA) {fe['unavoidable_data']} {fe['unavoidable_by_reason']}"
    )
    lines.append(f"Rule violations: {s['violations_by_rule'] or 'none'}")
    for e in explanation["centre_events"]:
        lines.append(f"Centre: {e['outcome']} {e['reason']} {e['activity']!r} {e['details']}")
    if "what_if" in explanation:
        lines.append(format_what_if(explanation["what_if"]))

    wanted = {str(p) for p in patient_ids} if patient_ids else None
    for pid, p in explanation["patients"].items():
        if wanted is not None and pid not in wanted:
            continue
        pfe = p["free_and_easy"]
        lines.append("")
        lines.append(f"Patient {pid}: Free and Easy {pfe['total']} (LOGIC {pfe['avoidable_logic']}, DATA {pfe['unavoidable_by_reason']})")
        for v in p["violations"]:
            lines.append(f"  ! {v['rule']} {v['message']} (day {v['day']}, slot {v['slot']}, {v['activity']})")
        for n in p["notes"]:
            lines.append(f"  - {n['stage']}: {n['outcome']} {n['reason']} {n['activity']!r}")
        for day in p["days"]:
            lines.append(f"  {day['day']}")
            for i, slot in enumerate(day["slots"]):
                label = day["labels"][i] if i < len(day["labels"]) else str(i)
                why = ", ".join(f"{e['outcome']} {e['reason']}" for e in slot["events"]) or ""
                if slot["free_and_easy"]:
                    why = f"{'LOGIC: a valid activity fit here' if slot['free_and_easy'] == LOGIC else 'DATA: ' + slot['free_and_easy']}"
                lines.append(f"    {label}  {slot['activity'][:28]:<28}  {slot['placed_by'] or '-':<20} {why}")
    return "\n".join(lines)


def dump_json(explanation: Mapping[str, Any], path: str) -> None:
    with open(path, "w") as f:
        json.dump(explanation, f, indent=2)


VIEWER = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "schedule_explainer.html")


def viewer_page(script: str, viewer: str = VIEWER) -> str:
    """The viewer with a script put in before its own."""
    with open(viewer, encoding="utf-8") as f:
        page = f.read()
    marker = "<!-- EXPLAIN_DATA -->"
    if marker not in page:
        raise ValueError(f"{viewer} has no {marker} placeholder")
    return page.replace(marker, script, 1)


def dump_html(explanation: Mapping[str, Any], path: str, viewer: str = VIEWER) -> None:
    """One page with the data inside, double-click to open."""
    # "</" would end the script tag early if a title contains it
    data = json.dumps(explanation).replace("</", "<\\/")
    page = viewer_page(f"<script>window.EXPLAIN_DATA = {data};</script>", viewer)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
