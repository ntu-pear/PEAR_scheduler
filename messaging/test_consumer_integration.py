import sys
import os
import logging
from datetime import datetime

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_patient_mapper_integration():
    """Test that the new mapper works with patient consumer logic"""
    
    print("=" * 60)
    print("TESTING PATIENT CONSUMER WITH NEW SIMPLIFIED MAPPER")
    print("=" * 60)
    
    # Import the new mapper functions
    from messaging.mappers.mapper_util import map_patient_create, map_patient_update
    
    # Test data similar to what patient service would send
    test_patient_data = {
        'id': 123,
        'name': 'John Doe',
        'preferredName': 'Johnny',
        'nric': 'S1234567A',  # Should be ignored
        'address': '123 Main Street',  # Should be ignored
        'homeNo': '65-1234-5678',  # Should be ignored
        'handphoneNo': '65-9876-5432',  # Should be ignored
        'gender': 'M',  # Should be ignored
        'dateOfBirth': '1990-05-15',  # Should be ignored
        'isActive': True,
        'isDeleted': False,
        'updateBit': '1',
        'startDate': '2024-01-15 08:00:00',
        'endDate': None,
        'createdDate': '2024-01-01 10:00:00',  # Should be ignored
        'modifiedDate': '2024-01-15 10:00:00',  # Should be ignored
        'CreatedById': 'system',  # Should be ignored
        'ModifiedById': 'admin'  # Should be ignored
    }
    
    print("\n1. Testing CREATE mapping:")
    print("-" * 30)
    print(f"Source data keys: {list(test_patient_data.keys())}")
    
    # Test create mapping
    create_mapped = map_patient_create(test_patient_data)
    if create_mapped:
        print("✅ CREATE mapping successful!")
        print(f"Mapped data: {create_mapped}")
        
        # Test creating Pydantic schema (as done in consumer)
        try:
            from pear_schedule.schemas.ref_patient import RefPatientCreate
            schema = RefPatientCreate(**create_mapped)
            print("✅ RefPatientCreate schema creation successful!")
            print(f"Schema fields: {list(schema.dict().keys())}")
        except Exception as e:
            print(f"❌ RefPatientCreate schema creation failed: {e}")
    else:
        print("❌ CREATE mapping failed!")
    
    print("\n2. Testing UPDATE mapping:")
    print("-" * 30)
    
    # Test update data (partial data)
    test_update_data = {
        'id': 123,
        'name': 'John Doe Jr.',
        'preferredName': 'Johnny Jr.',
        'isActive': False,
        'nric': 'S1234567A',  # Should be ignored
        'modifiedDate': '2024-02-01 15:30:00'  # Should be ignored
    }
    
    print(f"Update data keys: {list(test_update_data.keys())}")
    
    update_mapped = map_patient_update(test_update_data)
    if update_mapped:
        print("✅ UPDATE mapping successful!")
        print(f"Mapped data: {update_mapped}")
        
        # Test creating Pydantic schema (as done in consumer)
        try:
            from pear_schedule.schemas.ref_patient import RefPatientUpdate
            schema = RefPatientUpdate(**update_mapped)
            print("✅ RefPatientUpdate schema creation successful!")
            print(f"Schema fields: {list(schema.dict().keys())}")
        except Exception as e:
            print(f"❌ RefPatientUpdate schema creation failed: {e}")
    else:
        print("❌ UPDATE mapping failed!")
    
    print("\n3. Testing field transformations:")
    print("-" * 30)
    
    # Test various data types
    transform_test_data = {
        'id': 456,
        'name': 'Jane Smith',
        'isActive': 1,  # Integer to string
        'isDeleted': 0,  # Integer to string
        'updateBit': True,  # Boolean to string
        'startDate': '2024-03-01T09:00:00Z',  # ISO format
        'endDate': '2024-12-31 23:59:59'  # Different format
    }
    
    transform_mapped = map_patient_create(transform_test_data)
    if transform_mapped:
        print("✅ Transform test successful!")
        print("Field transformations applied:")
        for key, value in transform_mapped.items():
            original = transform_test_data.get(key.lower()) or transform_test_data.get(key)
            print(f"  {key}: {original} → {value} (type: {type(value).__name__})")
    else:
        print("❌ Transform test failed!")

def test_error_handling():
    """Test error handling scenarios"""
    
    print("\n4. Testing error handling:")
    print("-" * 30)
    
    from messaging.mappers.mapper_util import map_patient_create, map_patient_update
    
    # Test missing required fields
    print("Testing missing required fields...")
    incomplete_data = {'name': 'Test User'}  # Missing 'id'
    result = map_patient_create(incomplete_data)
    if result is None:
        print("✅ Correctly rejected incomplete data")
    else:
        print("❌ Should have rejected incomplete data")
    
    # Test empty data
    print("Testing empty data...")
    empty_result = map_patient_update({})
    if empty_result is None:
        print("✅ Correctly handled empty update data")
    else:
        print("❌ Should have handled empty update data")
    
    # Test with None values
    print("Testing None values...")
    none_data = {
        'id': 789,
        'name': 'Test User',
        'preferredName': None,
        'isActive': None,
        'startDate': None
    }
    none_result = map_patient_create(none_data)
    if none_result:
        print("✅ Handled None values correctly")
        print(f"Result: {none_result}")
    else:
        print("❌ Failed to handle None values")

def test_mapping_info():
    """Test mapping configuration info"""
    
    print("\n5. Testing mapping info:")
    print("-" * 30)
    
    from messaging.mappers.mapper_util import get_patient_mapping_info, mapper
    
    # Get patient mapping info
    info = get_patient_mapping_info()
    if info:
        print("✅ Mapping info retrieved successfully!")
        print(f"Source service: {info['source_service']}")
        print(f"Target service: {info['target_service']}")
        print(f"Entity type: {info['entity_type']}")
        print(f"Mapped fields: {info['mapped_fields']}")
        print(f"Field mappings: {list(info['field_mappings'].keys())}")
    else:
        print("❌ Failed to get mapping info")
    
    # List all mappings
    all_mappings = mapper.list_all_mappings()
    print(f"Available mappings: {all_mappings}")

if __name__ == "__main__":
    try:
        test_patient_mapper_integration()
        test_error_handling()
        test_mapping_info()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS COMPLETED!")
        print("The updated patient_consumer.py should work with the new mapper.")
        print("=" * 60)
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure you're running this from the correct directory")
        print("and that all required modules are available.")
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
