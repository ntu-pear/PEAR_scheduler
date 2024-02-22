import datetime
from unittest.mock import patch
import pandas as pd
from pear_schedule.scheduler.individualScheduling import IndividualActivityScheduler, _get_max_enddate, calculate_activity_availabillity
from tests.utils import fake_fn

class TestUtils:
    def test_get_patient_data(self):
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

    def test_get_max_enddate(self):
        lo_dt = datetime.datetime.now()
        hi_dt = lo_dt + datetime.timedelta(days=1)
        assert _get_max_enddate(None, None) == None
        assert _get_max_enddate(None, lo_dt) == None
        assert _get_max_enddate(lo_dt, None) == None
        assert _get_max_enddate(lo_dt, hi_dt) == hi_dt

    def test_calculate_activity_availabillity(self):
        assert calculate_activity_availabillity(0, 0, "") == 1000
        assert calculate_activity_availabillity(6, 10, "") == 1000
        assert calculate_activity_availabillity(0, 0, "0-2,1-1,1-5,4-3") == 4
        assert calculate_activity_availabillity(4, 10, "0-2,1-1,1-5,4-3") == 0
        assert calculate_activity_availabillity(1, 1, "0-2,1-1,1-5,4-3") == 3
        assert calculate_activity_availabillity(1, 2, "0-2,1-1,1-5,4-3") == 2

class TestRecommendedScheduling:
    pass

class TestPreferredScheduling:
    pass