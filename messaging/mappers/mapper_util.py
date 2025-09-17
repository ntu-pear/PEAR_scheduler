from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
import logging

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
                },
                'field_transforms': {
                    # Special transformations (target_field: transform_function)
                    'IsActive': lambda x: str(x) if x is not None else "1",
                    'IsDeleted': lambda x: str(x) if x is not None else "0", 
                    'UpdateBit': lambda x: str(x) if x is not None else "1",
                    'StartDate': lambda x: self._parse_datetime(x) or datetime.utcnow(),
                    'EndDate': lambda x: self._parse_datetime(x),
                },
                'defaults': {
                    'IsActive': '1',
                    'IsDeleted': '0',
                    'UpdateBit': '1'
                },
                'ignored_fields': [
                    # Source fields to ignore
                    'createdDate', 'modifiedDate', 'CreatedById', 'ModifiedById',
                    'nric', 'address', 'tempAddress', 'homeNo', 'handphoneNo',
                    'profilePicture', 'privacyLevel', 'preferredLanguageId',
                    'isApproved', 'isRespiteCare', 'autoGame', 'inActiveReason',
                    'terminationReason', 'inActiveDate', 'dateOfBirth', 'gender'
                ]
            },
            # Patient Prescription → Scheduler Service
            'patient_prescription_to_scheduler': {
                'source_service': 'patient-service',
                'target_service': 'scheduler-service',
                'entity_type': 'patient_prescription',
                # TODO: check required_fields. 
                'required_fields': ['PrescriptionListId', 'PatientId'],
                'field_mappings': {
                    'Id': 'Id',
                    'IsDeleted': 'IsDeleted',
                    'PatientId': 'PatientId',
                    'PrescriptionListId': 'PrescriptionListValue',
                    'Dosage': 'Dosage',
                    # TODO: add administer time in patient prescription table
                    'AdministerTime': 'AdministerTime',
                    'FrequencyPerDay': 'FrequencyPerDay',
                    'Instruction': 'Instruction',
                    'StartDate': 'StartDate',
                    'EndDate': 'EndDate',
                    'IsAfterMeal': 'IsAfterMeal',
                    'PrescriptionRemarks': 'PrescriptionRemarks',
                    # TODO: add IsChronic in patient prescription table and schema
                    #'IsChronic': 'IsChronic',
                    'Status': 'Status', # TODO: clarify if status is necessary because not in model
                    'CreatedDateTime': 'CreatedDateTime',
                    'UpdatedDateTime': 'UpdatedDateTime',
                    'CreatedById': 'CreatedById',
                    'ModifiedById': 'ModifiedById'
                },
                
                'field_transforms': {
                    # TODO: Check if it's 0 or 1
                    'IsDeleted': lambda x: str(x) if x is not None else "1", 
                    # TODO: get prescription list id mapping from prescription list table, use placeholder for now
                    'PrescriptionListValue': lambda x: "Aspirin",  # temporary value until mapping of prescription list is implemented
                    'StartDateTime': lambda x: self._parse_datetime(x) or datetime.utcnow(),
                    'EndDateTime': lambda x: self._parse_datetime(x),

                },
                'defaults': {
                    # TODO: Update AdministerTime and IsChronic here once patient prescription table in patient service is updated
                    'AdministerTime': "00:00", 
                    'IsChronic': "0"
                },
                'ignored_fields': [
                    # Source fields to ignore
                ]
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
                    
                    # Apply transformation if defined
                    if target_field in config.get('field_transforms', {}):
                        transform_func = config['field_transforms'][target_field]
                        try:
                            value = transform_func(value)
                        except Exception as e:
                            logger.warning(f"Transform failed for {target_field}: {e}")
                            continue
                    
                    # Only add non-None values for updates
                    if operation == 'update' and value is None:
                        continue
                        
                    mapped_data[target_field] = value
            
            # Apply defaults for create operations
            if operation == 'create':
                for target_field, default_value in config.get('defaults', {}).items():
                    if target_field not in mapped_data:
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
        """Parse datetime string consistently"""
        if not datetime_str:
            return None
        
        try:
            if isinstance(datetime_str, str):
                if 'T' in datetime_str:
                    return datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
                else:
                    return datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S')
            elif isinstance(datetime_str, datetime):
                return datetime_str
            return None
        except Exception as e:
            logger.warning(f"Failed to parse datetime: {datetime_str}, error: {str(e)}")
            return None
    
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


# Patient prescription mapping functions
def map_patient_prescription_create(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map patient prescription data for create operation for schema"""
    return mapper.map_data(source_data, 'patient_prescription_to_scheduler', 'create')

def map_patient_prescription_update(source_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map patient prescription data for update operation for schema"""
    return mapper.map_data(source_data, 'patient_prescription_to_scheduler', 'update')

def get_patient_prescription_mapping_info() -> Optional[Dict[str, Any]]:
    """Get patient prescription mapping information"""
    return mapper.get_mapping_info('patient_prescription_to_scheduler')

