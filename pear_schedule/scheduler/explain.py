"""
Explains a schedule run: which stage placed each slot and why, rule violations,
and whether each Free and Easy was avoidable. Read-only.
"""

import datetime
import json
from collections import Counter, defaultdict
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

from pear_schedule.db_utils.utils import day_timeslot_labels
from pear_schedule.scheduler import trace as schedule_trace
from pear_schedule.scheduler.gapFill import PoolActivity
from pear_schedule.scheduler.invariants import (
    LOGIC, PatientRules, RuleInputs, analyse_free_and_easy, base_title, check_rules,
)

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
    now = datetime.datetime.now()
    return now - datetime.timedelta(days=now.weekday())


def collect_rule_inputs(config: Mapping[str, Any], week_start: Optional[datetime.datetime] = None) -> RuleInputs:
    """Rule inputs from the same views the scheduler reads."""
    from pear_schedule.db_utils.views import (
        ActivitiesView, CompulsoryActivitiesOnlyView, DisrecommendedActivitiesView,
        GroupActivitiesOnlyView, RecommendedActivitiesView,
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
    for _, r in GroupActivitiesOnlyView.get_data().iterrows():
        titles.setdefault(r["ActivityTitle"], int(r["ActivityID"]))

    recommended = defaultdict(set)
    for _, r in RecommendedActivitiesView.get_data().iterrows():
        recommended[r["PatientID"]].add(int(r["ActivityID"]))
        titles.setdefault(r["ActivityTitle"], int(r["ActivityID"]))
    not_recommended = defaultdict(set)
    for _, r in DisrecommendedActivitiesView.get_data().iterrows():
        not_recommended[r["PatientID"]].add(int(r["ActivityID"]))

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
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "item"):  # numpy scalars
        return value.item()
    return str(value)


def build_explanation(
    schedules: Mapping[Any, List[List[str]]],
    trace: schedule_trace.ScheduleTrace,
    inputs: RuleInputs,
    config: Mapping[str, Any],
    patient_ids: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    """Schedules + trace + rule inputs -> JSON-able explanation."""
    # adhoc overrides are deliberate, skip them in the rule checks
    inputs.exempt = {
        (pid, d, s) for (pid, d, s), writes in trace.provenance.items()
        if any(w.stage == schedule_trace.STAGE_ADHOC for w in writes)
    }
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
                "unavoidable_by_reason": dict(sum((i["reasons"] for i in pfe), Counter())),
            },
        }

    total_slots = sum(len(day) for days in schedules.values() for day in days)
    return _jsonable({
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "week_start": inputs.week_start.date().isoformat(),
        "open_days": open_days,
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
    })


def run_explanation(config: Mapping[str, Any], patient_ids: Optional[Iterable[Any]] = None) -> Dict[str, Any]:
    """Builds this week's schedules under a trace, without writing, and explains them."""
    from pear_schedule.scheduler.utils import build_schedules

    schedules: Dict[Any, List[List[str]]] = {}
    with schedule_trace.tracing() as trace:
        build_schedules(config, schedules)
    return build_explanation(schedules, trace, collect_rule_inputs(config), config, patient_ids)


def format_text(explanation: Mapping[str, Any], patient_ids: Optional[Iterable[Any]] = None) -> str:
    """Text summary for the terminal."""
    lines = []
    s = explanation["summary"]
    fe = s["free_and_easy"]
    lines.append(f"Week of {explanation['week_start']}: {s['patients']} patients, {s['slots']} slots")
    pct = (100 * fe["total"] / s["slots"]) if s["slots"] else 0
    lines.append(
        f"Free and Easy: {fe['total']} slots ({pct:.0f}%), avoidable (LOGIC) {fe['avoidable_logic']}, "
        f"unavoidable (DATA) {fe['unavoidable_data']} {fe['unavoidable_by_reason']}"
    )
    lines.append(f"Rule violations: {s['violations_by_rule'] or 'none'}")
    for e in explanation["centre_events"]:
        lines.append(f"Centre: {e['outcome']} {e['reason']} {e['activity']!r} {e['details']}")

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
