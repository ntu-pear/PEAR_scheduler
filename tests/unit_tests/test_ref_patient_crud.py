import pytest
from unittest.mock import Mock, patch
from datetime import datetime
from pear_schedule.crud.ref_patient_crud import (
    create_or_update_ref_patient,
    update_ref_patient_idempotent,
    soft_delete_ref_patient_idempotent,
    get_ref_patients
)
from pear_schedule.schemas.ref_patient import RefPatientCreate, RefPatientUpdate


class TestRefPatientCrud:
    
    def test_create_or_update_ref_patient_create_new(self, db_session_mock, sample_ref_patient):
        """Test creating a new patient when one doesn't exist"""
        # Mock that no existing patient is found, then return the new patient
        db_session_mock.query().filter().first.side_effect = [None, sample_ref_patient]
        
        # Mock the patient data
        patient_data = RefPatientCreate(
            Id=1,
            Name="John Doe",
            PreferredName="John",
            UpdateBit="1",
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 12, 31),
            IsActive="1",
            IsDeleted="0",
            CreatedDateTime=datetime.utcnow(),
            UpdatedDateTime=datetime.utcnow(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )
        
        with patch('app.crud.ref_patient_crud.text') as mock_text:
            result = create_or_update_ref_patient(db_session_mock, patient_data, "test_user")
        
        # Verify database operations were called
        db_session_mock.execute.assert_called_once()
        db_session_mock.commit.assert_called_once()
        assert result == sample_ref_patient

    def test_create_or_update_ref_patient_update_existing(self, db_session_mock, sample_ref_patient):
        """Test updating an existing patient"""
        # Mock that an existing patient is found
        db_session_mock.query().filter().first.return_value = sample_ref_patient
        
        patient_data = RefPatientCreate(
            Id=1,
            Name="John Updated",
            PreferredName="Johnny",
            UpdateBit="1",
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 12, 31),
            IsActive="1",
            IsDeleted="0",
            CreatedDateTime=datetime.utcnow(),
            UpdatedDateTime=datetime.utcnow(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )
        
        result = create_or_update_ref_patient(db_session_mock, patient_data, "test_user")
        
        # Verify update operations
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_ref_patient)
        assert result == sample_ref_patient

    def test_update_ref_patient_idempotent_patient_exists(self, db_session_mock, sample_ref_patient):
        """Test updating a patient that exists"""
        db_session_mock.query().filter().first.return_value = sample_ref_patient
        
        update_data = RefPatientUpdate(
            Id=1,
            Name="Updated Name",
            PreferredName="Updated Preferred",
            UpdateBit="1",
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 12, 31),
            IsActive="1",
            IsDeleted="0",
            UpdatedDateTime=datetime.utcnow(),
            ModifiedById="test_user"
        )
        
        result = update_ref_patient_idempotent(db_session_mock, 1, update_data, "test_user")
        
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_ref_patient)
        assert result == sample_ref_patient

    def test_update_ref_patient_idempotent_patient_not_exists(self, db_session_mock):
        """Test updating a patient that doesn't exist (should return None gracefully)"""
        db_session_mock.query().filter().first.return_value = None
        
        update_data = RefPatientUpdate(
            Id=1,
            Name="Updated Name",
            PreferredName="Updated Preferred", 
            UpdateBit="1",
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 12, 31),
            IsActive="1",
            IsDeleted="0",
            UpdatedDateTime=datetime.utcnow(),
            ModifiedById="test_user"
        )
        
        result = update_ref_patient_idempotent(db_session_mock, 999, update_data, "test_user")
        
        assert result is None
        db_session_mock.commit.assert_not_called()

    def test_soft_delete_ref_patient_idempotent_patient_exists(self, db_session_mock, sample_ref_patient):
        """Test soft deleting a patient that exists"""
        db_session_mock.query().filter().first.return_value = sample_ref_patient
        
        result = soft_delete_ref_patient_idempotent(db_session_mock, 1, "test_user")
        
        assert sample_ref_patient.IsDeleted == "1"
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_ref_patient)
        assert result == sample_ref_patient

    def test_soft_delete_ref_patient_idempotent_patient_not_exists(self, db_session_mock):
        """Test soft deleting a patient that doesn't exist (should return None gracefully)"""
        db_session_mock.query().filter().first.return_value = None
        
        result = soft_delete_ref_patient_idempotent(db_session_mock, 999, "test_user")
        
        assert result is None
        db_session_mock.commit.assert_not_called()

    def test_soft_delete_ref_patient_idempotent_already_deleted(self, db_session_mock, sample_ref_patient):
        """Test soft deleting a patient that's already deleted"""
        sample_ref_patient.IsDeleted = "1"
        db_session_mock.query().filter().first.return_value = sample_ref_patient
        
        result = soft_delete_ref_patient_idempotent(db_session_mock, 1, "test_user")
        
        assert result == sample_ref_patient
        db_session_mock.commit.assert_not_called()

    def test_get_ref_patients_with_filters(self, db_session_mock, sample_ref_patient):
        """Test getting patients with name and isActive filters"""
        # Set up the mock for the main query
        db_session_mock.query().filter().filter().filter().order_by().offset().limit().all.return_value = [sample_ref_patient]
        
        # Set up the mock for the count query  
        db_session_mock.query().scalar.return_value = 1
        
        patients, total_records, total_pages = get_ref_patients(
            db_session_mock, 
            pageNo=0, 
            pageSize=10, 
            name="John", 
            isActive="1"
        )
        
        assert len(patients) == 1
        assert patients[0] == sample_ref_patient
        assert total_records == 1
        assert total_pages == 1

    def test_get_ref_patients_no_filters(self, db_session_mock, sample_ref_patient):
        """Test getting patients without filters"""
        db_session_mock.query().filter().order_by().offset().limit().all.return_value = [sample_ref_patient]
        db_session_mock.query().scalar.return_value = 1
        
        patients, total_records, total_pages = get_ref_patients(db_session_mock)
        
        assert len(patients) == 1
        assert total_records == 1
        assert total_pages == 1

    def test_get_ref_patients_pagination(self, db_session_mock):
        """Test pagination calculations"""
        db_session_mock.query().filter().order_by().offset().limit().all.return_value = []
        db_session_mock.query().scalar.return_value = 25
        
        patients, total_records, total_pages = get_ref_patients(
            db_session_mock, 
            pageNo=1, 
            pageSize=10
        )
        
        assert total_records == 25
        assert total_pages == 3  # math.ceil(25/10) = 3
