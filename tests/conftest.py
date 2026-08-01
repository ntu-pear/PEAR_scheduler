import pytest
import pandas as pd
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
from tests.utils.mock_db import get_db_session_mock
from tests.utils.scheduler_config import make_scheduler_config
from pear_schedule.models.ref_patient_model import RefPatient
from pear_schedule.models.ref_activity_model import RefActivity
from pear_schedule.models.ref_activity_exclusion_model import RefActivityExclusion
from pear_schedule.models.ref_activity_preference_model import RefActivityPreference
from pear_schedule.models.ref_activity_recommendation_model import RefActivityRecommendation
from pear_schedule.models.ref_activity_routine_model import RefActivityRoutine
from pear_schedule.models.ref_centre_activity_model import RefCentreActivity
from pear_schedule.models.ref_patient_medication_model import RefPatientMedication
from pear_schedule.models.schedule_model import Schedule

# CRUD / model fixtures

@pytest.fixture
def db_session_mock():
    """Fixture to mock the database session using the established pattern."""
    return get_db_session_mock()


@pytest.fixture
def sample_ref_patient():
    """Create a sample RefPatient instance"""
    return RefPatient(
        PatientID=1,
        Name="John Doe",
        PreferredName="John",
        UpdateBit="1",
        StartDate=datetime(2024, 1, 1),
        EndDate=datetime(2024, 12, 31),
        IsActive="1",
        IsDeleted="0",
        CreatedDateTime=datetime.now(),
        UpdatedDateTime=datetime.now(),
        CreatedById="test_user",
        ModifiedById="test_user"
    )


@pytest.fixture
def sample_ref_activity():
    """Create a sample RefActivity instance"""
    return RefActivity(
        ActivityID=1,
        ActivityTitle="Morning Exercise",
        ActivityDesc="Light exercise for seniors",
        IsDeleted="0",
        CreatedDateTime=datetime.now(),
        UpdatedDateTime=datetime.now(),
        CreatedById="test_user",
        ModifiedById="test_user"
    )


@pytest.fixture
def sample_schedule():
    """Create a sample Schedule instance based on actual data"""
    return Schedule(
        ScheduleID=1560,
        PatientID=3,
        StartDate=datetime(2024, 12, 2),
        EndDate=datetime(2024, 12, 8, 23, 59, 59),
        Monday="Breathing+Vital Check--Board Games--Picture Coloring--Lunch--Watch television--Act1--Leslie history routine--Clip Coupons",
        Tuesday="Breathing+Vital Check--Musical Instrument Lesson--Picture Coloring--Lunch--Watch television--Act1--Brisk Walking--String beads",
        Wednesday="Breathing+Vital Check--Mahjong--Watch television--Lunch--Picture Coloring--Act1--Leslie history routine--Clip Coupons",
        Thursday="Breathing+Vital Check--Watch television--Picture Coloring--Lunch--Sort poker chips--String beads--Clip Coupons--Sewing",
        Friday="Breathing+Vital Check--Watch television--Picture Coloring--Lunch--Sort poker chips--Act1--Leslie history routine--String beads",
        Saturday="",
        Sunday="",
        IsDeleted="0",
        CreatedDateTime=datetime(2024, 12, 3, 20, 34, 51, 653237),
        UpdatedDateTime=datetime(2024, 12, 3, 20, 34, 51, 653237),
        CreatedById="test_user",
        ModifiedById="test_user"
    )


@pytest.fixture
def sample_activity_exclusion():
    """Create a sample RefActivityExclusion instance"""
    return RefActivityExclusion(
        ActivityExclusionID=1,
        PatientID=1,
        CentreActivityID=1,
        StartDateTime=datetime(2024, 1, 1),
        EndDateTime=datetime(2024, 1, 7),
        ExclusionRemarks="Patient has mobility issues",
        IsDeleted="0",
        CreatedDateTime=datetime.now(),
        UpdatedDateTime=datetime.now(),
        CreatedById="test_user",
        ModifiedById="test_user"
    )


@pytest.fixture
def sample_activity_preference():
    """Create a sample RefActivityPreference instance"""
    return RefActivityPreference(
        CentreActivityPreferenceID=1,
        PatientID=1,
        CentreActivityID=1,
        IsLike="1",
        IsDeleted="0",
        CreatedDateTime=datetime.now(),
        UpdatedDateTime=datetime.now(),
        CreatedById="test_user",
        ModifiedById="test_user"
    )


@pytest.fixture
def sample_activity_recommendation():
    """Create a sample RefActivityRecommendation instance"""
    return RefActivityRecommendation(
        CentreActivityRecommendationID=1,
        PatientID=1,
        CentreActivityID=1,
        DoctorID="doc123",
        DoctorRecommendation="1",
        DoctorRemarks="Good for mobility",
        IsDeleted="0",
        CreatedDateTime=datetime.now(),
        UpdatedDateTime=datetime.now(),
        CreatedById="test_user",
        ModifiedById="test_user"
    )


@pytest.fixture
def sample_activity_routine():
    """Create a sample RefActivityRoutine instance based on actual data"""
    return RefActivityRoutine(
        RoutineID=1,
        PatientID=4,
        ActivityID=9,
        IncludeInSchedule="1",
        RoutineIssues="Too slow",
        RoutineTimeSlots="0-2,4-2",
        IsDeleted="0",
        CreatedDateTime=datetime(2024, 2, 27, 0, 54, 33, 981608),
        UpdatedDateTime=datetime(2024, 2, 27, 0, 54, 33, 981609),
        CreatedById="test_user",
        ModifiedById="test_user"
    )

@pytest.fixture
def sample_centre_activity():
    """Create a sample RefCentreActivity instance"""
    return RefCentreActivity(
        CentreActivityID=1,
        ActivityID=1,
        IsDeleted="0",
        IsCompulsory="0",
        IsFixed="0",
        IsGroup="0",
        StartDate=datetime(2024, 1, 1),
        EndDate=datetime(2024, 12, 31),
        MinDuration=30,
        MaxDuration=60,
        MinPeopleReq=1,
        FixedTimeSlots=None,
        CreatedDateTime=datetime.now(),
        UpdatedDateTime=datetime.now(),
        CreatedById="test_user",
        ModifiedById="test_user"
    )


@pytest.fixture
def sample_patient_medication():
    """Create a sample RefPatientMedication instance"""
    return RefPatientMedication(
        MedicationID=1,
        PatientID=1,
        PrescriptionName="Aspirin",
        Dosage="1 tablet",
        Instruction="Take with food",
        StartDateTime=datetime(2024, 1, 1),
        EndDateTime=datetime(2024, 12, 31),
        PrescriptionRemarks="For blood thinning",
        IsDeleted="0",
        CreatedDateTime=datetime.now(),
        UpdatedDateTime=datetime.now(),
        CreatedById="test_user",
        ModifiedById="test_user"
    )


@pytest.fixture
def sample_complex_routine():
    """Create a sample routine with complex issues based on actual data"""
    return RefActivityRoutine(
        RoutineID=8,
        PatientID=13,
        ActivityID=20,
        IncludeInSchedule="1",
        RoutineIssues="Here we choose Tues and Thurs. In Manage Activities it was Mon, Wed, Fri.",
        RoutineTimeSlots="1-6,3-6",  # Tuesday and Thursday at 6pm
        IsDeleted="0",
        CreatedDateTime=datetime(2024, 4, 17, 11, 31, 10, 635244),
        UpdatedDateTime=datetime(2024, 4, 17, 11, 31, 10, 635247),
        CreatedById="test_user",
        ModifiedById="test_user"
    )


@pytest.fixture
def sample_overlapping_schedule():
    """Create a sample overlapping schedule for testing conflicts"""
    return Schedule(
        ScheduleID=9999,
        PatientID=3,  # Same patient as sample_schedule
        StartDate=datetime(2024, 12, 5),  # Overlaps with existing schedule
        EndDate=datetime(2024, 12, 12),
        Monday="Different Monday Activities",
        Tuesday="Different Tuesday Activities",
        Wednesday="Different Wednesday Activities",
        Thursday="Different Thursday Activities",
        Friday="Different Friday Activities",
        Saturday="Weekend Activities",
        Sunday="Sunday Activities",
        IsDeleted="0",
        CreatedDateTime=datetime.now(),
        UpdatedDateTime=datetime.now(),
        CreatedById="test_user",
        ModifiedById="test_user"
    )


@pytest.fixture
def mock_log_crud_action():
    """Mock the log_crud_action function"""
    with patch('pear_schedule.crud.schedule_crud.log_crud_action') as mock_log:
        yield mock_log


@pytest.fixture
def mock_serialize_data():
    """Mock the serialize_data function"""
    with patch('pear_schedule.crud.schedule_crud.serialize_data') as mock_serialize:
        mock_serialize.side_effect = lambda x: str(x)
        yield mock_serialize


# Scheduler fixtures - config/date + one empty-or-sample DataFrame per views.py View class
# used across the scheduler tests

@pytest.fixture
def scheduler_config():
    """See tests/utils/scheduler_config.py - deterministic, no datetime.now() in here."""
    return make_scheduler_config()


@pytest.fixture
def fixed_monday():
    return datetime(2024, 3, 18)


@pytest.fixture
def compulsory_activities_df():
    return pd.DataFrame({
        "ActivityTitle": ["Breathing+Vital Check"],
        "IsFixed": [1],
        "FixedTimeSlots": ["0-0"],
        "MinDuration": [30],
    })


@pytest.fixture
def recommended_activities_df():
    return pd.DataFrame({
        "ActivityID": [1],
        "IsFixed": [1],
        "MinDuration": [30],
        "ActivityTitle": ["Physiotherapy"],
        "FixedTimeSlots": ["0-1"],
        "PatientID": [1],
        "ActivityEndDate": [pd.Timestamp("2099-12-31")],
    })


@pytest.fixture
def disrecommended_activities_df():
    return pd.DataFrame({
        "ActivityID": pd.Series([], dtype="int64"),
        "IsFixed": pd.Series([], dtype="int64"),
        "ActivityTitle": pd.Series([], dtype="object"),
        "PatientID": pd.Series([], dtype="int64"),
        "ActivityEndDate": pd.Series([], dtype="datetime64[ns]"),
    })


@pytest.fixture
def patients_view_df():
    return pd.DataFrame({
        "PatientID": pd.Series([], dtype="int64"),
        "PreferredActivityID": pd.Series([], dtype="int64"),
        "ActivityEndDate": pd.Series([], dtype="datetime64[ns]"),
    })


@pytest.fixture
def patients_unpreferred_df():
    return pd.DataFrame({
        "PatientID": pd.Series([], dtype="int64"),
        "DispreferredActivityID": pd.Series([], dtype="int64"),
        "ActivityEndDate": pd.Series([], dtype="datetime64[ns]"),
    })


@pytest.fixture
def activities_excluded_df():
    return pd.DataFrame({
        "ActivityExclusionID": pd.Series([], dtype="int64"),
        "ActivityID": pd.Series([], dtype="int64"),
        "PatientID": pd.Series([], dtype="int64"),
        "ExclusionRemarks": pd.Series([], dtype="object"),
        "EndDateTime": pd.Series([], dtype="datetime64[ns]"),
        "ActivityTitle": pd.Series([], dtype="object"),
    })


@pytest.fixture
def activities_view_df():
    return pd.DataFrame({
        "ActivityID": [1],
        "ActivityTitle": ["Board Games"],
        "IsFixed": [0],
        "FixedTimeSlots": [""],
        "MinDuration": [30],
        "MaxDuration": [30],
        "EndDate": [pd.Timestamp("2099-12-31")],
        "StartDate": [pd.Timestamp("2020-01-01")],
    })


@pytest.fixture
def group_activities_only_df():
    return pd.DataFrame({
        "ActivityID": [1],
        "CentreActivityID": [1],
        "ActivityTitle": ["Mahjong"],
        "IsFixed": [0],
        "FixedTimeSlots": [""],
        "MinPeopleReq": [2],
        "MinDuration": [30],
    })


@pytest.fixture
def group_activities_preference_df():
    return pd.DataFrame({
        "CentreActivityID": pd.Series([], dtype="int64"),
        "PatientID": pd.Series([], dtype="int64"),
        "IsLike": pd.Series([], dtype="int64"),
    })


@pytest.fixture
def group_activities_recommendation_df():
    return pd.DataFrame({
        "CentreActivityID": pd.Series([], dtype="int64"),
        "PatientID": pd.Series([], dtype="int64"),
        "DoctorRecommendation": pd.Series([], dtype="int64"),
    })


@pytest.fixture
def group_activities_exclusion_df():
    return pd.DataFrame({
        "CentreActivityID": pd.Series([], dtype="int64"),
        "PatientID": pd.Series([], dtype="int64"),
    })


@pytest.fixture
def patients_only_df():
    return pd.DataFrame({"PatientID": [1, 2]})


@pytest.fixture
def medication_view_df():
    return pd.DataFrame({
        "PatientID": [1],
        "MedicationID": [1],
        "PrescriptionName": ["Aspirin"],
        "Dosage": ["1 tablet"],
        "AdministerTime": ["0900"],
        "StartDateTime": [pd.Timestamp("2020-01-01")],
        "EndDateTime": [pd.Timestamp("2099-12-31")],
        "Instruction": ["Take with food"],
        "IsDeleted": [0],
    })


@pytest.fixture
def caregiver_allocated_df():
    return pd.DataFrame({
        "patientId": [1],
        "caregiverId": ["CG1"],
        "tempCaregiverId": [""],
        "supervisorId": ["SUP1"],
    })


@pytest.fixture
def adhoc_activity_df():
    return pd.DataFrame({
        "AdhocID": [1],
        "PatientID": [1],
        "PatientName": ["John Doe"],
        "OldCentreActivityID": [1],
        "OldActivityTitle": ["Breathing+Vital Check"],
        "NewCentreActivityID": [2],
        "NewActivityTitle": ["Adhoc Replacement Activity"],
        "StartDate": [pd.Timestamp("2024-03-18")],
        "EndDate": [pd.Timestamp("2024-03-24")],
        "Status": ["Active"],
        "IsDeleted": [0],
        "CreatedDateTime": [pd.Timestamp("2024-03-01")],
        "UpdatedDateTime": [pd.Timestamp("2024-03-01")],
    })