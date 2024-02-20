import datetime
from unittest.mock import patch
import pandas as pd
from pear_schedule.scheduler.individualScheduling import IndividualActivityScheduler
from tests.utils import validateDF


def fake_fn(result):
    def mock_fn(*args, **kwargs):
        return result
    return mock_fn


def test_get_patient_data():
    exclusion_end = datetime.datetime.now()

    fake_patients_view = fake_fn(pd.DataFrame({
        "PatientID": [1,1,2,4],
        "PreferredActivityID": [1,2,1,4]
    }))
    fake_exclusion_view = fake_fn(pd.DataFrame({
        "ActivityExclusionID": [1,2,3],
        "ActivityID": [4,1,2],
        "PatientID": [3,2,1],
        "ExclusionRemarks": ["",None,""],
        "EndDateTime": [exclusion_end]*3,
        "ActivityTitle": ["test1", "test2", "test3"],
    }))
    with (
        patch("pear_schedule.scheduler.individualScheduling.PatientsView.get_data", fake_patients_view),
        patch("pear_schedule.scheduler.individualScheduling.ActivitiesExcludedView.get_data", fake_exclusion_view),
    ):
        result = IndividualActivityScheduler._get_patient_data()

    expected = {
        1: {"preferences": {1: True, 2: True}, "exclusions": {2: exclusion_end}},
        2: {"preferences": {1: True}, "exclusions": {1: exclusion_end}},
        3: {"preferences": {}, "exclusions": {4: exclusion_end}},
        4: {"preferences": {4: True}, "exclusions": {}},
    }

    assert result.keys() == expected.keys(), f"expected patients {expected.keys()} \ngot {result.keys()}"

    mismatched_patients = {
        "patientID": [],
        "expected_preferences":[],
        "result_preferences":[],
        "expected_exclusions":[],
        "result_exclusions":[]
    }

    for p in expected:
        valid = True
        if result[p]["preferences"] != expected[p]["preferences"]:
            valid = False
        elif result[p]["exclusions"] != expected[p]["exclusions"]:
            valid = False

        if not valid:
            mismatched_patients["patientID"].append(p)
            mismatched_patients["expected_preferences"].append(expected[p]["preferences"])
            mismatched_patients["result_preferences"].append(result[p]["preferences"])
            mismatched_patients["expected_exclusions"].append(expected[p]["exclusions"])
            mismatched_patients["result_exclusions"].append(result[p]["exclusions"])

    assert not mismatched_patients["patientID"], f"{pd.DataFrame(mismatched_patients)}"

class TestRecommendedScheduling:
    pass

class TestPreferredScheduling:
    pass