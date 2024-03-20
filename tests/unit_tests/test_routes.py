from collections import Counter
from unittest.mock import patch

import pandas as pd
import pytest
from pear_schedule.api.utils import activitiesExcludedPatientTest, checkWeeklyScheduleCorrectness, generateStatistics, getPatientWellnessPlan, getTablesDF, medicationPatientTest, nonPreferredActivitiesPatientTest, nonRecommendedActivitiesPatientTest, preferredActivitiesPatientTest, prepareJsonResponse, prepareMedicationSchedule, recommendedActivitiesPatientTest, routinesPatientTest

class TestPatientTestUtils:
    # =======================================================================
    @pytest.fixture
    def mock_views(self):
        with patch('pear_schedule.db_utils.views.WeeklyScheduleView.get_data', return_value=pd.DataFrame({
                'PatientID' : [1],
                'StartDate' : [pd.to_datetime("2024-03-18")],
                "EndDate" : [pd.to_datetime("2024-03-24 23:59:59")],
                "Monday" : ["Breathing+Vital Check--Sewing | Give Medication@1030: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses--Sewing--Lunch--Cutting Pictures--Origami | Give Medication@1440: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses--Brisk Walking--Sort poker chips"],
                "Tuesday" : ["Breathing+Vital Check--Musical Instrument Lesson | Give Medication@1030: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses--Sewing--Lunch--Cutting Pictures--Clip Coupons | Give Medication@1440: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses--Story Time--Cup Stacking Game"],
                "Wednesday" : ["Breathing+Vital Check--Movie Screening | Give Medication@1030: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses--Sewing--Lunch--Cutting Pictures--Sort poker chips | Give Medication@1440: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses--Clip Coupons--Cup Stacking Game"],
                "Thursday" : ["Breathing+Vital Check--Sewing | Give Medication@1030: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses--Cutting Pictures--Lunch--Sort poker chips--String beads | Give Medication@1440: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses--Mahjong--Cup Stacking Game"],
                "Friday" : ["Breathing+Vital Check--Cutting Pictures | Give Medication@1030: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses--Sewing--Lunch--Picture Coloring--Origami | Give Medication@1440: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses--Cup Stacking Game--Clip Coupons"]
                })), \
            patch('pear_schedule.db_utils.views.CentreActivityPreferenceView.get_data', return_value=pd.DataFrame({
                'PatientID' : [1,1,1,1,1,1],
                'IsLike': [1,1,0,0,1,1],
                'ActivityTitle': ["Movie Screening", "Brisk Walking", "Sewing", "Origami", "Cutting Pictures", "Watch television"]
                })), \
            patch('pear_schedule.db_utils.views.CentreActivityRecommendationView.get_data', return_value=pd.DataFrame({
                'PatientID' : [1,1,1],
                'DoctorRecommendation': [1,1,0],
                'ActivityTitle': ["Brisk Walking", "Sewing", "Cutting Pictures"]
                })), \
            patch('pear_schedule.db_utils.views.ActivitiesExcludedView.get_data', return_value=pd.DataFrame({
                "PatientID" : [1],
                "ActivityTitle": ["Movie Screening"]
                })), \
            patch('pear_schedule.db_utils.views.RoutineView.get_data', return_value=pd.DataFrame({
                "PatientID" : [1], 
                "IncludeInSchedule" : [1],
                "ActivityTitle" : ["Cup Stacking Game"]
                })), \
            patch('pear_schedule.db_utils.views.MedicationTesterView.get_data', return_value=pd.DataFrame({
                'PatientID' : [1],
                'PrescriptionName' : ["Ibuprofen"],
                "Dosage" : ["2 tabs"],
                "AdministerTime" : ["1030,1440"],
                "Instruction" : ["Always leave at least 4 hours between doses"],
                "StartDateTime" : [pd.to_datetime("2024-01-01 00:00:00.0000000")],
                "EndDateTime" : [pd.to_datetime("2024-05-31 00:00:00.0000000")]
                })), \
            patch('pear_schedule.db_utils.views.ActivityAndCentreActivityView.get_data', return_value=pd.DataFrame({
                "ActivityTitle" : ['Lunch', 'Breathing+Vital Check','Board Games','Movie Screening', 'Brisk Walking', 'Mahjong', 'Musical Instrument Lesson', 'Story Time', 'Physiotherapy', 'String beads', 'Sewing', 'Cup Stacking Game', 'Sort poker chips', 'Origami', 'Picture Coloring', 'Clip Coupons', 'Cutting Pictures', 'Watch television'],
                "IsGroup" : [1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0]
            })):
            yield  
    
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
                'error_check': {  # Duplicate lists for further processing
                    'preferred': [],
                    'recommended': [],
                    'routines': [],
                }
            },
            'should_not_be_scheduled_activities':{
                'non_preferred': [],
                'non_recommended': [],
                'excluded': [],
                'error_check': {  # Initializing empty lists for further processing
                    'non_preferred': [],
                    'non_recommended': [],
                    'excluded': [],
                }
            },
            'medication_info': {
                'medication_schedule' : {},
                'error_check': { # Initializing empty dictionary for further processing
                    "medication_schedule" : {}
                }
            }
        }
    
    # Helper function to create a mock json response
    def create_mock_json_response(self):
        return {
            1 : {}
        }
    # =======================================================================
    
    '''
    Get all necessary tables 
    '''
    def test_get_tables_DF_return_all_needed_tables(self, mock_views):
        fake_tables_DF = getTablesDF()
        
        expected_keys = [
        "weeklyScheduleViewDF",
        "centreActivityPreferenceViewDF",
        "centreActivityRecommendationViewDF",
        "activitiesExcludedViewDF",
        "routineViewDF",
        "medicationViewDF",
        "activitiesAndCentreActivityViewDF"
        ]
        
        assert all(key in fake_tables_DF for key in expected_keys), "Not all expected keys are present in the tablesDF"
        for df in fake_tables_DF.values():
            assert not df.empty, "One of the DataFrames is empty"
    
    
    '''
    Generate the Patient Wellness Plan and Medication Schedule
    '''
    # test whether the patient wellness plan is parsed correctly based on the mock data 
    def test_get_patient_wellness_plan_based_on_mock_data(self, mock_views):
        fake_tables_DF = getTablesDF()
        config = {
            'DAYS': 5,
            'DAY_OF_WEEK_ORDER': ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        }
        fake_patient_wellness_plan = getPatientWellnessPlan(fake_tables_DF, patientID=1, config=config)
        
        assert fake_patient_wellness_plan['should_be_scheduled_activities']['preferred'] == ["Movie Screening", "Brisk Walking", "Cutting Pictures", "Watch television"]
        assert fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_preferred'] == ["Sewing", "Origami"]
        assert fake_patient_wellness_plan['should_be_scheduled_activities']['recommended'] == ["Brisk Walking", "Sewing"]
        assert fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended'] == ['Cutting Pictures']
        assert fake_patient_wellness_plan['should_be_scheduled_activities']['routines'] == ["Cup Stacking Game"]
        assert fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] == ["Movie Screening"]
        
        for activity_type, error_check_list in fake_patient_wellness_plan['should_be_scheduled_activities']['error_check'].items():
            assert error_check_list == fake_patient_wellness_plan["should_be_scheduled_activities"][activity_type], "For should_be_scheduled_activities, the error_check lists should be the same as the original list"
        
        for _, error_check_list in fake_patient_wellness_plan['should_not_be_scheduled_activities']['error_check'].items():
            assert len(error_check_list) == 0, "For should_not_be_scheduled_activities, the error_check lists should be empty"
            
        for _, day_medication_list in fake_patient_wellness_plan['medication_info']['medication_schedule'].items():
            assert day_medication_list == ['Give Medication@1030: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses', 'Give Medication@1440: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses']
        
        for _, day_medication_list in fake_patient_wellness_plan['medication_info']['error_check']['medication_schedule'].items():
            assert len(day_medication_list) == 0, "For medication_incorrect_schedule, the error_check lists should be empty"
    
    # test whether the medication schedule is parsed correctly based on the mock data 
    def test_prepare_medication_schedule_medication_starts_mid_week(self, mock_views):
        tablesDF = getTablesDF()
        weekly_schedule = tablesDF['weeklyScheduleViewDF'].loc[tablesDF['weeklyScheduleViewDF']['PatientID'] == 1]
        schedule_start_datetime = weekly_schedule['StartDate'].min()
        schedule_end_datetime = weekly_schedule['EndDate'].max()
        
        fake_medications = pd.DataFrame({
            'PatientID' : [1],
            'PrescriptionName' : ["Ibuprofen"],
            "Dosage" : ["2 tabs"],
            "AdministerTime" : ["1030,1440"],
            "Instruction" : ["Always leave at least 4 hours between doses"],
            "StartDateTime" : [pd.to_datetime("2024-03-20 00:00:00.0000000")],
            "EndDateTime" : [pd.to_datetime("2024-05-31 00:00:00.0000000")]
        })
        
        medication_schedule, medication_incorrect_schedule = prepareMedicationSchedule(fake_medications, schedule_start_datetime, schedule_end_datetime, DAYS=5)
        
        assert 0 not in medication_schedule
        assert 1 not in medication_schedule
        assert medication_schedule[2] == ['Give Medication@1030: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses', 'Give Medication@1440: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses']
        assert medication_schedule[3] == ['Give Medication@1030: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses', 'Give Medication@1440: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses']
        assert medication_schedule[4] == ['Give Medication@1030: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses', 'Give Medication@1440: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses']
    
    def test_prepare_medication_schedule_medication_stops_mid_week(self, mock_views):
        tablesDF = getTablesDF()
        weekly_schedule = tablesDF['weeklyScheduleViewDF'].loc[tablesDF['weeklyScheduleViewDF']['PatientID'] == 1]
        schedule_start_datetime = weekly_schedule['StartDate'].min()
        schedule_end_datetime = weekly_schedule['EndDate'].max()
        
        fake_medications = pd.DataFrame({
            'PatientID' : [1],
            'PrescriptionName' : ["Ibuprofen"],
            "Dosage" : ["2 tabs"],
            "AdministerTime" : ["1030,1440"],
            "Instruction" : ["Always leave at least 4 hours between doses"],
            "StartDateTime" : [pd.to_datetime("2024-01-01 00:00:00.0000000")],
            "EndDateTime" : [pd.to_datetime("2024-03-20 00:00:00.0000000")]
        })
        
        medication_schedule, medication_incorrect_schedule = prepareMedicationSchedule(fake_medications, schedule_start_datetime, schedule_end_datetime, DAYS=5)
        
        assert medication_schedule[0] == ['Give Medication@1030: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses', 'Give Medication@1440: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses']
        assert medication_schedule[1] == ['Give Medication@1030: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses', 'Give Medication@1440: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses']
        assert medication_schedule[2] == ['Give Medication@1030: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses', 'Give Medication@1440: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses']
        assert 3 not in medication_schedule
        assert 4 not in medication_schedule
    
    def test_prepare_medication_schedule_medication_two_medications_parsing(self, mock_views):
        tablesDF = getTablesDF()
        weekly_schedule = tablesDF['weeklyScheduleViewDF'].loc[tablesDF['weeklyScheduleViewDF']['PatientID'] == 1]
        schedule_start_datetime = weekly_schedule['StartDate'].min()
        schedule_end_datetime = weekly_schedule['EndDate'].max()
        
        fake_medications = pd.DataFrame({
            'PatientID' : [1, 1],
            'PrescriptionName' : ["Guaifenesin", "Diphenhydramine"],
            "Dosage" : ["10 ml","2 tabs"],
            "AdministerTime" : ['1315', '0930,1300'],
            "Instruction" : ["Nil","Always leave at least 4 hours between doses"],
            "StartDateTime" : [pd.to_datetime("2024-01-01 00:00:00.0000000"), pd.to_datetime("2024-01-01 00:00:00.0000000")],
            "EndDateTime" : [pd.to_datetime("2024-05-31 00:00:00.0000000"), pd.to_datetime("2024-05-31 00:00:00.0000000")]
        })
        
        medication_schedule, medication_incorrect_schedule = prepareMedicationSchedule(fake_medications, schedule_start_datetime, schedule_end_datetime, DAYS=5)
        
        for _, medication_day_list in medication_schedule.items():
            assert medication_day_list == ['Give Medication@0930: Diphenhydramine(2 tabs)**Always leave at least 4 hours between doses', 'Give Medication@1300: Diphenhydramine(2 tabs)**Always leave at least 4 hours between doses', 'Give Medication@1315: Guaifenesin(10 ml)']
    
    
    '''
    Checking Weekly Schedule Correctness (Assumes that all other functions implemented are correct)
    '''
    def test_prepare_json_response(self, mock_views):
        fake_tables_DF = getTablesDF()
        config = {
            'DAYS': 5,
            'DAY_OF_WEEK_ORDER': ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        }
        fake_patient_wellness_plan = getPatientWellnessPlan(fake_tables_DF, patientID=1, config=config)
        fake_json_response = self.create_mock_json_response()
        
        prepareJsonResponse(fake_json_response, fake_patient_wellness_plan)
        
        assert fake_json_response[1]['Schedule start date'] == '2024-03-18 00:00:00'
        assert fake_json_response[1]['Schedule end date'] == '2024-03-24 23:59:59'
        
        assert fake_json_response[1]['Preferred Activities'] == ['Movie Screening', "Brisk Walking", "Cutting Pictures", "Watch television"]
        assert fake_json_response[1]['Non-Preferred Activities'] == ["Sewing", "Origami"]
        
        assert fake_json_response[1]['Doctor Recommended Activities'] == ["Brisk Walking", "Sewing"]
        assert fake_json_response[1]['Doctor Non-Recommended Activities'] == ["Cutting Pictures"]
        
        assert fake_json_response[1]['Routines'] == ["Cup Stacking Game"]
        assert fake_json_response[1]['Activities Excluded'] == ["Movie Screening"]
        
        for day, schedule in fake_patient_wellness_plan['medication_info']['medication_schedule'].items():
            fake_json_response[1]["Medication Schedule"][fake_patient_wellness_plan['DAY_OF_WEEK_ORDER'][day]] == ['Give Medication@1030: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses', 'Give Medication@1440: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses']
    
    # NOTE: Based on the mock_data, the weekly schedule is incorrect  
    def test_check_weekly_schedule_correctness_based_on_mock_data(self, mock_views):
        tablesDF = getTablesDF() 
        patientInfo = tablesDF['weeklyScheduleViewDF'].iloc[0]
        json_response = self.create_mock_json_response()
        activity_count_dict = {activity: 0 for activity in tablesDF['activitiesAndCentreActivityViewDF']['ActivityTitle'].unique()} # dictionary to keep track of each activity count
        mondayIndex = tablesDF['weeklyScheduleViewDF'].columns.get_loc("Monday")
        config = {
            'DAYS': 5,
            'DAY_OF_WEEK_ORDER': ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        }
        
        patient_wellness_plan = getPatientWellnessPlan(tablesDF, 1, config)
        prepareJsonResponse(json_response, patient_wellness_plan)
        checkWeeklyScheduleCorrectness(mondayIndex, patientInfo, patient_wellness_plan, json_response, activity_count_dict)
        
        assert patient_wellness_plan['should_be_scheduled_activities']['error_check']['preferred'] == ["Watch television"]
        assert len(patient_wellness_plan['should_be_scheduled_activities']['error_check']['recommended']) == 0, "If there are no errors, the error_check_lists should be empty"
        assert len(patient_wellness_plan['should_be_scheduled_activities']['error_check']['routines']) == 0, "If there are no errors, the error_check_lists should be empty"
        
        assert patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['non_preferred'] == ["Sewing", "Origami"]
        assert patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['non_recommended'] == ["Cutting Pictures"]
        assert patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['excluded'] == ['Movie Screening']
        
        for _, medication_day_list in patient_wellness_plan['medication_info']['medication_schedule'].items():
            assert len(medication_day_list) == 0,  "If there are no errors, the medication_schedule should be empty and there should be no medications in medication_incorrect_schedule"
    
    def test_check_weekly_schedule_correctness_based_on_another_incorrect_schedule(self, mock_views):
        tablesDF = getTablesDF() 
        tablesDF['weeklyScheduleViewDF'] = pd.DataFrame({
            'PatientID' : [1],
            'StartDate' : [pd.to_datetime("2024-03-18")],
            "EndDate" : [pd.to_datetime("2024-03-24 23:59:59")],
            "Monday" : ["Breathing+Vital Check | Give Medication@0930: Diphenhydramine(2 tabs)**Always leave at least 4 hours between doses--Physiotherapy--Cup Stacking Game--Lunch--Origami | Give Medication@1315: Guaifenesin(10 ml)**To be eaten after meals, Give Medication@1300: Diphenhydramine(2 tabs)**Always leave at least 4 hours between doses--Watch television--Brisk Walking--Picture Coloring"],
            "Tuesday" : ["Breathing+Vital Check | Give Medication@0930: Diphenhydramine(2 tabs)**Always leave at least 4 hours between doses--Musical Instrument Lesson--Origami--Lunch--Cup Stacking Game | Give Medication@1315: Guaifenesin(10 ml)**To be eaten after meals, Give Medication@1300: Diphenhydramine(2 tabs)**Always leave at least 4 hours between doses--Clip Coupons--Story Time--Cutting Pictures"],
            "Wednesday" : ["Breathing+Vital Check | Give Medication@0930: Diphenhydramine(2 tabs)**Always leave at least 4 hours between doses--Movie Screening--Cup Stacking Game--Lunch--Origami | Give Medication@1315: Guaifenesin(10 ml)**To be eaten after meals, Give Medication@1300: Diphenhydramine(2 tabs)**Always leave at least 4 hours between doses--Watch television--Sort poker chips--Clip Coupons"],
            "Thursday" : ["Breathing+Vital Check | Give Medication@0930: Diphenhydramine(2 tabs)**Always leave at least 4 hours between doses--Cup Stacking Game--Origami--Lunch--Watch television | Give Medication@1315: Guaifenesin(10 ml)**To be eaten after meals, Give Medication@1300: Diphenhydramine(2 tabs)**Always leave at least 4 hours between doses--String beads--Mahjong--Picture Coloring"],
            "Friday" : ["Breathing+Vital Check | Give Medication@0930: Diphenhydramine(2 tabs)**Always leave at least 4 hours between doses--Cup Stacking Game--Origami--Lunch--Sort poker chips | Give Medication@1315: Guaifenesin(10 ml)**To be eaten after meals, Give Medication@1300: Diphenhydramine(2 tabs)**Always leave at least 4 hours between doses--Cutting Pictures--Clip Coupons--String beads"]
        })
        patientInfo = tablesDF['weeklyScheduleViewDF'].iloc[0]
        
        json_response = self.create_mock_json_response()
        activity_count_dict = {activity: 0 for activity in tablesDF['activitiesAndCentreActivityViewDF']['ActivityTitle'].unique()} # dictionary to keep track of each activity count
        mondayIndex = tablesDF['weeklyScheduleViewDF'].columns.get_loc("Monday")
        config = {
            'DAYS': 5,
            'DAY_OF_WEEK_ORDER': ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        }
        
        patient_wellness_plan = getPatientWellnessPlan(tablesDF, 1, config)
        prepareJsonResponse(json_response, patient_wellness_plan)
        checkWeeklyScheduleCorrectness(mondayIndex, patientInfo, patient_wellness_plan, json_response, activity_count_dict)
        
        assert len(patient_wellness_plan['should_be_scheduled_activities']['error_check']['preferred']) == 0
        assert patient_wellness_plan['should_be_scheduled_activities']['error_check']['recommended'] == ['Sewing']
        assert len(patient_wellness_plan['should_be_scheduled_activities']['error_check']['routines']) == 0
        
        assert patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['non_preferred'] == ['Origami']
        assert patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['non_recommended'] == ['Cutting Pictures']
        assert patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['excluded'] == ['Movie Screening']
        
        for day, medication_day_list in patient_wellness_plan['medication_info']['medication_schedule'].items():
            expected_list = [
                    "Give Medication@1030: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses",
                    "Give Medication@1440: Ibuprofen(2 tabs)**Always leave at least 4 hours between doses"
                ]
            assert Counter(medication_day_list) == Counter(expected_list)
        
        for day, medication_day_list in patient_wellness_plan['medication_info']['error_check']['medication_schedule'].items():
            expected_list = [
                    "Give Medication@0930: Diphenhydramine(2 tabs)**Always leave at least 4 hours between doses",
                    "Give Medication@1300: Diphenhydramine(2 tabs)**Always leave at least 4 hours between doses",
                    "Give Medication@1315: Guaifenesin(10 ml)**To be eaten after meals"
                ]
            assert Counter(medication_day_list) == Counter(expected_list)
    
    
    '''
    Test 1: Activities excluded are not scheduled
    '''
    def test_activities_excluded_patient_test_pass(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Mahjong"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['excluded'] = []
        fake_json_response = self.create_mock_json_response()
        
        activitiesExcludedPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 1"]["Result"] == "Passed"
        assert fake_json_response[1]["Test 1"]["Reason"] == []
    
    def test_activities_excluded_patient_test_fail(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Mahjong", "Cutting"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['excluded'] = ["Mahjong"]
        fake_json_response = self.create_mock_json_response()
        
        activitiesExcludedPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 1"]["Result"] == "Failed"
        assert fake_json_response[1]["Test 1"]["Reason"] == [f"The following activities excluded are scheduled: {fake_patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['excluded']}"]
    
    
    '''
    Test 2: Patient preferred activities are scheduled
    '''
    def test_preferred_activities_patient_test_pass(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_be_scheduled_activities']['preferred'] = ["Dancing", "Cooking"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['error_check']['preferred'] = []
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Mahjong", "Piano"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended'] = ["Mahjong", "Cutting"]
        fake_json_response = self.create_mock_json_response()
        
        preferredActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 2"]["Result"] == "Passed"
        assert fake_json_response[1]["Test 2"]["Reason"] == []
    
    def test_preferred_activities_patient_test_fail_without_exception(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_be_scheduled_activities']['preferred'] = ["Dancing", "Cooking"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['error_check']['preferred'] = ["Cooking"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Mahjong", "Piano"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended'] = ["Mahjong", "Cutting"]
        fake_json_response = self.create_mock_json_response()
        
        preferredActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 2"]["Result"] == "Failed"
        assert fake_json_response[1]["Test 2"]["Reason"] == [f"The following preferred activities are not scheduled: ['Cooking']"]
    
    def test_preferred_activities_patient_test_fail_with_one_exception(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_be_scheduled_activities']['preferred'] = ["Mahjong", "Dancing", "Cooking"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['error_check']['preferred'] = ["Mahjong", "Cooking"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Mahjong", "Piano"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended'] = ["Cutting"]
        fake_json_response = self.create_mock_json_response()
        
        preferredActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 2"]["Result"] == "Failed"
        assert fake_json_response[1]["Test 2"]["Reason"] == [f"(Exception) ['Mahjong'] are not scheduled because there are part of Activities Excluded", f"The following preferred activities are not scheduled: ['Cooking']"]
    
    def test_preferred_activities_patient_test_fail_with_two_exception(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_be_scheduled_activities']['preferred'] = ["Cutting","Mahjong", "Dancing", "Cooking"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['error_check']['preferred'] = ["Cutting","Mahjong", "Cooking"]
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
        fake_patient_wellness_plan['should_be_scheduled_activities']['preferred'] = ["Mahjong", "Dancing", "Cooking"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['error_check']['preferred'] = ["Mahjong"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Mahjong", "Piano"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended'] = ["Cutting"]
        fake_json_response = self.create_mock_json_response()
        
        preferredActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 2"]["Result"] == "Passed"
        assert fake_json_response[1]["Test 2"]["Reason"] == [f"(Exception) ['Mahjong'] are not scheduled because there are part of Activities Excluded"]
    
    def test_preferred_activities_patient_test_pass_with_two_exception(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_be_scheduled_activities']['preferred'] = ["Cutting","Mahjong", "Dancing", "Cooking"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['error_check']['preferred'] = ["Cutting","Mahjong"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Mahjong", "Piano"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended'] = ["Cutting"]
        fake_json_response = self.create_mock_json_response()
        
        preferredActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 2"]["Result"] == "Passed"
        assert fake_json_response[1]["Test 2"]["Reason"] == [
            f"(Exception) ['Mahjong'] are not scheduled because there are part of Activities Excluded",
            f"(Exception) ['Cutting'] are not scheduled because there are part of Doctor Non-Recommended Activities"
            ]
    
    
    '''
    Test 3: Patient non-preferred activities are not scheduled
    '''
    def test_non_preferred_activities_patient_test_pass(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_preferred'] = ["Piano"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['non_preferred'] = []
        fake_patient_wellness_plan['should_be_scheduled_activities']['recommended'] = ["Mahjong", "Cutting"]
        
        fake_json_response = self.create_mock_json_response()
        
        nonPreferredActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 3"]["Result"] == "Passed"
        assert fake_json_response[1]["Test 3"]["Reason"] == []
    
    def test_non_preferred_activities_patient_test_fail(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_preferred'] = ["Piano"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['non_preferred'] = ["Piano"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['recommended'] = ["Mahjong", "Cutting"]
        
        fake_json_response = self.create_mock_json_response()
        
        nonPreferredActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 3"]["Result"] == "Failed"
        assert fake_json_response[1]["Test 3"]["Reason"] == [f"The following non-preferred activities are scheduled: ['Piano']"]
    
    def test_non_preferred_activities_patient_test_pass_with_one_exception(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_preferred'] = ["Piano", "Mahjong"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['non_preferred'] = ["Mahjong"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['recommended'] = ["Mahjong", "Cutting"]
        
        fake_json_response = self.create_mock_json_response()
        
        nonPreferredActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 3"]["Result"] == "Passed"
        assert fake_json_response[1]["Test 3"]["Reason"] == ["(Exception) ['Mahjong'] are scheduled because there are part of Doctor Recommended Activities"]
    
    def test_non_preferred_activities_patient_test_fail_with_one_exception(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_preferred'] = ["Piano", "Mahjong"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['non_preferred'] = ["Mahjong", "Piano"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['recommended'] = ["Mahjong", "Cutting"]
        
        fake_json_response = self.create_mock_json_response()
        
        nonPreferredActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 3"]["Result"] == "Failed"
        assert fake_json_response[1]["Test 3"]["Reason"] == ["(Exception) ['Mahjong'] are scheduled because there are part of Doctor Recommended Activities","The following non-preferred activities are scheduled: ['Piano']"]
    
    
    '''
    Test 4: Doctor recommended activities are scheduled
    '''
    def test_recommended_activities_patient_test_pass(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Clip Coupons", "Piano"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['recommended'] = ["Cutting"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['error_check']['recommended'] = []
        
        fake_json_response = self.create_mock_json_response()
        
        recommendedActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 4"]["Result"] == "Passed"
        assert fake_json_response[1]["Test 4"]["Reason"] == []
    
    def test_recommended_activities_patient_test_fail(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Clip Coupons", "Piano"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['recommended'] = ["Cutting"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['error_check']['recommended'] = ["Cutting"]
        
        fake_json_response = self.create_mock_json_response()
        
        recommendedActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 4"]["Result"] == "Failed"
        assert fake_json_response[1]["Test 4"]["Reason"] == ["The following doctor recommended activities are not scheduled: ['Cutting']"]
    
    def test_recommended_activities_patient_test_fail_with_exception(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Clip Coupons", "Piano"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['recommended'] = ["Cutting", "Piano"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['error_check']['recommended'] = ["Cutting", "Piano"]
        
        fake_json_response = self.create_mock_json_response()
        
        recommendedActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 4"]["Result"] == "Failed"
        assert fake_json_response[1]["Test 4"]["Reason"] == ["(Exception) ['Piano'] are not scheduled because there are part of Activities Excluded","The following doctor recommended activities are not scheduled: ['Cutting']"]
    
    def test_recommended_activities_patient_test_pass_with_exception(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Clip Coupons", "Piano"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['recommended'] = ["Cutting", "Piano"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['error_check']['recommended'] = ["Piano"]
        
        fake_json_response = self.create_mock_json_response()
        
        recommendedActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 4"]["Result"] == "Passed"
        assert fake_json_response[1]["Test 4"]["Reason"] == ["(Exception) ['Piano'] are not scheduled because there are part of Activities Excluded"]
    
    
    '''
    Test 5: Doctor non-recommended activities are not scheduled
    '''
    def test_non_recommended_activities_patient_test_pass(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended'] = ["Clip Coupons"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['non_recommended'] = []
        
        fake_json_response = self.create_mock_json_response()
        
        nonRecommendedActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 5"]["Result"] == "Passed"
        assert fake_json_response[1]["Test 5"]["Reason"] == []
    
    def test_non_recommended_activities_patient_test_fail(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['non_recommended'] = ["Clip Coupons"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['error_check']['non_recommended'] = ["Clip Coupons"]
        
        fake_json_response = self.create_mock_json_response()
        
        nonRecommendedActivitiesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 5"]["Result"] == "Failed"
        assert fake_json_response[1]["Test 5"]["Reason"] == ["The following doctor non-recommended activities are scheduled: ['Clip Coupons']"]
    
    
    '''
    Test 6: Patient routines are scheduled 
    '''
    def test_routines_patient_test_pass(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_be_scheduled_activities']['routines'] = ["Sewing", "Piano"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['error_check']['routines'] = []
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Clip Coupons"]
        
        fake_json_response = self.create_mock_json_response()
        
        routinesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 6"]["Result"] == "Passed"
        assert fake_json_response[1]["Test 6"]["Reason"] == []
    
    def test_routines_patient_test_fail(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_be_scheduled_activities']['routines'] = ["Sewing", "Piano"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['error_check']['routines'] = ["Piano"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Clip Coupons", "Sewing"]
        
        fake_json_response = self.create_mock_json_response()
        
        routinesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 6"]["Result"] == "Failed"
        assert fake_json_response[1]["Test 6"]["Reason"] == ["The following routines are not scheduled: ['Piano']"]
    
    def test_routines_patient_test_pass_with_one_exception(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_be_scheduled_activities']['routines'] = ["Sewing", "Piano"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['error_check']['routines'] = ["Sewing"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Clip Coupons", "Sewing", "Piano"]
        
        fake_json_response = self.create_mock_json_response()
        
        routinesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 6"]["Result"] == "Passed"
        assert fake_json_response[1]["Test 6"]["Reason"] == ["(Exception) ['Sewing'] are not scheduled because there are part of Activities Excluded"]
    
    def test_routines_patient_test_fail_with_one_exception(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['should_be_scheduled_activities']['routines'] = ["Sewing", "Piano"]
        fake_patient_wellness_plan['should_be_scheduled_activities']['error_check']['routines'] = ["Sewing", "Piano"]
        fake_patient_wellness_plan['should_not_be_scheduled_activities']['excluded'] = ["Clip Coupons", "Piano"]
        
        fake_json_response = self.create_mock_json_response()
        
        routinesPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 6"]["Result"] == "Failed"
        assert fake_json_response[1]["Test 6"]["Reason"] == ["(Exception) ['Piano'] are not scheduled because there are part of Activities Excluded", "The following routines are not scheduled: ['Sewing']"]
    
    
    '''
    Test 7: All medications are administered correctly
    '''
    def test_medication_patient_test_pass(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        
        fake_json_response = self.create_mock_json_response()
        
        medicationPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 7"]["Result"] == "Passed"
        assert fake_json_response[1]["Test 7"]["Reason"] == {}
    
    def test_medication_patient_test_fail(self):
        fake_patient_wellness_plan = self.create_mock_patient_wellness_plan()
        fake_patient_wellness_plan['medication_info']['medication_schedule'][1] = ['Give Medication@0945: Galantamine(2 tabs)*']
        fake_patient_wellness_plan['medication_info']['error_check']['medication_schedule'][1] = ['Give Medication@0930: Galantamine(2 puffs)']
        fake_patient_wellness_plan['medication_info']['medication_schedule'][2] = ['Give Medication@0945: Galantamine(2 tabs)*']
        fake_patient_wellness_plan['medication_info']['error_check']['medication_schedule'][2] = ['Give Medication@0930: Galantamine(2 puffs)']
        
        fake_json_response = self.create_mock_json_response()
        
        medicationPatientTest(fake_patient_wellness_plan, fake_json_response)
        
        assert fake_json_response[1]["Test 7"]["Result"] == "Failed"
        assert fake_json_response[1]["Test 7"]["Reason"]["Tuesday"] == ["(Incorrect) The following medications were scheduled incorrectly: ['Give Medication@0930: Galantamine(2 puffs)']", "(Correct) The medications that are supposed to be scheduled are: ['Give Medication@0945: Galantamine(2 tabs)*']"]
        assert fake_json_response[1]["Test 7"]["Reason"]["Wednesday"] == ["(Incorrect) The following medications were scheduled incorrectly: ['Give Medication@0930: Galantamine(2 puffs)']", "(Correct) The medications that are supposed to be scheduled are: ['Give Medication@0945: Galantamine(2 tabs)*']"]
    
    
    '''
    Generate Statistics (Assumes that all other functions implemented are correct)
    '''
    def test_generate_statistics(self, mock_views):
        tablesDF = getTablesDF() 
        patientInfo = tablesDF['weeklyScheduleViewDF'].iloc[0]
        json_response = self.create_mock_json_response()
        activity_count_dict = {activity: 0 for activity in tablesDF['activitiesAndCentreActivityViewDF']['ActivityTitle'].unique()} # dictionary to keep track of each activity count
        mondayIndex = tablesDF['weeklyScheduleViewDF'].columns.get_loc("Monday")
        config = {
            'DAYS': 5,
            'DAY_OF_WEEK_ORDER': ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        }
        
        patient_wellness_plan = getPatientWellnessPlan(tablesDF, 1, config)
        
        prepareJsonResponse(json_response, patient_wellness_plan)
        checkWeeklyScheduleCorrectness(mondayIndex, patientInfo, patient_wellness_plan, json_response, activity_count_dict)
        generateStatistics(tablesDF, patient_wellness_plan, json_response, activity_count_dict)
        
        assert json_response[1]['Scheduled Activities Count'] == {
                "Lunch": 5,
                "Breathing+Vital Check": 5,
                "Board Games": 0,
                "Movie Screening": 1,
                "Brisk Walking": 1,
                "Mahjong": 1,
                "Musical Instrument Lesson": 1,
                "Story Time": 1,
                "Physiotherapy": 0,
                "String beads": 1,
                "Sewing": 6,
                "Cup Stacking Game": 4,
                "Sort poker chips": 3,
                "Origami": 2,
                "Picture Coloring": 1,
                "Clip Coupons": 3,
                "Cutting Pictures": 5,
                "Watch television": 0
        }
        assert json_response[1]['Group Activities Count'] == 15
        assert json_response[1]['Solo Activities Count'] == 25
    
