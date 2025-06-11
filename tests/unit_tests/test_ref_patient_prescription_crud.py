import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta
from app.crud.ref_patient_prescription_crud import (
    create_or_update_ref_patient_prescription,
    update_ref_patient_prescription_idempotent,
    soft_delete_ref_patient_prescription_idempotent,
    get_ref_patient_prescriptions,
    get_ref_patient_prescription_by_id,
    get_patient_active_prescriptions,
    get_patient_prescriptions_by_status,
    get_prescriptions_ending_soon,
    get_patient_medication_schedule
)
from app.schemas.ref_patient_prescription import RefPatientPrescriptionCreate, RefPatientPrescriptionUpdate


class TestRefPatientPrescriptionCrud:
    
    def test_create_or_update_ref_patient_prescription_create_new(self, db_session_mock, sample_patient_prescription):
        """Test creating a new patient prescription when one doesn't exist"""
        # Mock that no existing prescription is found
        db_session_mock.query().filter().first.return_value = None
        
        prescription_data = RefPatientPrescriptionCreate(
            Id=1,
            PatientId=1,
            PrescriptionListId=1,
            PrescriptionListValue="Aspirin 100mg",
            Dosage="1 tablet",
            FrequencyPerDay=1,
            Instruction="Take with food",
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 12, 31),
            IsAfterMeal="1",
            PrescriptionRemarks="For blood thinning",
            Status="Active",
            IsDeleted="0",
            CreatedDateTime=datetime.utcnow(),
            UpdatedDateTime=datetime.utcnow(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )
        
        # Mock refresh to set the Id after creation
        def mock_refresh(obj):
            obj.Id = 1
        db_session_mock.refresh.side_effect = mock_refresh
        
        result = create_or_update_ref_patient_prescription(db_session_mock, prescription_data, "test_user", "Test User")
        
        db_session_mock.add.assert_called_once()
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once()

    def test_create_or_update_ref_patient_prescription_update_existing(self, db_session_mock, sample_patient_prescription):
        """Test updating an existing patient prescription"""
        # Mock that existing prescription is found
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_patient_prescription
        
        prescription_data = RefPatientPrescriptionCreate(
            Id=1,
            PatientId=1,
            PrescriptionListId=1,
            PrescriptionListValue="Aspirin 100mg",
            Dosage="2 tablets",  # Updated dosage
            FrequencyPerDay=2,   # Updated frequency
            Instruction="Take with food twice daily",
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 12, 31),
            IsAfterMeal="1",
            PrescriptionRemarks="Updated - For blood thinning",
            Status="Active",
            IsDeleted="0",
            CreatedDateTime=datetime.utcnow(),
            UpdatedDateTime=datetime.utcnow(),
            CreatedById="test_user",
            ModifiedById="test_user"
        )
        
        # Add Id attribute to simulate existing record
        prescription_data.Id = 1
        
        result = create_or_update_ref_patient_prescription(db_session_mock, prescription_data, "test_user", "Test User")
        
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_patient_prescription)
        assert result == sample_patient_prescription

    def test_update_ref_patient_prescription_idempotent_exists(self, db_session_mock, sample_patient_prescription):
        """Test updating a patient prescription that exists"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_patient_prescription
        
        update_data = RefPatientPrescriptionUpdate(
            Id=1,
            PatientId=1,
            PrescriptionListId=1,
            PrescriptionListValue="Aspirin 100mg",
            Dosage="1.5 tablets",
            FrequencyPerDay=2,
            Instruction="Take with food, morning and evening",
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 12, 31),
            IsAfterMeal="1",
            PrescriptionRemarks="Updated dosage",
            Status="Active",
            IsDeleted="0",
            UpdatedDateTime=datetime.utcnow(),
            ModifiedById="test_user"
        )
        
        result = update_ref_patient_prescription_idempotent(db_session_mock, 1, update_data, "test_user")
        
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_patient_prescription)
        assert result == sample_patient_prescription

    def test_update_ref_patient_prescription_idempotent_not_exists(self, db_session_mock):
        """Test updating a patient prescription that doesn't exist"""
        db_session_mock.query().filter().first.return_value = None
        
        update_data = RefPatientPrescriptionUpdate(
            Id=1,
            PatientId=1,
            PrescriptionListId=1,
            PrescriptionListValue="Aspirin 100mg",
            Dosage="1.5 tablets",
            FrequencyPerDay=2,
            Instruction="Take with food, morning and evening",
            StartDate=datetime(2024, 1, 1),
            EndDate=datetime(2024, 12, 31),
            IsAfterMeal="1",
            PrescriptionRemarks="Updated dosage",
            Status="Active",
            IsDeleted="0",
            UpdatedDateTime=datetime.utcnow(),
            ModifiedById="test_user"
        )
        
        result = update_ref_patient_prescription_idempotent(db_session_mock, 999, update_data, "test_user")
        
        assert result is None
        db_session_mock.commit.assert_not_called()

    def test_soft_delete_ref_patient_prescription_idempotent_exists(self, db_session_mock, sample_patient_prescription):
        """Test soft deleting a patient prescription that exists"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_patient_prescription
        
        result = soft_delete_ref_patient_prescription_idempotent(db_session_mock, 1, "test_user")
        
        assert sample_patient_prescription.IsDeleted == "1"
        db_session_mock.commit.assert_called_once()
        db_session_mock.refresh.assert_called_once_with(sample_patient_prescription)
        assert result == sample_patient_prescription

    def test_get_ref_patient_prescriptions_with_filters(self, db_session_mock, sample_patient_prescription):
        """Test getting patient prescriptions with filters"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [sample_patient_prescription]
        db_session_mock.query.return_value.scalar.return_value = 1
        
        prescriptions, total_records, total_pages = get_ref_patient_prescriptions(
            db_session_mock,
            pageNo=0,
            pageSize=10,
            patient_id=1,
            status="Active",
            prescription_value="Aspirin"
        )
        
        assert len(prescriptions) == 1
        assert prescriptions[0] == sample_patient_prescription
        assert total_records == 1
        assert total_pages == 1

    def test_get_ref_patient_prescriptions_with_active_filter(self, db_session_mock, sample_patient_prescription):
        """Test getting patient prescriptions with active filter"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [sample_patient_prescription]
        db_session_mock.query.return_value.scalar.return_value = 1
        
        prescriptions, total_records, total_pages = get_ref_patient_prescriptions(
            db_session_mock,
            pageNo=0,
            pageSize=10,
            patient_id=1,
            is_active=True
        )
        
        assert len(prescriptions) == 1
        assert total_records == 1
        assert total_pages == 1

    def test_get_patient_active_prescriptions(self, db_session_mock, sample_patient_prescription):
        """Test getting all active prescriptions for a patient"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = [sample_patient_prescription]
        
        result = get_patient_active_prescriptions(db_session_mock, 1)
        
        assert len(result) == 1
        assert result[0] == sample_patient_prescription

    def test_get_patient_prescriptions_by_status(self, db_session_mock, sample_patient_prescription):
        """Test getting patient prescriptions by status"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = [sample_patient_prescription]
        
        result = get_patient_prescriptions_by_status(db_session_mock, 1, "Active")
        
        assert len(result) == 1
        assert result[0] == sample_patient_prescription

    def test_get_prescriptions_ending_soon(self, db_session_mock, sample_patient_prescription):
        """Test getting prescriptions ending within specified days"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = [sample_patient_prescription]
        
        result = get_prescriptions_ending_soon(db_session_mock, days=7)
        
        assert len(result) == 1
        assert result[0] == sample_patient_prescription

    def test_get_patient_medication_schedule(self, db_session_mock, sample_patient_prescription):
        """Test getting patient's medication schedule"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = [sample_patient_prescription]
        
        result = get_patient_medication_schedule(db_session_mock, 1)
        
        assert len(result) == 1
        assert result[0] == sample_patient_prescription

    def test_get_patient_medication_schedule_with_meal_filter(self, db_session_mock, sample_patient_prescription):
        """Test getting patient's medication schedule with meal timing filter"""
        db_session_mock.query.return_value.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = [sample_patient_prescription]
        
        result = get_patient_medication_schedule(db_session_mock, 1, is_after_meal="1")
        
        assert len(result) == 1
        assert result[0] == sample_patient_prescription

    def test_get_ref_patient_prescription_by_id_found(self, db_session_mock, sample_patient_prescription):
        """Test getting a patient prescription by ID when it exists"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = sample_patient_prescription
        
        result = get_ref_patient_prescription_by_id(db_session_mock, 1)
        
        assert result == sample_patient_prescription

    def test_get_ref_patient_prescription_by_id_not_found(self, db_session_mock):
        """Test getting a patient prescription by ID when it doesn't exist"""
        db_session_mock.query.return_value.filter.return_value.first.return_value = None
        
        result = get_ref_patient_prescription_by_id(db_session_mock, 999)
        
        assert result is None
