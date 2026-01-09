# Amplitude Connector

A LakeFlow connector for extracting data from Amplitude Analytics using the Export API and User Profile API.

## Overview

This connector enables you to sync event data and user profiles from Amplitude to your data warehouse. It supports two primary data sources:

1. **Events** - Raw event data with full event properties and user context
2. **User Profiles** - User properties, cohort memberships, and computed properties

## Features

- ✅ **Incremental event sync** - Efficiently syncs new events using time-based cursor
- ✅ **Full event schema** - Preserves all event properties, user properties, and metadata
- ✅ **User profile sync** - Fetches user properties, cohorts, and computations
- ✅ **Rate limiting** - Automatic rate limit handling for User Profile API (600 req/min)
- ✅ **Regional support** - Supports both US and EU data regions
- ✅ **Automatic retries** - Built-in retry logic for transient failures

## Authentication

### Finding Your API Credentials

1. Log in to your Amplitude account
2. Navigate to **Settings** → **Projects**
3. Select your project
4. Under the **General** tab, you'll find:
   - **API Key** - Used for Export API authentication
   - **Secret Key** - Used for both Export API and User Profile API

> **Note on User Profile API Authentication**: The connector implements intelligent fallback authentication. It first attempts to use the `secret_key` (per official Amplitude documentation), and if that fails, automatically retries with the `api_key`. This ensures compatibility with all Amplitude account configurations.

### Required Credentials

- `api_key`: Your Amplitude project API key  
- `secret_key`: Your Amplitude project secret key

## Configuration

### Connection Options

```json
{
  "api_key": "YOUR_API_KEY",
  "secret_key": "YOUR_SECRET_KEY",
  "region": "US",
  "start_date": "2024-01-01"
}
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `api_key` | Yes | - | Amplitude API key |
| `secret_key` | Yes | - | Amplitude secret key |
| `region` | No | "US" | Data region: "US" or "EU" |
| `start_date` | No | 30 days ago | Start date for initial event sync (YYYY-MM-DD) |

### Regional Considerations

- **US Region**: Full support for both Export API and User Profile API
- **EU Region**: Only Export API is supported. User Profile API is not available in EU.

## Tables

### 1. Events

Raw event data from Amplitude's Export API.

**Ingestion Type**: `append` (incremental, time-based)  
**Primary Key**: `uuid`  
**Cursor Field**: `server_upload_time`

#### Schema

| Field | Type | Description |
|-------|------|-------------|
| `uuid` | string | Unique event identifier |
| `event_id` | long | Sequential event ID |
| `event_type` | string | Event name (e.g., "button_clicked") |
| `event_time` | string | ISO 8601 timestamp of event |
| `server_upload_time` | string | When event was uploaded to Amplitude |
| `user_id` | string | User identifier |
| `device_id` | string | Device/anonymous identifier |
| `amplitude_id` | long | Amplitude's internal user ID |
| `session_id` | long | Session identifier |
| `event_properties` | string | JSON string of event properties |
| `user_properties` | string | JSON string of user properties at event time |
| `platform` | string | Platform (iOS, Android, Web, etc.) |
| `os_name` | string | Operating system |
| `country` | string | Country based on IP |
| `city` | string | City based on IP |
| ... | ... | 30+ additional fields |

#### Example Query

```python
# Initial sync - fetches events from start_date
records, offset = connector.read_table("events", start_offset={}, table_options={})

# Subsequent sync - continues from last offset
records, offset = connector.read_table("events", start_offset=offset, table_options={})
```

#### Event Properties

Event properties are stored as JSON strings and can be parsed in your data warehouse:

```sql
-- BigQuery example
SELECT 
  event_type,
  JSON_EXTRACT_SCALAR(event_properties, '$.button_name') as button_name,
  JSON_EXTRACT_SCALAR(event_properties, '$.screen') as screen
FROM events
WHERE event_type = 'button_clicked'
```

#### Important Notes

- **Data Delay**: Events are available 2+ hours after `server_upload_time`
- **Batch Size**: Default 24 hours per batch (configurable via `BATCH_SIZE_HOURS`)
- **Size Limit**: Export API has 4GB limit per request. Reduce batch size if needed.

### 2. User Profiles

User profile data from Amplitude's User Profile API.

**Ingestion Type**: `snapshot`  
**Primary Key**: `user_id`  
**Region**: US only

#### Schema

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | string | User identifier |
| `device_id` | string | Device identifier |
| `amp_props` | string | JSON string of user properties |
| `cohort_ids` | array<string> | List of cohort IDs user belongs to |
| `recommendations` | string | JSON string of recommendations |
| `computations` | string | JSON string of computed properties |

#### Table Options

User profiles require explicit user IDs to fetch:

| Option | Required | Description |
|--------|----------|-------------|
| `user_ids` | Yes | Comma-separated list of user IDs to fetch |
| `get_cohort_ids` | No | Set to "true" to include cohort memberships |
| `get_computations` | No | Set to "true" to include computed properties |

#### Example Query

```python
# Fetch profiles for specific users
table_options = {
    "user_ids": "user_123,user_456,user_789",
    "get_cohort_ids": "true",
    "get_computations": "true"
}

records, offset = connector.read_table(
    "user_profiles",
    start_offset={},
    table_options=table_options
)
```

#### Extracting User IDs

Since the User Profile API requires explicit user IDs, you typically extract them from your events:

```sql
-- Get distinct user IDs from recent events
SELECT DISTINCT user_id
FROM events
WHERE server_upload_time >= CURRENT_TIMESTAMP - INTERVAL 7 DAY
  AND user_id IS NOT NULL
```

#### Rate Limiting

The User Profile API has a rate limit of **600 requests per minute** per organization. The connector automatically:
- Tracks request counts per 60-second window
- Pauses when limit is reached
- Resumes after the window resets

For large user bases, consider:
- Batching user IDs across multiple sync runs
- Syncing only active users (those with recent events)
- Running syncs during off-peak hours

## Usage Example

### Basic Setup

```python
from sources.amplitude.amplitude import LakeflowConnect

# Initialize connector
config = {
    "api_key": "abc123...",
    "secret_key": "xyz789...",
    "region": "US",
    "start_date": "2024-01-01"
}

connector = LakeflowConnect(config)

# List available tables
tables = connector.list_tables()
print(tables)  # ['events', 'user_profiles']
```

### Syncing Events

```python
# Get schema
schema = connector.get_table_schema("events", {})

# Get metadata
metadata = connector.read_table_metadata("events", {})
print(metadata)
# {
#   "primary_keys": ["uuid"],
#   "cursor_field": "server_upload_time",
#   "ingestion_type": "append"
# }

# Initial sync
records, offset = connector.read_table("events", start_offset={}, table_options={})

for record in records:
    print(record["event_type"], record["user_id"])

# Save offset for next sync
# offset = {"last_hour": "20240115T14"}

# Incremental sync
records, new_offset = connector.read_table("events", start_offset=offset, table_options={})
```

### Syncing User Profiles

```python
# Extract user IDs from events (or other source)
user_ids = ["user_123", "user_456", "user_789"]

# Configure table options
table_options = {
    "user_ids": ",".join(user_ids),
    "get_cohort_ids": "true",
    "get_computations": "true"
}

# Fetch profiles
records, offset = connector.read_table(
    "user_profiles",
    start_offset={},
    table_options=table_options
)

for profile in records:
    print(profile["user_id"], profile["cohort_ids"])
```

## Data Delay and Freshness

### Events

- **Availability**: 2+ hours after `server_upload_time`
- **Freshness**: Near real-time events appear with ~2 hour delay
- **Historical Data**: Events before November 12, 2014 are grouped by day (not hour)

### User Profiles

- **Availability**: Real-time (no delay)
- **Freshness**: Always returns current user state
- **Note**: No "last modified" timestamp; use snapshot mode

## Limitations and Considerations

1. **Export API Size Limit**: 4GB per request
   - If exceeded, reduce `BATCH_SIZE_HOURS` in the code
   - Default: 24 hours per batch
   - For high-volume projects, use 1-6 hours

2. **User Profile API - No Bulk Export**
   - Must provide explicit user IDs
   - 600 requests/minute limit
   - Not available in EU region
   - Best for syncing active users, not entire user base

3. **Dynamic Schemas**
   - Event properties vary by event type
   - User properties vary by project configuration
   - Properties stored as JSON strings; parse in warehouse

4. **No Delete Detection**
   - Events are immutable (append-only)
   - Deleted users not tracked by API
   - Use snapshot mode for user profiles

5. **Regional Limitations**
   - EU region: Export API only
   - US region: Both Export API and User Profile API

## Troubleshooting

### Authentication Errors

**Error**: `Authentication failed. Check your api_key and secret_key.`

**Solution**: Verify credentials in Amplitude project settings. Ensure you're using the correct project's keys.

### Rate Limit Exceeded

**Error**: `429 Too Many Requests`

**Solution**: The connector handles this automatically for User Profile API. If persistent, reduce the number of users per sync.

### 4GB Size Limit

**Error**: `Export request failed with 400. Time range ... may exceed 4GB limit.`

**Solution**: Reduce `BATCH_SIZE_HOURS` constant in `amplitude.py`:

```python
BATCH_SIZE_HOURS = 6  # Reduce from 24 to 6 hours
```

### No Data Returned

**Issue**: Empty results for recent hours

**Explanation**: 2-hour data delay. Events from last 2 hours are not yet available.

**Solution**: Wait 2+ hours after event occurrence, or adjust `EXPORT_DELAY_HOURS`.

### EU Region - User Profile API

**Error**: `User Profile API is not supported in EU region`

**Solution**: User Profile API is not available for EU customers. Use Export API only, which includes user properties at event time.

## Schema Evolution

Event and user properties can change over time as your tracking implementation evolves:

1. **New Properties**: Automatically included in JSON strings
2. **Removed Properties**: Historic data retains old properties
3. **Type Changes**: Stored as JSON strings; handle in warehouse

To update your warehouse schema:
1. Sample recent events
2. Parse `event_properties` and `user_properties`
3. Add new columns or update transformation logic

## API Documentation

For detailed API documentation, see:
- [amplitude_api_doc.md](./amplitude_api_doc.md) - Complete API reference
- [Amplitude Export API Docs](https://amplitude.com/docs/apis/analytics/export) - Official documentation
- [Amplitude User Profile API Docs](https://amplitude.com/docs/apis/analytics/user-profile) - Official documentation

## Support

For issues or questions:
1. Check the [API Documentation](./amplitude_api_doc.md)
2. Review [Amplitude's official documentation](https://amplitude.com/docs)
3. Verify your API credentials and project configuration
4. Check rate limits and quota usage in Amplitude dashboard

## Version History

- **v1.0.0** (2026-01-09) - Initial implementation
  - Export API integration for events
  - User Profile API integration for user profiles
  - Time-based incremental sync for events
  - Snapshot sync for user profiles
  - Rate limiting and retry logic
  - US and EU region support

