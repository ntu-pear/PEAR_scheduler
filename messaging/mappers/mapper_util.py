import logging
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

class MapperUtil:
    """
    Universal mapper that handles all source-to-target transformations
    Easy to configure and maintain for up to 10 source-destination pairs
    """
    
    def __init__(self):
        # Mapping configurations - easily add new ones here
        self.mapping_configs = {
            # Patient Service → Scheduler Service
            'patient_service_to_scheduler': {
                'source_service': 'patient-service',
                'target_service': 'scheduler-service', 
                'entity_type': 'patient',
                'required_fields': ['id', 'name'],
                'field_mappings': {
                    # Direct mappings (source_field: target_field)
                    'id': 'PatientID',
                    'name': 'Name',
                    'preferredName': 'PreferredName',
                    'isActive': 'IsActive',
                    'isDeleted': 'IsDeleted',
                    'updateBit': 'UpdateBit',
                    'startDate': 'StartDate',
                    'endDate': 'EndDate',
                    'createdDate': 'CreatedDateTime',
                    'modifiedDate': 'UpdatedDateTime',
                    'CreatedById': 'CreatedById',
                    'ModifiedById': 'ModifiedById',
                },
                'field_transforms': {
                    # Special transformations (target_field: transform_function)
                    'IsActive': lambda x: self._convert_boolean(x, "1"),
                    'IsDeleted': lambda x: self._convert_boolean(x, "0"), 
                    'UpdateBit': lambda x: self._convert_boolean(x, "1"),
                    'StartDate': lambda x: self._parse_datetime(x) or datetime.now(),
                    'EndDate': lambda x: self._parse_datetime(x),
                    'CreatedDateTime': lambda x: self._parse_datetime(x) or datetime.now(),
                    'UpdatedDateTime': lambda x: self._parse_datetime(x) or datetime.now(),
                },
                'defaults': {
                    'IsActive': '1',
                    'IsDeleted': '0'
                },
                'ignored_fields': [
                    # Source fields to ignore
                    'nric', 'address', 'tempAddress', 'homeNo', 'handphoneNo',
                    'profilePicture', 'privacyLevel', 'preferredLanguageId',
                    'isApproved', 'isRespiteCare', 'autoGame', 'inActiveReason',
                    'terminationReason', 'inActiveDate', 'dateOfBirth', 'gender'
                ]
            },

            # Patient Service → Scheduler Service (Patient Medication)
            'patient_medication_service_to_scheduler': {
                'source_service': 'patient-service',
                'target_service': 'scheduler-service', 
                'entity_type': 'patient_medication',
                'required_fields': ['Id', 'PatientId'],
                'field_mappings': {
                    # Direct mappings (source_field: target_field) - updated to match your schema
                    'Id': 'MedicationID',  # Keep same field name
                    'PatientId': 'PatientID',  # Required field
                    'PrescriptionName': 'PrescriptionName',
                    'AdministerTime': 'AdministerTime',
                    'Dosage': 'Dosage',
                    'Instruction': 'Instruction',
                    'StartDate': 'StartDateTime',
                    'EndDate': 'EndDateTime',
                    'PrescriptionRemarks': 'PrescriptionRemarks',
                    'IsDeleted': 'IsDeleted',
                    'CreatedDateTime': 'CreatedDateTime',
                    'UpdatedDateTime': 'UpdatedDateTime',
                    'CreatedById': 'CreatedById',
                    'ModifiedById': 'ModifiedById',
                },
                'field_transforms': {
                    # Special transformations (target_field: transform_function)
                    'IsDeleted': lambda x: self._convert_boolean(x, "0"),
                    'StartDate': lambda x: self._parse_datetime(x),
                    'EndDate': lambda x: self._parse_datetime(x),
                    'CreatedDateTime': lambda x: self._parse_datetime(x) or datetime.now(),
                    'UpdatedDateTime': lambda x: self._parse_datetime(x) or datetime.now(),
                    'Dosage': lambda x: str(x) if x is not None else "",
                    'Instruction': lambda x: str(x) if x is not None else "",
                    'PrescriptionRemarks': lambda x: str(x) if x is not None else "",
                },
                'defaults': {
                    'IsDeleted': '0',
                    'CreatedDateTime': datetime.now(),
                    'UpdatedDateTime': datetime.now(),
                    'CreatedById': 'patient_service',
                    'ModifiedById': 'patient_service',
                    'PrescriptionRemarks': '',
                },
                'ignored_fields': [
                    # Source fields to ignore - adjust based on your source model
                    'patient', 'prescription_list'  # SQLAlchemy relationship fields
                ]
            },
            # Patient Allocation mapping (Patient Service -> Scheduler Service)
            'patient_allocation_service_to_scheduler': {
                'source_service': 'patient-service',
                'target_service': 'scheduler-service',
                'entity_type': 'patient_allocation',
                'required_fields': ['id', 'patientId', 'doctorId', 'gameTherapistId', 
                                   'supervisorId', 'caregiverId'],
                'field_mappings': {
                    'id': 'id',
                    'active': 'active',
                    'isDeleted': 'is_deleted',
                    'patientId': 'patient_id',
                    'doctorId': 'doctor_id',
                    'gameTherapistId': 'game_therapist_id',
                    'supervisorId': 'supervisor_id',
                    'caregiverId': 'caregiver_id',
                    'tempDoctorId': 'temp_doctor_id',
                    'tempCaregiverId': 'temp_caregiver_id',
                    'createdDate': 'created_date',
                    'modifiedDate': 'modified_date',
                    'CreatedById': 'created_by_id',
                    'ModifiedById': 'modified_by_id',
                },
                'field_transforms': {
                    'is_deleted': lambda x: self._convert_boolean(x, "0"),
                    'created_date': lambda x: self._parse_datetime(x) or datetime.now(),
                    'modified_date': lambda x: self._parse_datetime(x) or datetime.now(),
                    'temp_doctor_id': lambda x: str(x) if x is not None else None,
                    'temp_caregiver_id': lambda x: str(x) if x is not None else None,
                },
                'defaults': {
                    'active': 'Y',
                    'is_deleted': '0',
                    'created_by_id': 'patient_service',
                    'modified_by_id': 'patient_service'
                },
                'ignored_fields': [
                    # Ignore guardian relationships for now
                    'guardianId', 'guardian2Id'
                ]
            },
                    
            # Activity Service → Scheduler Service
            'activity_service_to_scheduler': {
                'source_service': 'activity-service',
                'target_service': 'scheduler-service',
                'entity_type': 'activity',
                'required_fields': ['id', 'title'],
                'field_mappings': {
                    # Direct mappings (source_field: target_field)
                    'id': 'ActivityID',
                    'title': 'ActivityTitle',
                    'description': 'ActivityDesc',
                    'is_deleted': 'IsDeleted',
                    'created_date': 'CreatedDateTime',
                    'modified_date': 'UpdatedDateTime',
                    'created_by_id': 'CreatedById',
                    'modified_by_id': 'ModifiedById',
                },
                'field_transforms': {
                    # Special transformations (target_field: transform_function)
                    'IsDeleted': lambda x: self._convert_boolean(x, "0"),
                    'CreatedById': lambda x: x or "activity_service",
                    'ModifiedById': lambda x: x or "activity_service",
                    'CreatedDateTime': lambda x: self._parse_datetime(x) or datetime.now(),
                    'UpdatedDateTime': lambda x: self._parse_datetime(x) or datetime.now(),
                },
                'defaults': {
                    'IsDeleted': '0',
                    'CreatedDateTime': datetime.now(),
                    'UpdatedDateTime': datetime.now(),
                    'CreatedById': 'activity_service',
                    'ModifiedById': 'activity_service'
                },
                'ignored_fields': [
                    # Source fields to ignore
                    'createdById', 'modifiedById', 'isDeleted'
                ]
            },

            # Activity Service → Scheduler Service (Activity Preferences)
            'activity_preference_service_to_scheduler': {
                'source_service': 'activity-service',
                'target_service': 'scheduler-service',
                'entity_type': 'activity_preference',
                'required_fields': ['centre_activity_id', 'patient_id'],
                'field_mappings': {
                    'id': 'CentreActivityPreferenceID',
                    'centre_activity_id': 'CentreActivityID',
                    'patient_id': 'PatientID',
                    'is_like': 'IsLike',
                    'is_deleted': 'IsDeleted',
                    'created_date': 'CreatedDateTime',
                    'modified_date': 'UpdatedDateTime',
                    'created_by_id': 'CreatedById',
                    'modified_by_id': 'ModifiedById',
                },
                'field_transforms': {
                    'IsLike': lambda x: self._convert_preference_value(x, "0"),  # Convert to -1, 0, or 1
                    'IsDeleted': lambda x: self._convert_boolean(x, "0"),
                    'ModifiedById': lambda x: x or "activity_service",
                    'CreatedDateTime': lambda x: self._parse_datetime(x) or datetime.now(),
                    'UpdatedDateTime': lambda x: self._parse_datetime(x) or datetime.now(),
                },
                'defaults': {
                    'IsDeleted': '0',
                    'IsLike': '0',  # Neutral preference
                    'CreatedDateTime': datetime.now(),
                    'UpdatedDateTime': datetime.now(),
                    'CreatedById': 'activity_service',
                    'ModifiedById': 'activity_service'
                },
                'ignored_fields': []
            },

            # Activity Service → Scheduler Service (Activity Recommendations)
            'activity_recommendation_service_to_scheduler': {
                'source_service': 'activity-service',
                'target_service': 'scheduler-service',
                'entity_type': 'activity_recommendation',
                'required_fields': ['centre_activity_id', 'patient_id', 'doctor_id'],
                'field_mappings': {
                    # Direct mappings (source_field: target_field)
                    'id': 'CentreActivityRecommendationID',  # Use the source ID as our unique identifier
                    'centre_activity_id': 'CentreActivityID',
                    'patient_id': 'PatientID',
                    'doctor_id': 'DoctorID',
                    'doctor_recommendation': 'DoctorRecommendation',
                    'doctor_remarks': 'DoctorRemarks',
                    'is_deleted': 'IsDeleted',
                    'created_date': 'CreatedDateTime',
                    'modified_date': 'UpdatedDateTime',
                    'created_by_id': 'CreatedById',
                    'modified_by_id': 'ModifiedById',
                },
                'field_transforms': {
                    # Special transformations (target_field: transform_function)
                    'DoctorID': lambda x: str(x) if x is not None else "",
                    'DoctorRecommendation': lambda x: self._convert_preference_value(x, "0"),  # Convert to -1, 0, or 1
                    'DoctorRemarks': lambda x: str(x) if x is not None else "",
                    'IsDeleted': lambda x: self._convert_boolean(x, "0"),
                    'CreatedDateTime': lambda x: self._parse_datetime(x) or datetime.now(),
                    'UpdatedDateTime': lambda x: self._parse_datetime(x) or datetime.now(),
                },
                'defaults': {
                    'IsDeleted': '0',
                    'DoctorRecommendation': '0',  # Neutral recommendation
                    'DoctorRemarks': '',
                    'CreatedDateTime': datetime.now(),
                    'UpdatedDateTime': datetime.now(),
                    'CreatedById': 'activity_service',
                    'ModifiedById': 'activity_service'
                },
                'ignored_fields': []
            },

            # Activity Service → Scheduler Service (Centre Activity)
            'centre_activity_service_to_scheduler': {
                'source_service': 'activity-service',
                'target_service': 'scheduler-service',
                'entity_type': 'centre_activity',
                'required_fields': ['id', 'activity_id'],
                'field_mappings': {
                    # Direct mappings (source_field: target_field)
                    'id': 'CentreActivityID',
                    'activity_id': 'ActivityID',
                    'is_deleted': 'IsDeleted',
                    'is_compulsory': 'IsCompulsory',
                    'is_fixed': 'IsFixed',
                    'is_group': 'IsGroup',
                    'start_date': 'StartDate',
                    'end_date': 'EndDate',
                    'min_duration': 'MinDuration',
                    'max_duration': 'MaxDuration',
                    'min_people_req': 'MinPeopleReq',
                    'fixed_time_slots': 'FixedTimeSlots',
                    'created_date': 'CreatedDateTime',
                    'modified_date': 'UpdatedDateTime',
                    'created_by_id': 'CreatedById',
                    'modified_by_id': 'ModifiedById',
                },
                'field_transforms': {
                    # Special transformations (target_field: transform_function)
                    'IsDeleted': lambda x: self._convert_boolean(x, "0"),
                    'IsCompulsory': lambda x: self._convert_boolean(x, "0"),
                    'IsFixed': lambda x: self._convert_boolean(x, "0"),
                    'IsGroup': lambda x: self._convert_boolean(x, "0"),
                    'StartDate': lambda x: self._parse_date(x),
                    'EndDate': lambda x: self._parse_date(x),
                    'MinDuration': lambda x: int(x) if x is not None else 30,
                    'MaxDuration': lambda x: int(x) if x is not None else 60,
                    'MinPeopleReq': lambda x: int(x) if x is not None else 1,
                    'FixedTimeSlots': lambda x: str(x) if x is not None else None,
                    'CreatedDateTime': lambda x: self._parse_datetime(x) or datetime.now(),
                    'UpdatedDateTime': lambda x: self._parse_datetime(x) or datetime.now(),
                    'CreatedById': lambda x: str(x) if x is not None else 'activity_service',
                    'ModifiedById': lambda x: str(x) if x is not None else 'activity_service',
                },
                'defaults': {
                    'IsDeleted': '0',
                    'IsCompulsory': '0',
                    'IsFixed': '0',
                    'IsGroup': '0',
                    'MinDuration': 30,
                    'MaxDuration': 60,
                    'MinPeopleReq': 1,
                    'CreatedDateTime': datetime.now(),
                    'UpdatedDateTime': datetime.now(),
                    'CreatedById': 'activity_service',
                    'ModifiedById': 'activity_service'
                },
                'ignored_fields': []
            },
            
            # Activity Service → Scheduler Service (Activity Exclusions)
            'activity_exclusion_service_to_scheduler': {
                'source_service': 'activity-service',
                'target_service': 'scheduler-service',
                'entity_type': 'activity_exclusion',
                'required_fields': ['patient_id', 'centre_activity_id'],
                'field_mappings': {
                    # Direct mappings (source_field: target_field)
                    'id': 'ActivityExclusionID',
                    'patient_id': 'PatientID',
                    'centre_activity_id': 'CentreActivityID',
                    'start_date': 'StartDateTime',
                    'end_date': 'EndDateTime', 
                    'exclusion_remarks': 'ExclusionRemarks',
                    'is_deleted': 'IsDeleted',
                    'created_date': 'CreatedDateTime',
                    'modified_date': 'UpdatedDateTime',
                    'created_by_id': 'CreatedById',
                    'modified_by_id': 'ModifiedById',
                },
                'field_transforms': {
                    # Special transformations (target_field: transform_function)
                    'StartDateTime': lambda x: self._parse_datetime(x) or datetime.now(),
                    'EndDateTime': lambda x: self._parse_datetime(x) or datetime.now(),
                    'ExclusionRemarks': lambda x: str(x) if x is not None else "",
                    'IsDeleted': lambda x: self._convert_boolean(x, "0"),
                    'CreatedDateTime': lambda x: self._parse_datetime(x) or datetime.now(),
                    'UpdatedDateTime': lambda x: self._parse_datetime(x) or datetime.now(),
                    'CreatedById': lambda x: str(x) if x is not None else 'activity_service',
                    'ModifiedById': lambda x: str(x) if x is not None else 'activity_service',
                },
                'defaults': {
                    'IsDeleted': '0',
                    'ExclusionRemarks': '',
                    'StartDateTime': datetime.now(),
                    'EndDateTime': datetime.now(),
                    'CreatedDateTime': datetime.now(),
                    'UpdatedDateTime': datetime.now(),
                    'CreatedById': 'activity_service',
                    'ModifiedById': 'activity_service'
                },
                'ignored_fields': []
            },
            # Activity Service → Scheduler Service (Adhoc Activities)
            "adhoc_service_to_scheduler": {
                "source_service": "activity-service",
                "target_service": "scheduler-service",
                "entity_type": "adhoc",
                "required_fields": ["id", "patient_id", "old_centre_activity_id", "new_centre_activity_id"],
                "field_mappings": {
                    # Direct mappings (source_field: target_field)
                    "id": "AdhocID",
                    "patient_id": "PatientID",
                    "old_centre_activity_id": "OldCentreActivityID",
                    "new_centre_activity_id": "NewCentreActivityID",
                    "start_date": "StartDate",
                    "end_date": "EndDate",
                    "status": "Status",
                    "is_deleted": "IsDeleted",
                    "created_date": "CreatedDateTime",
                    "modified_date": "UpdatedDateTime",
                    "created_by_id": "CreatedById",
                    "modified_by_id": "ModifiedById",
                },
                "field_transforms": {
                    # Special transformations (target_field: transform_function)
                    "StartDate": lambda x: self._parse_date(x),
                    "EndDate": lambda x: self._parse_date(x),
                    "Status": lambda x: str(x) if x is not None else "",
                    "IsDeleted": lambda x: self._convert_boolean(x, "0"),
                    "CreatedDateTime": lambda x: self._parse_datetime(x) or datetime.now(),
                    "UpdatedDateTime": lambda x: self._parse_datetime(x) or datetime.now(),
                    "CreatedById": lambda x: str(x) if x is not None else "activity_service",
                    "ModifiedById": lambda x: str(x) if x is not None else "activity_service",
                },
                "defaults": {
                    "IsDeleted": "0",
                    "CreatedDateTime": datetime.now(),
                    "UpdatedDateTime": datetime.now(),
                    "CreatedById": "activity_service",
                    "ModifiedById": "activity_service",
                },
                "ignored_fields": [],
            },
            # Template for future mappings - just copy and modify
            'template_mapping': {
                'source_service': 'source-service-name',
                'target_service': 'target-service-name',
                'entity_type': 'entity-type',
                'required_fields': ['id'],
                'field_mappings': {
                    # 'source_field': 'target_field'
                },
                'field_transforms': {
                    # 'target_field': transform_function
                },
                'defaults': {
                    # 'target_field': 'default_value'
                },
                'ignored_fields': []
            }
        }
    
    def map_data(self, source_data: Dict[str, Any], mapping_key: str, 
                 operation: str = 'create') -> Optional[Dict[str, Any]]:
        """
        Universal mapping function
        
        Args:
            source_data: Source data dictionary
            mapping_key: Key for mapping config (e.g., 'patient_service_to_scheduler')
            operation: 'create' or 'update'
            
        Returns:
            Mapped data dictionary or None if mapping fails
        """
        try:
            config = self.mapping_configs.get(mapping_key)
            if not config:
                logger.error(f"Mapping configuration not found: {mapping_key}")
                return None
            
            # Validate required fields for create operations
            if operation == 'create':
                if not self._validate_required_fields(source_data, config['required_fields']):
                    return None
            
            mapped_data = {}
            
            # Apply field mappings
            for source_field, target_field in config['field_mappings'].items():
                if source_field in source_data:
                    value = source_data[source_field]
                    
                    # Debug logging for timestamp fields
                    if target_field == 'UpdatedDateTime':
                        logger.debug(f"Processing timestamp: {source_field}={value} (type: {type(value)})")
                    
                    # Apply transformation if defined
                    if target_field in config.get('field_transforms', {}):
                        transform_func = config['field_transforms'][target_field]
                        try:
                            transformed_value = transform_func(value)
                            if target_field == 'UpdatedDateTime':
                                logger.debug(f"Transformed to: {transformed_value} (type: {type(transformed_value)})")
                            value = transformed_value
                        except Exception as e:
                            logger.warning(f"Transform failed for {target_field}: {e}")
                            continue
                    
                    # Only add non-None values for updates
                    if operation == 'update' and value is None:
                        if target_field == 'UpdatedDateTime':
                            logger.error(f"UpdatedDateTime is None after transform! Source: {source_field}={source_data.get(source_field)}")
                        continue
                        
                    mapped_data[target_field] = value
            
            # Apply defaults for create operations or when required fields are missing
            if operation == 'create':
                for target_field, default_value in config.get('defaults', {}).items():
                    if target_field not in mapped_data:
                        mapped_data[target_field] = default_value
            elif operation == 'update':
                # For updates, ONLY default ModifiedById if missing
                # UpdatedDateTime should ALWAYS come from source data
                critical_defaults = {'ModifiedById'}  # Removed UpdatedDateTime
                for target_field, default_value in config.get('defaults', {}).items():
                    if target_field in critical_defaults and target_field not in mapped_data:
                        mapped_data[target_field] = default_value
            
            if not mapped_data:
                logger.warning(f"No mappable fields found for {mapping_key}")
                return None
            
            self._log_mapping_success(config, source_data.get('id'), operation)
            return mapped_data
            
        except Exception as e:
            logger.error(f"Mapping failed for {mapping_key}: {str(e)}")
            logger.error(f"Source data: {source_data}")
            return None
    
    def get_mapping_info(self, mapping_key: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific mapping configuration"""
        config = self.mapping_configs.get(mapping_key)
        if not config:
            return None
            
        return {
            'source_service': config['source_service'],
            'target_service': config['target_service'],
            'entity_type': config['entity_type'],
            'mapped_fields': len(config['field_mappings']),
            'ignored_fields': len(config['ignored_fields']),
            'field_mappings': config['field_mappings'],
            'has_transforms': len(config.get('field_transforms', {})) > 0,
            'defaults': config.get('defaults', {})
        }
    
    def list_all_mappings(self) -> List[str]:
        """List all available mapping keys"""
        return [key for key in self.mapping_configs.keys() if key != 'template_mapping']
    
    def add_mapping_config(self, mapping_key: str, config: Dict[str, Any]):
        """Add a new mapping configuration"""
        self.mapping_configs[mapping_key] = config
        logger.info(f"Added new mapping configuration: {mapping_key}")
    
    def update_field_mapping(self, mapping_key: str, source_field: str, target_field: str):
        """Update a single field mapping - useful for column changes"""
        if mapping_key in self.mapping_configs:
            self.mapping_configs[mapping_key]['field_mappings'][source_field] = target_field
            logger.info(f"Updated {mapping_key}: {source_field} → {target_field}")
        else:
            logger.error(f"Mapping configuration not found: {mapping_key}")
    
    def remove_field_mapping(self, mapping_key: str, source_field: str):
        """Remove a field mapping"""
        if mapping_key in self.mapping_configs:
            config = self.mapping_configs[mapping_key]
            if source_field in config['field_mappings']:
                del config['field_mappings'][source_field]
                logger.info(f"Removed field mapping {mapping_key}: {source_field}")
    
    def add_ignored_field(self, mapping_key: str, field_name: str):
        """Add a field to ignore list"""
        if mapping_key in self.mapping_configs:
            ignored_fields = self.mapping_configs[mapping_key].get('ignored_fields', [])
            if field_name not in ignored_fields:
                ignored_fields.append(field_name)
                logger.info(f"Added ignored field {mapping_key}: {field_name}")
    
    # Helper methods
    def _validate_required_fields(self, data: Dict[str, Any], required_fields: List[str]) -> bool:
        """Validate required fields are present"""
        missing = [field for field in required_fields if field not in data or data[field] is None]
        if missing:
            logger.error(f"Missing required fields: {missing}")
            return False
        return True
    
    def _parse_datetime(self, datetime_str: Any) -> Optional[datetime]:
        """Parse datetime string consistently WITHOUT timezone conversion"""
        if not datetime_str:
            return None
        
        try:
            if isinstance(datetime_str, str):
                if 'T' in datetime_str:
                    # DON'T add timezone info - keep it as naive datetime
                    # Remove any existing timezone markers
                    clean_str = datetime_str.replace('Z', '').replace('+00:00', '')
                    return datetime.fromisoformat(clean_str)
                else:
                    # Try datetime format first
                    try:
                        return datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        # If that fails, try date-only format and add default time
                        try:
                            date_part = datetime.strptime(datetime_str, '%Y-%m-%d')
                            return date_part.replace(hour=0, minute=0, second=0)
                        except ValueError:
                            # Try ISO date format
                            clean_str = datetime_str.replace('Z', '').replace('+00:00', '')
                            return datetime.fromisoformat(clean_str)
            elif isinstance(datetime_str, datetime):
                return datetime_str
            return None
        except Exception as e:
            logger.warning(f"Failed to parse datetime: {datetime_str}, error: {str(e)}")
            return None
    
    def _parse_date(self, date_str: Any) -> Optional[date]:
        """Parse date string consistently"""
        if not date_str:
            return None
        
        try:
            from datetime import date
            if isinstance(date_str, str):
                # Handle ISO format dates
                if 'T' in date_str:
                    return datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
                else:
                    return datetime.strptime(date_str, '%Y-%m-%d').date()
            elif isinstance(date_str, datetime):
                return date_str.date()
            elif isinstance(date_str, date):
                return date_str
            return None
        except Exception as e:
            logger.warning(f"Failed to parse date: {date_str}, error: {str(e)}")
            return None
    
    def _convert_boolean(self, value: Any, default: str = "0") -> str:
        """Convert boolean values to string representation for database"""
        if value is None:
            return default
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, str):
            # Handle string boolean representations
            if value.lower() in ('true', '1', 'yes'):
                return "1"
            elif value.lower() in ('false', '0', 'no'):
                return "0"
        # For numeric values
        try:
            return "1" if int(value) else "0"
        except (ValueError, TypeError):
            return default
    
    def _convert_preference_value(self, value: Any, default: str = "0") -> str:
        """Convert preference values to string representation (-1, 0, 1)"""
        if value is None:
            return default
        
        # Handle numeric values directly
        if isinstance(value, (int, float)):
            if value < 0:
                return "-1"
            elif value > 0:
                return "1"
            else:
                return "0"
        
        # Handle string representations
        if isinstance(value, str):
            value_lower = value.lower().strip()
            if value_lower in ('dislike', 'negative', 'no', 'false', '-1'):
                return "-1"
            elif value_lower in ('like', 'positive', 'yes', 'true', '1'):
                return "1"
            elif value_lower in ('neutral', 'none', '0'):
                return "0"
            # Try to convert to int
            try:
                int_val = int(float(value))
                if int_val < 0:
                    return "-1"
                elif int_val > 0:
                    return "1"
                else:
                    return "0"
            except (ValueError, TypeError):
                pass
        
        # Handle boolean (True = 1, False = 0, no -1 from boolean)
        if isinstance(value, bool):
            return "1" if value else "0"
        
        return default
    
    def _log_mapping_success(self, config: Dict[str, Any], source_id: Any, operation: str):
        """Log successful mapping"""
        logger.info(f"✅ {operation.upper()} mapping: {config['source_service']} → "
                   f"{config['target_service']} ({config['entity_type']} ID: {source_id})")


# Global instance for easy import
mapper = MapperUtil()

# Convenience functions for the priority patient mapper
def map_patient_create(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map patient data for create operation"""
    return mapper.map_data(source_data, 'patient_service_to_scheduler', 'create')

def map_patient_update(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map patient data for update operation"""
    return mapper.map_data(source_data, 'patient_service_to_scheduler', 'update')

def get_patient_mapping_info() -> Optional[Dict[str, Any]]:
    """Get patient mapping information"""
    return mapper.get_mapping_info('patient_service_to_scheduler')

# Easy configuration functions for column changes
def update_patient_field_mapping(source_field: str, target_field: str):
    """Update patient field mapping when columns change"""
    mapper.update_field_mapping('patient_service_to_scheduler', source_field, target_field)

def add_patient_ignored_field(field_name: str):
    """Add field to patient ignore list"""
    mapper.add_ignored_field('patient_service_to_scheduler', field_name)

# Convenience functions for activity mapper
def map_activity_create(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map activity data for create operation"""
    return mapper.map_data(source_data, 'activity_service_to_scheduler', 'create')

def map_activity_update(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map activity data for update operation"""
    # Simply pass through to the mapper - no magic, no defaults
    return mapper.map_data(source_data, 'activity_service_to_scheduler', 'update')

def get_activity_mapping_info() -> Optional[Dict[str, Any]]:
    """Get activity mapping information"""
    return mapper.get_mapping_info('activity_service_to_scheduler')

# Easy configuration functions for column changes
def update_activity_field_mapping(source_field: str, target_field: str):
    """Update activity field mapping when columns change"""
    mapper.update_field_mapping('activity_service_to_scheduler', source_field, target_field)

def add_activity_ignored_field(field_name: str):
    """Add field to activity ignore list"""
    mapper.add_ignored_field('activity_service_to_scheduler', field_name)

# Convenience functions for patient medication mapper
def map_patient_medication_create(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map patient medication data for create operation"""
    return mapper.map_data(source_data, 'patient_medication_service_to_scheduler', 'create')

def map_patient_medication_update(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map patient medication data for update operation"""
    return mapper.map_data(source_data, 'patient_medication_service_to_scheduler', 'update')

def get_patient_medication_mapping_info() -> Optional[Dict[str, Any]]:
    """Get patient medication mapping information"""
    return mapper.get_mapping_info('patient_medication_service_to_scheduler')

# Easy configuration functions for column changes
def update_patient_medication_field_mapping(source_field: str, target_field: str):
    """Update patient medication field mapping when columns change"""
    mapper.update_field_mapping('patient_medication_service_to_scheduler', source_field, target_field)

def add_patient_medication_ignored_field(field_name: str):
    """Add field to patient medication ignore list"""
    mapper.add_ignored_field('patient_medication_service_to_scheduler', field_name)
    
def map_patient_allocation_create(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map patient allocation data for create operation"""
    return mapper.map_data(source_data, 'patient_allocation_service_to_scheduler', 'create')


def map_patient_allocation_update(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map patient allocation data for update operation"""
    return mapper.map_data(source_data, 'patient_allocation_service_to_scheduler', 'update')


def get_patient_allocation_mapping_info() -> Optional[Dict[str, Any]]:
    """Get patient allocation mapping information"""
    return mapper.get_mapping_info('patient_allocation_service_to_scheduler')

# Convenience functions for activity preference mapper
def map_activity_preference_create(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map activity preference data for create operation"""
    return mapper.map_data(source_data, 'activity_preference_service_to_scheduler', 'create')

def map_activity_preference_update(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map activity preference data for update operation"""
    return mapper.map_data(source_data, 'activity_preference_service_to_scheduler', 'update')

def get_activity_preference_mapping_info() -> Optional[Dict[str, Any]]:
    """Get activity preference mapping information"""
    return mapper.get_mapping_info('activity_preference_service_to_scheduler')

# Easy configuration functions for column changes
def update_activity_preference_field_mapping(source_field: str, target_field: str):
    """Update activity preference field mapping when columns change"""
    mapper.update_field_mapping('activity_preference_service_to_scheduler', source_field, target_field)

def add_activity_preference_ignored_field(field_name: str):
    """Add field to activity preference ignore list"""
    mapper.add_ignored_field('activity_preference_service_to_scheduler', field_name)

# Convenience functions for activity recommendation mapper
def map_activity_recommendation_create(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map activity recommendation data for create operation"""
    return mapper.map_data(source_data, 'activity_recommendation_service_to_scheduler', 'create')

def map_activity_recommendation_update(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map activity recommendation data for update operation"""
    return mapper.map_data(source_data, 'activity_recommendation_service_to_scheduler', 'update')

def get_activity_recommendation_mapping_info() -> Optional[Dict[str, Any]]:
    """Get activity recommendation mapping information"""
    return mapper.get_mapping_info('activity_recommendation_service_to_scheduler')

# Easy configuration functions for column changes
def update_activity_recommendation_field_mapping(source_field: str, target_field: str):
    """Update activity recommendation field mapping when columns change"""
    mapper.update_field_mapping('activity_recommendation_service_to_scheduler', source_field, target_field)

def add_activity_recommendation_ignored_field(field_name: str):
    """Add field to activity recommendation ignore list"""
    mapper.add_ignored_field('activity_recommendation_service_to_scheduler', field_name)

# Convenience functions for centre activity mapper
def map_centre_activity_create(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map centre activity data for create operation"""
    return mapper.map_data(source_data, 'centre_activity_service_to_scheduler', 'create')

def map_centre_activity_update(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map centre activity data for update operation"""
    return mapper.map_data(source_data, 'centre_activity_service_to_scheduler', 'update')

def get_centre_activity_mapping_info() -> Optional[Dict[str, Any]]:
    """Get centre activity mapping information"""
    return mapper.get_mapping_info('centre_activity_service_to_scheduler')

# Easy configuration functions for column changes
def update_centre_activity_field_mapping(source_field: str, target_field: str):
    """Update centre activity field mapping when columns change"""
    mapper.update_field_mapping('centre_activity_service_to_scheduler', source_field, target_field)

def add_centre_activity_ignored_field(field_name: str):
    """Add field to centre activity ignore list"""
    mapper.add_ignored_field('centre_activity_service_to_scheduler', field_name)

# Convenience functions for activity exclusion mapper
def map_activity_exclusion_create(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map activity exclusion data for create operation"""
    return mapper.map_data(source_data, 'activity_exclusion_service_to_scheduler', 'create')

def map_activity_exclusion_update(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map activity exclusion data for update operation"""
    return mapper.map_data(source_data, 'activity_exclusion_service_to_scheduler', 'update')

def get_activity_exclusion_mapping_info() -> Optional[Dict[str, Any]]:
    """Get activity exclusion mapping information"""
    return mapper.get_mapping_info('activity_exclusion_service_to_scheduler')

# Easy configuration functions for column changes
def update_activity_exclusion_field_mapping(source_field: str, target_field: str):
    """Update activity exclusion field mapping when columns change"""
    mapper.update_field_mapping('activity_exclusion_service_to_scheduler', source_field, target_field)

def add_activity_exclusion_ignored_field(field_name: str):
    """Add field to activity exclusion ignore list"""
    mapper.add_ignored_field("activity_exclusion_service_to_scheduler", field_name)


# Convenience functions for adhoc mapper
def map_adhoc_create(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map adhoc data for create operation"""
    return mapper.map_data(source_data, "adhoc_service_to_scheduler", "create")


def map_adhoc_update(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map adhoc data for update operation"""
    return mapper.map_data(source_data, "adhoc_service_to_scheduler", "update")


def get_adhoc_mapping_info() -> Optional[Dict[str, Any]]:
    """Get adhoc mapping information"""
    return mapper.get_mapping_info("adhoc_service_to_scheduler")


# Easy configuration functions for adhoc column changes
def update_adhoc_field_mapping(source_field: str, target_field: str):
    """Update adhoc field mapping when columns change"""
    mapper.update_field_mapping("adhoc_service_to_scheduler", source_field, target_field)


def add_adhoc_ignored_field(field_name: str):
    """Add field to adhoc ignore list"""
    mapper.add_ignored_field("adhoc_service_to_scheduler", field_name)
