import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime
from tests.utils.mock_db import get_db_session_mock
from pear_schedule.models.ref_patient_model import RefPatient
from pear_schedule.models.ref_activity_model import RefActivity
from pear_schedule.models.ref_activity_exclusion_model import RefActivityExclusion
from pear_schedule.models.ref_activity_preference_model import RefActivityPreference
from pear_schedule.models.ref_activity_recommendation_model import RefActivityRecommendation
from pear_schedule.models.ref_activity_routine_model import RefActivityRoutine
from pear_schedule.models.ref_patient_medication_model import RefPatientMedication
from pear_schedule.models.schedule_model import Schedule


@pytest.fixture
def db_session_mock():
    """Fixture to mock the database session using the established pattern."""
    return get_db_session_mock()


@pytest.fixture
def sample_ref_patient():
    """Create a sample RefPatient instance"""
    return RefPatient(
        Id=1,
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
        Id=1560,
        PatientId=3,
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
        ActivityID=1,
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
        Id=1,
        PatientId=4,
        ActivityId=9,
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
def sample_patient_medication():
    """Create a sample RefPatientMedication instance"""
    return RefPatientMedication(
        Id=1,
        PatientId=1,
        PrescriptionName="Aspirin",
        Dosage="1 tablet",
        FrequencyPerDay=1,
        Instruction="Take with food",
        StartDate=datetime(2024, 1, 1),
        EndDate=datetime(2024, 12, 31),
        IsAfterMeal="1",
        PrescriptionRemarks="For blood thinning",
        Status="Active",
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
        Id=8,
        PatientId=13,
        ActivityId=20,
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
        Id=9999,
        PatientId=3,  # Same patient as sample_schedule
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
    with pytest.mock.patch('app.crud.schedule_crud.log_crud_action') as mock_log:
        yield mock_log


@pytest.fixture
def mock_serialize_data():
    """Mock the serialize_data function"""
    with pytest.mock.patch('app.crud.schedule_crud.serialize_data') as mock_serialize:
        mock_serialize.side_effect = lambda x: str(x)
        yield mock_serialize
