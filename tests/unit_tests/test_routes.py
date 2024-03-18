from unittest.mock import patch
from pear_schedule.api.utils import activitiesExcludedPatientTest, preferredActivitiesPatientTest
from tests.utils import fake_fn

class TestPatientTestUtils:
    ## ========================= FOR TESTING CASES =========================
    # Test 1
    # patient_wellness_plan['should_not_be_scheduled_activities']['duplicates']['excluded'] = ["Mahjong", "Physiotherapy"]
    
    # Test 2
    # patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended'] = ["Mahjong", "Cutting"]
    # patient_wellness_plan['should_be_scheduled_activities']['duplicates']['preferred'] = ["Mahjong","Cutting","Piano", "Dancing", "Cooking"]
    # patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Mahjong", "Piano"]
    
    # Test 3
    # patient_wellness_plan['should_not_be_scheduled_activities']['duplicates']['non_preferred'] = ["Mahjong"]
    # patient_wellness_plan['should_be_scheduled_activities']['recommended'] = ["Mahjong", "Cutting"]
    
    # Test 4
    # patient_wellness_plan['should_be_scheduled_activities']['duplicates']['recommended'] = ["Clip Coupons", "Cutting"]
    # patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Clip Coupons", "Piano"]
    
    # Test 5
    # patient_wellness_plan['should_not_be_scheduled_activities']['duplicates']['non_recommended'] = ["Clip Coupons"]
    
    # Test 6
    # patient_wellness_plan['should_be_scheduled_activities']['duplicates']['routines'] = ["Sewing", "Piano"]
    # patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Clip Coupons", "Piano", "Sewing"]
    
    # Test 7
    # patient_wellness_plan['medication_info']['medication_schedule'][2] = ['Give Medication@0945: Galantamine(2 tabs)*']
    # patient_wellness_plan['medication_info']['duplicates']['medication_schedule'][2] = ['Give Medication@0930: Galantamine(2 puffs)']
    # patient_wellness_plan['medication_info']['medication_schedule'][1] = ['Give Medication@0945: Galantamine(2 tabs)*']
    # patient_wellness_plan['medication_info']['duplicates']['medication_schedule'][1] = ['Give Medication@0930: Galantamine(2 puffs)']
    
    # =======================================================================
            
    # Helper function to create a mock patient wellness plan
    def create_mock_patient_wellness_plan(self):
        return {
            'patientID': 1,
            'DAYS': 5,
            'DAY_OF_WEEK_ORDER' : ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            'should_be_scheduled_activities': {
                'preferred': [],
                'recommended': [],
                'routines': [],
                'duplicates': {  # Duplicate lists for further processing
                    'preferred': [],
                    'recommended': [],
                    'routines': [],
                }
            },
            'should_not_be_scheduled_activities':{
                'non_preferred': [],
                'non_recommended': [],
                'excluded': [],
                'duplicates': {  # Initializing empty lists for further processing
                    'non_preferred': [],
                    'non_recommended': [],
                    'excluded': [],
                }
            },
            'medication_info': {
                'medication_schedule' : {},
                'duplicates': { # Initializing empty dictionary for further processing
                    "medication_schedule" : {}
                }
            }
        }
    
    # Helper function to create a mock json response
    def create_mock_json_response(self):
        return {
            1 : {}
        }
    
    '''
    Test 1: Activities excluded are not scheduled
    '''
    def test_activities_excluded_patient_test_pass(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Mahjong"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['duplicates']['excluded'] = []
        fake_json_response = self.create_mock_json_response()
        
        activitiesExcludedPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 1"]["Result"] == "Passed"
        assert fake_json_response[1]["Test 1"]["Reason"] == []
        
    def test_activities_excluded_patient_test_fail(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Mahjong", "Cutting"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['duplicates']['excluded'] = ["Mahjong"]
        fake_json_response = self.create_mock_json_response()
        
        activitiesExcludedPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 1"]["Result"] == "Failed"
        assert fake_json_response[1]["Test 1"]["Reason"] == [f"The following activities excluded are scheduled: {fake_patient_wellness_plan['should_not_be_scheduled_activities']['duplicates']['excluded']}"]
        
        
    '''
    Test 2: Patient preferred activities are scheduled
    '''
    def test_preferred_activities_patient_test_pass(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_be_scheduled_activities']['duplicates']['preferred'] = ["Dancing", "Cooking"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['duplicates']['preferred'] = []
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Mahjong", "Piano"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended'] = ["Mahjong", "Cutting"]
        fake_json_response = self.create_mock_json_response()
        
        preferredActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 2"]["Result"] == "Passed"
        assert fake_json_response[1]["Test 2"]["Reason"] == []
        
    def test_preferred_activities_patient_test_fail_without_exception(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_be_scheduled_activities']['duplicates']['preferred'] = ["Dancing", "Cooking"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['duplicates']['preferred'] = ["Cooking"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Mahjong", "Piano"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended'] = ["Mahjong", "Cutting"]
        fake_json_response = self.create_mock_json_response()
        
        preferredActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 2"]["Result"] == "Failed"
        assert fake_json_response[1]["Test 2"]["Reason"] == [f"The following preferred activities are not scheduled: ['Cooking']"]
        
    def test_preferred_activities_patient_test_fail_with_one_exception(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_be_scheduled_activities']['duplicates']['preferred'] = ["Mahjong", "Dancing", "Cooking"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['duplicates']['preferred'] = ["Mahjong", "Cooking"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Mahjong", "Piano"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended'] = ["Cutting"]
        fake_json_response = self.create_mock_json_response()
        
        preferredActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 2"]["Result"] == "Failed"
        assert fake_json_response[1]["Test 2"]["Reason"] == [f"(Exception) ['Mahjong'] are not scheduled because there are part of Activities Excluded", f"The following preferred activities are not scheduled: ['Cooking']"]

    def test_preferred_activities_patient_test_fail_with_two_exception(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_be_scheduled_activities']['duplicates']['preferred'] = ["Cutting","Mahjong", "Dancing", "Cooking"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['duplicates']['preferred'] = ["Cutting","Mahjong", "Cooking"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Mahjong", "Piano"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended'] = ["Cutting"]
        fake_json_response = self.create_mock_json_response()
        
        preferredActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 2"]["Result"] == "Failed"
        assert fake_json_response[1]["Test 2"]["Reason"] == [
            f"(Exception) ['Mahjong'] are not scheduled because there are part of Activities Excluded",
            f"(Exception) ['Cutting'] are not scheduled because there are part of Doctor Non-Recommended Activities",  
            f"The following preferred activities are not scheduled: ['Cooking']"
            ]
        
    def test_preferred_activities_patient_test_pass_with_one_exception(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_be_scheduled_activities']['duplicates']['preferred'] = ["Mahjong", "Dancing", "Cooking"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['duplicates']['preferred'] = ["Mahjong"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Mahjong", "Piano"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended'] = ["Cutting"]
        fake_json_response = self.create_mock_json_response()
        
        preferredActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 2"]["Result"] == "Passed"
        assert fake_json_response[1]["Test 2"]["Reason"] == [f"(Exception) ['Mahjong'] are not scheduled because there are part of Activities Excluded"]
        
    def test_preferred_activities_patient_test_pass_with_two_exception(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_be_scheduled_activities']['duplicates']['preferred'] = ["Cutting","Mahjong", "Dancing", "Cooking"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['duplicates']['preferred'] = ["Cutting","Mahjong"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Mahjong", "Piano"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended'] = ["Cutting"]
        fake_json_response = self.create_mock_json_response()
        
        preferredActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 2"]["Result"] == "Passed"
        assert fake_json_response[1]["Test 2"]["Reason"] == [
            f"(Exception) ['Mahjong'] are not scheduled because there are part of Activities Excluded",
            f"(Exception) ['Cutting'] are not scheduled because there are part of Doctor Non-Recommended Activities"
            ]