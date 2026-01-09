#!/usr/bin/env python3
"""
Manual test script for Amplitude connector - no dependencies on pyspark or pytest.
Run: python sources/amplitude/test/manual_test.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Mock pyspark types for import
class MockType:
    def __init__(self, *args, **kwargs):
        pass

class MockStructType(MockType):
    def __init__(self, fields=None):
        self.fields = fields or []
    
    def fieldNames(self):
        return [f.name for f in self.fields]

class MockStructField:
    def __init__(self, name, dataType, nullable=True):
        self.name = name
        self.dataType = dataType
        self.nullable = nullable

# Inject mocks into sys.modules
sys.modules['pyspark'] = type(sys)('pyspark')
sys.modules['pyspark.sql'] = type(sys)('pyspark.sql')
sys.modules['pyspark.sql.types'] = type(sys)('pyspark.sql.types')

# Add mock types to pyspark.sql.types
types_module = sys.modules['pyspark.sql.types']
types_module.StructType = MockStructType
types_module.StructField = MockStructField
types_module.StringType = MockType
types_module.LongType = MockType
types_module.DoubleType = MockType
types_module.ArrayType = MockType
types_module.IntegerType = MockType

# Now import the connector
from sources.amplitude.amplitude import LakeflowConnect


def load_config(config_path):
    """Load JSON config file"""
    with open(config_path) as f:
        return json.load(f)


def test_initialization():
    """Test connector initialization"""
    print("\n" + "=" * 60)
    print("TEST: Initialization")
    print("=" * 60)
    
    parent_dir = Path(__file__).parent.parent
    config_path = parent_dir / "configs" / "dev_config.json"
    
    try:
        config = load_config(config_path)
        connector = LakeflowConnect(config)
        print("✅ Connector initialized successfully")
        print(f"   Region: {connector.region}")
        print(f"   Export URL: {connector.export_base_url}")
        return connector, True
    except Exception as e:
        print(f"❌ Initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return None, False


def test_list_tables(connector):
    """Test list_tables method"""
    print("\n" + "=" * 60)
    print("TEST: List Tables")
    print("=" * 60)
    
    try:
        tables = connector.list_tables()
        print(f"✅ Found {len(tables)} tables:")
        for table in tables:
            print(f"   - {table}")
        return True
    except Exception as e:
        print(f"❌ list_tables failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_get_table_schema(connector):
    """Test get_table_schema method"""
    print("\n" + "=" * 60)
    print("TEST: Get Table Schema")
    print("=" * 60)
    
    try:
        tables = connector.list_tables()
        for table in tables:
            schema = connector.get_table_schema(table, {})
            field_count = len(schema.fields) if hasattr(schema, 'fields') else 0
            print(f"✅ {table}: {field_count} fields")
            
            # Show first few fields
            if hasattr(schema, 'fields') and schema.fields:
                print(f"   Sample fields:")
                for field in schema.fields[:5]:
                    print(f"     - {field.name}")
        return True
    except Exception as e:
        print(f"❌ get_table_schema failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_read_table_metadata(connector):
    """Test read_table_metadata method"""
    print("\n" + "=" * 60)
    print("TEST: Read Table Metadata")
    print("=" * 60)
    
    try:
        tables = connector.list_tables()
        for table in tables:
            metadata = connector.read_table_metadata(table, {})
            print(f"✅ {table}:")
            print(f"   Primary keys: {metadata.get('primary_keys')}")
            print(f"   Cursor field: {metadata.get('cursor_field', 'N/A')}")
            print(f"   Ingestion type: {metadata.get('ingestion_type')}")
        return True
    except Exception as e:
        print(f"❌ read_table_metadata failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_read_events(connector):
    """Test reading events table"""
    print("\n" + "=" * 60)
    print("TEST: Read Events Table")
    print("=" * 60)
    
    try:
        print("Attempting to read events (this may take a moment)...")
        records_iter, offset = connector.read_table("events", start_offset={}, table_options={})
        
        print(f"✅ read_table returned successfully")
        print(f"   Offset: {offset}")
        
        # Try to read a few records
        print("\n   Reading sample records...")
        record_count = 0
        for i, record in enumerate(records_iter):
            if i >= 3:  # Just read first 3 records
                break
            record_count += 1
            print(f"\n   Record {i + 1}:")
            print(f"     UUID: {record.get('uuid', 'N/A')}")
            print(f"     Event Type: {record.get('event_type', 'N/A')}")
            print(f"     User ID: {record.get('user_id', 'N/A')}")
            print(f"     Device ID: {record.get('device_id', 'N/A')}")
            print(f"     Event Time: {record.get('event_time', 'N/A')}")
        
        if record_count == 0:
            print("   ⚠️  No records found (may be no data in time range)")
        else:
            print(f"\n   Successfully read {record_count} sample records")
        
        return True
    except Exception as e:
        print(f"❌ read_table (events) failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_read_user_profiles(connector):
    """Test reading user_profiles table"""
    print("\n" + "=" * 60)
    print("TEST: Read User Profiles Table")
    print("=" * 60)
    
    # Check if user_profiles is available
    if "user_profiles" not in connector.list_tables():
        print("⚠️  user_profiles not available in this region (EU)")
        return True
    
    try:
        # Load table config
        parent_dir = Path(__file__).parent.parent
        table_config_path = parent_dir / "configs" / "dev_table_config.json"
        
        try:
            table_config = load_config(table_config_path)
            table_options = table_config.get("user_profiles", {})
        except:
            print("⚠️  No table config found, using default test user")
            table_options = {"user_ids": "test_user_123"}
        
        print(f"Using table options: {table_options}")
        print("Attempting to read user profiles...")
        
        records_iter, offset = connector.read_table(
            "user_profiles",
            start_offset={},
            table_options=table_options
        )
        
        print(f"✅ read_table returned successfully")
        print(f"   Offset: {offset}")
        
        # Try to read records
        print("\n   Reading sample records...")
        record_count = 0
        for i, record in enumerate(records_iter):
            if i >= 2:  # Just read first 2 records
                break
            record_count += 1
            print(f"\n   Record {i + 1}:")
            print(f"     User ID: {record.get('user_id', 'N/A')}")
            print(f"     Device ID: {record.get('device_id', 'N/A')}")
            print(f"     Has amp_props: {record.get('amp_props') is not None}")
            print(f"     Cohort IDs: {record.get('cohort_ids', [])}")
        
        if record_count == 0:
            print("   ⚠️  No records found (user may not exist)")
        else:
            print(f"\n   Successfully read {record_count} sample records")
        
        return True
    except ValueError as e:
        if "user_ids" in str(e):
            print(f"⚠️  Expected error (user_ids required): {e}")
            return True
        else:
            print(f"❌ read_table (user_profiles) failed: {e}")
            return False
    except Exception as e:
        print(f"❌ read_table (user_profiles) failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all manual tests"""
    print("\n" + "=" * 70)
    print(" AMPLITUDE CONNECTOR MANUAL TEST SUITE")
    print("=" * 70)
    print(f"\nStarted at: {datetime.now().isoformat()}")
    
    results = []
    
    # Test 1: Initialization
    connector, success = test_initialization()
    results.append(("Initialization", success))
    
    if not connector:
        print("\n❌ Cannot continue without successful initialization")
        sys.exit(1)
    
    # Test 2: List Tables
    success = test_list_tables(connector)
    results.append(("List Tables", success))
    
    # Test 3: Get Table Schema
    success = test_get_table_schema(connector)
    results.append(("Get Table Schema", success))
    
    # Test 4: Read Table Metadata
    success = test_read_table_metadata(connector)
    results.append(("Read Table Metadata", success))
    
    # Test 5: Read Events
    success = test_read_events(connector)
    results.append(("Read Events", success))
    
    # Test 6: Read User Profiles
    success = test_read_user_profiles(connector)
    results.append(("Read User Profiles", success))
    
    # Print summary
    print("\n" + "=" * 70)
    print(" TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for test_name, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    print(f"Completed at: {datetime.now().isoformat()}")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print(f"\n❌ {total - passed} test(s) failed")
        sys.exit(1)


if __name__ == "__main__":
    main()

