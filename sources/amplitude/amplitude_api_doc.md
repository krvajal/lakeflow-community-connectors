# **Amplitude API Documentation**

## **Authorization**

Amplitude provides two authentication methods depending on the API being used:

### **Method 1: Basic Authentication (Export API)**

- **Preferred method for bulk event data export**
- **Authentication scheme**: HTTP Basic Authentication
- **Credentials**: API Key (username) + Secret Key (password)
- **Header format**: `Authorization: Basic <base64_encoded_credentials>`
  - Encode `{api_key}:{secret_key}` in Base64
  - Example: `Authorization: Basic YWhhbWwsdG9uQGFwaWdlZS5jb206bClwYXNzdzByZAo`

### **Method 2: API Key Authentication (User Profile API)**

- **Used for**: User Profile API, Cohort queries
- **Header format**: `Authorization: Api-Key <SECRET_KEY>`
- **Note**: Secret Key must be kept secure; recommended for server-side use only

### **Finding Credentials**

1. Navigate to your Amplitude project settings
2. Go to "Settings" → "Projects" → Select your project
3. API Key and Secret Key are displayed under the "General" tab
4. Each project has unique credentials

### **Rate Limits**

- **User Profile API**: 600 requests per minute per organization
- **Export API**: No explicit rate limit documented, but 4GB response size limit per request
- Exceeding limits returns HTTP 429; contact Amplitude Support for increases

**Example authenticated requests**:

```bash
# Export API (Basic Auth)
curl -X GET 'https://amplitude.com/api/2/export?start=20220101T00&end=20220101T23' \
  --header 'Authorization: Basic <base64_api_key:secret_key>'

# User Profile API (API Key Auth)
curl -X GET 'https://profile-api.amplitude.com/v1/userprofile?user_id=12345&get_amp_props=true' \
  --header 'Authorization: Api-Key <SECRET_KEY>'
```

## **Object List**

Amplitude's data model consists of **events** and **user profiles**. For connector purposes, we treat these as two primary object types:

| Object Type | Description | Discovery Method | Notes |
|------------|-------------|------------------|-------|
| `events` | Raw event data with properties | Static | All events are exported together via Export API |
| `user_profiles` | User properties, cohorts, computations | Dynamic per user | Retrieved individually per user_id or device_id |

### **Events Object**

- **Type**: Append-only event stream
- **Primary Key**: Combination of `uuid` (unique event ID) or `event_id` + `user_id` + `event_time`
- **Access**: Export API - bulk export by time range
- **Schema**: Dynamic - event properties vary by event type

### **User Profiles Object**

- **Type**: User dimension data
- **Primary Key**: `user_id` or `device_id`
- **Access**: User Profile API - individual user queries
- **Schema**: Dynamic - user properties configured per project

### **Object Discovery**

The object list is **static** for this connector:
1. **events** - Contains all event data across all event types
2. **user_profiles** - Contains user-level attributes and computations

**Note**: Amplitude does not provide an API to list all event types or enumerate users. Event types and user properties must be discovered by:
- Examining exported event data
- Querying known users via User Profile API
- Using Amplitude's Taxonomy (UI-based, no public API documented)

## **Object Schema**

### **Events Schema (Export API)**

The Export API returns events with the following schema. All fields are optional except where noted.

| Field Name | Type | Description |
|-----------|------|-------------|
| `uuid` | string (UUID) | Unique identifier for the event |
| `event_id` | integer | Sequential event ID within the project |
| `event_type` | string | Name of the event (e.g., "page_view", "button_click") |
| `event_time` | string (ISO 8601) | UTC timestamp when the event occurred on the client |
| `server_received_time` | string (ISO 8601) | UTC timestamp when Amplitude servers received the event |
| `server_upload_time` | string (ISO 8601) | UTC timestamp when event was uploaded to Amplitude |
| `client_event_time` | string (ISO 8601) | Client-side timestamp of the event |
| `client_upload_time` | string (ISO 8601) | Client-side timestamp when event was uploaded |
| `processed_time` | string (ISO 8601) | UTC timestamp when Amplitude processed the event |
| `user_id` | string | User identifier set by the client |
| `device_id` | string | Device identifier (anonymous ID) |
| `amplitude_id` | long | Amplitude's internal user ID |
| `session_id` | long | Session identifier |
| `event_properties` | object (JSON) | Custom properties specific to this event |
| `user_properties` | object (JSON) | User properties at the time of the event |
| `group_properties` | object (JSON) | Group properties (for group analytics) |
| `groups` | object (JSON) | Group types and values the user belongs to |
| `$insert_id` | string | Deduplication ID |
| `app` | integer | Project/app ID |
| `platform` | string | Platform (e.g., "iOS", "Android", "Web") |
| `os_name` | string | Operating system name |
| `os_version` | string | Operating system version |
| `device_type` | string | Device type classification |
| `device_family` | string | Device family (e.g., "iPhone", "Samsung") |
| `device_carrier` | string | Mobile carrier name |
| `version_name` | string | App version |
| `start_version` | string | App version when user first used the app |
| `language` | string | Device/browser language |
| `country` | string | Country (based on IP) |
| `region` | string | Region/state (based on IP) |
| `city` | string | City (based on IP) |
| `dma` | string | Designated Market Area (US only) |
| `location_lat` | float | Latitude (based on IP) |
| `location_lng` | float | Longitude (based on IP) |
| `ip_address` | string | IP address of the event |
| `library` | string | SDK library used (e.g., "amplitude-js/8.21.0") |
| `amplitude_attribution_ids` | string | Attribution campaign IDs |
| `paying` | boolean | Whether the user is a paying user |
| `sample_rate` | null | Sampling rate (typically null) |
| `data` | object (JSON) | Additional data blob |

**Dynamic Schema Discovery**:

Since event and user properties are custom per project, the connector should:
1. Export a sample of events via Export API
2. Inspect `event_properties` and `user_properties` fields
3. Extract unique keys across all events to determine the full schema
4. Map nested JSON properties to appropriate column types

### **User Profiles Schema (User Profile API)**

| Field Name | Type | Description |
|-----------|------|-------------|
| `user_id` | string | User identifier |
| `device_id` | string | Device identifier |
| `amp_props` | object (JSON) | User properties (key-value pairs) |
| `cohort_ids` | array of strings | List of cohort IDs the user belongs to |
| `recommendations` | array of objects | Recommendation results (if requested) |
| `computations` | object (JSON) | Computed user properties |
| `propensities` | array of objects | Prediction propensity scores |

**User Properties** (within `amp_props`):
- Schema is fully dynamic based on project configuration
- Common system properties: `library`, `first_used`, `last_used`
- Custom properties defined by the application
- Types: string, number, boolean, arrays

## **Get Object Primary Keys**

### **Events Primary Key**

The primary key for events is **composite** and depends on the use case:

1. **Recommended Primary Key**: `uuid`
   - Type: string (UUID format)
   - Globally unique across all events
   - Always present in Export API responses

2. **Alternative Primary Key**: Composite of `event_id` + `user_id`
   - `event_id`: integer, sequential within project
   - Note: `event_id` alone is not unique across users

3. **Deduplication Key**: `$insert_id`
   - Type: string
   - Optional field set by client for deduplication
   - Not guaranteed to be present

**Recommendation**: Use `uuid` as the primary key for the events table.

### **User Profiles Primary Key**

The primary key for user profiles is:

- **Primary Key**: `user_id`
  - Type: string
  - Required for User Profile API queries
  
- **Alternative Key**: `device_id`
  - Type: string
  - Used for anonymous users without a `user_id`

**Note**: Users can have both `user_id` and `device_id`. The connector should decide whether to:
- Use `user_id` as primary key (skipping anonymous users)
- Use `device_id` as fallback when `user_id` is null
- Create separate tables for identified vs anonymous users

## **Object's Ingestion Type**

### **Events**

- **Ingestion Type**: `append`
- **Rationale**:
  - Events are immutable once created
  - Export API provides event data by time range (`server_upload_time`)
  - No update or delete operations on historical events
  - Amplitude does not provide change feeds or updated events

**Incremental Strategy**:
- Use `server_upload_time` as cursor field
- Track last successfully synced time range
- Query next time range in subsequent syncs
- Consider 2-hour delay: data is available 2+ hours after `server_upload_time`

### **User Profiles**

- **Ingestion Type**: `snapshot` (with optional CDC via polling)
- **Rationale**:
  - User properties change over time
  - No timestamp field indicates when profile was last modified
  - User Profile API queries individual users, not bulk export
  - No native incremental update mechanism

**Snapshot Strategy**:
- Maintain list of known user_ids (extracted from events)
- Query User Profile API for each user
- Full refresh of all user profiles periodically

**Alternative CDC Strategy** (requires event data correlation):
- Track users from recent events
- Query User Profile API only for users with recent activity
- Compare with previously cached profiles to detect changes

**Handling Deletes**:
- Amplitude does not expose deleted users
- Snapshot mode naturally handles user deletions (users no longer appear)

## **Read API for Data Retrieval**

### **Export API - Bulk Event Data**

**HTTP Method**: GET  
**Endpoint**: `https://amplitude.com/api/2/export`  
**EU Region**: `https://analytics.eu.amplitude.com/api/2/export`

#### **Query Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `start` | string | Yes | First hour included in export. Format: `YYYYMMDDTHH` (e.g., `20220101T05`) |
| `end` | string | Yes | Last hour included in export. Format: `YYYYMMDDTHH` (e.g., `20220101T23`) |

#### **Request Example**

```bash
# Export events for January 1, 2022 (full day)
curl -X GET 'https://amplitude.com/api/2/export?start=20220101T00&end=20220101T23' \
  -u '{api_key}:{secret_key}'

# Export events for specific hour
curl -X GET 'https://amplitude.com/api/2/export?start=20220115T14&end=20220115T14' \
  --header 'Authorization: Basic <base64_encoded_credentials>'
```

#### **Response Format**

- **Content-Type**: `application/zip`
- **Structure**: Zipped archive containing one or more JSON files
- **File Format**: Newline-delimited JSON (NDJSON) - one event object per line
- **Note**: Multiple files per hour for high-volume projects

#### **Response Example** (unzipped file content)

```json
{"server_received_time":"2022-01-01T14:23:45.123Z","app":12345,"device_carrier":"Verizon","city":"San Francisco","user_id":"user_123","uuid":"550e8400-e29b-41d4-a716-446655440000","event_time":"2022-01-01T14:23:40.000Z","platform":"iOS","os_version":"15.1","amplitude_id":98765432,"processed_time":"2022-01-01T14:23:45.456Z","version_name":"2.5.0","ip_address":"192.0.2.1","paying":false,"dma":"San Francisco-Oakland-San Jose CA","group_properties":{},"user_properties":{"plan":"free","signup_date":"2021-12-01"},"client_upload_time":"2022-01-01T14:23:41.000Z","$insert_id":"unique_event_123","event_type":"button_clicked","library":"amplitude-ios/8.9.0","device_type":"iPhone 13","location_lng":-122.4194,"server_upload_time":"2022-01-01T14:23:42.000Z","event_id":123456789,"location_lat":37.7749,"os_name":"iOS","groups":{},"event_properties":{"button_name":"checkout","screen":"cart_page"},"device_id":"ABCD-1234-EFGH-5678","language":"en","country":"United States","region":"California","session_id":1641048220000,"device_family":"Apple iPhone","client_event_time":"2022-01-01T14:23:40.000Z"}
{"server_received_time":"2022-01-01T14:25:10.456Z","app":12345,"city":"New York","user_id":"user_456","uuid":"661f9511-f30c-52e5-b827-557766551111","event_time":"2022-01-01T14:25:05.000Z","platform":"Web","os_version":"Windows 10","amplitude_id":98765433,"processed_time":"2022-01-01T14:25:10.789Z","version_name":"1.0.0","ip_address":"198.51.100.1","paying":true,"user_properties":{"plan":"premium","signup_date":"2020-05-15"},"client_upload_time":"2022-01-01T14:25:06.000Z","event_type":"page_viewed","library":"amplitude-js/8.21.0","device_type":"Mac","server_upload_time":"2022-01-01T14:25:07.000Z","event_id":123456790,"os_name":"Mac OS","event_properties":{"page_url":"/products","referrer":"google"},"device_id":"WXYZ-9876-MNOP-5432","language":"en-US","country":"United States","region":"New York","session_id":1641048300000,"client_event_time":"2022-01-01T14:25:05.000Z"}
```

#### **Pagination Strategy**

The Export API uses **time-based pagination**:

1. Specify start and end hour (inclusive)
2. API returns all events for that time range
3. For large datasets, response may span multiple files within the ZIP
4. No cursor-based pagination within a single request
5. For incremental sync:
   - Track `last_synced_hour` (e.g., `20220101T23`)
   - Next sync: `start = last_synced_hour + 1 hour`
   - Continue until current time minus 2 hours (data availability delay)

#### **Incremental Read Strategy**

```
Initial Sync:
  start_time = project_start_date (e.g., 20210101T00)
  end_time = (current_time - 2 hours) rounded to hour
  
Subsequent Syncs:
  start_time = last_successful_sync_hour + 1
  end_time = (current_time - 2 hours) rounded to hour
  
Lookback Window:
  Recommended: 2-3 hours to account for late-arriving events
  Adjust start_time = last_sync_hour - lookback_hours
```

#### **Considerations**

- **Data Availability Delay**: 2+ hours after `server_upload_time`
- **Size Limit**: 4GB per request
  - If exceeded, returns HTTP 400
  - Solution: Request smaller time ranges (e.g., 1 hour instead of 24)
- **Max Time Range**: 365 days per request
- **Empty Response**: HTTP 404 if no data for time range
- **Historical Data**: Events before November 12, 2014 are grouped by day (not hour)

#### **Rate Limits**

- No explicit rate limit documented
- Recommended: Implement exponential backoff for 5xx errors
- Respect 4GB size limit by adjusting time range granularity

### **User Profile API - Individual User Data**

**HTTP Method**: GET  
**Endpoint**: `https://profile-api.amplitude.com/v1/userprofile`  
**EU Region**: Not supported

#### **Query Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_id` | string | Conditional | User ID to query. Required unless `device_id` is provided |
| `device_id` | string | Conditional | Device ID to query. Required unless `user_id` is provided |
| `get_amp_props` | boolean | No | Return user properties. Defaults to `false` |
| `get_cohort_ids` | boolean | No | Return cohort IDs user belongs to. Defaults to `false` |
| `get_computations` | boolean | No | Return all computed properties. Defaults to `false` |
| `comp_id` | string | No | Return specific computation by ID. Can be comma-separated for multiple |
| `get_recs` | boolean | No | Return recommendations. Defaults to `false` |
| `rec_id` | string | No | Recommendation ID to retrieve (required if `get_recs=true`) |
| `get_propensity` | boolean | No | Return prediction propensity scores. Defaults to `false` |
| `prediction_id` | string | No | Prediction ID (required if `get_propensity=true`) |
| `propensity_type` | string | No | Type of propensity: `score` or `pct` (percentile) |

#### **Request Examples**

```bash
# Get user properties
curl -X GET 'https://profile-api.amplitude.com/v1/userprofile?user_id=user_123&get_amp_props=true' \
  --header 'Authorization: Api-Key <SECRET_KEY>'

# Get user properties and cohort memberships
curl -X GET 'https://profile-api.amplitude.com/v1/userprofile?user_id=user_123&get_amp_props=true&get_cohort_ids=true' \
  --header 'Authorization: Api-Key <SECRET_KEY>'

# Get computations
curl -X GET 'https://profile-api.amplitude.com/v1/userprofile?user_id=user_123&get_computations=true' \
  --header 'Authorization: Api-Key <SECRET_KEY>'
```

#### **Response Example**

```json
{
  "userData": {
    "user_id": "user_123",
    "device_id": "ABCD-1234-EFGH-5678",
    "amp_props": {
      "library": "amplitude-ios/8.9.0",
      "first_used": "2021-12-01",
      "last_used": "2022-01-15",
      "plan": "premium",
      "signup_date": "2021-12-01",
      "total_purchases": 5,
      "is_beta_tester": true
    },
    "cohort_ids": ["cohort_abc123", "cohort_def456"],
    "recommendations": null
  }
}
```

#### **Pagination Strategy**

The User Profile API does **not support pagination**. It returns data for one user per request.

**Bulk User Profile Retrieval**:
1. Maintain list of user_ids (from events or external source)
2. Query User Profile API for each user sequentially
3. Implement rate limiting: max 600 requests/minute
4. Use batching: group 10-50 users per batch, add delays between batches

**Recommended Pattern**:
```
users_to_query = get_user_ids_from_events()
batch_size = 10
delay_between_batches = 1 second

for batch in chunk(users_to_query, batch_size):
    for user_id in batch:
        profile = get_user_profile(user_id)
        store_profile(profile)
    sleep(delay_between_batches)
```

#### **Handling Deleted/Missing Users**

- **Error Response**: `{"error":"User id and device id not seen before"}`
- **Handling**: Skip user and log as "not found"
- **Note**: Users without any events will return this error

#### **Rate Limits**

- **Limit**: 600 requests per minute per organization
- **Exceeding Limit**: HTTP 429 with error message
- **Handling**: Implement retry with exponential backoff
- **Recommendation**: Limit to 500 req/min to leave buffer

## **Field Type Mapping**

### **Amplitude Types to Connector Logical Types**

| Amplitude Field Type | JSON Type | Connector Logical Type | Notes |
|---------------------|-----------|----------------------|-------|
| UUID | string | string | Event unique identifier |
| Event ID | number | long/bigint | Sequential event ID |
| Amplitude ID | number | long/bigint | Internal user ID |
| Session ID | number | long/bigint | Unix timestamp (milliseconds) |
| Timestamp (ISO 8601) | string | timestamp | Parse to timestamp with timezone |
| User ID | string | string | External user identifier |
| Device ID | string | string | Device/anonymous identifier |
| Event Type | string | string | Event name |
| Event Properties | object | json/struct | Dynamic nested object |
| User Properties | object | json/struct | Dynamic nested object |
| Group Properties | object | json/struct | Dynamic nested object |
| Groups | object | json/struct | Dynamic nested object |
| Platform | string | string | Enum-like values |
| OS Name | string | string | Enum-like values |
| OS Version | string | string | Version string |
| Country | string | string | Country name |
| Region | string | string | State/region name |
| City | string | string | City name |
| DMA | string | string | Designated Market Area |
| Location Latitude | number | float/double | GPS coordinate |
| Location Longitude | number | float/double | GPS coordinate |
| IP Address | string | string | IPv4 or IPv6 |
| Paying | boolean | boolean | True/false |
| Cohort IDs | array | array<string> | List of cohort identifiers |
| Computations | object | json/struct | Key-value pairs |

### **Dynamic Property Mapping**

Since `event_properties` and `user_properties` are dynamic, the connector should:

1. **Sample events** to discover all possible keys
2. **Infer types** from values:
   - String → string
   - Number without decimal → integer/long
   - Number with decimal → float/double
   - Boolean → boolean
   - Object → json/struct
   - Array → array<type>
3. **Handle type conflicts**: Use string for fields with mixed types
4. **Nested objects**: Store as JSON string or flatten to dot notation

**Example Flattening**:
```json
{
  "event_properties": {
    "purchase": {
      "amount": 29.99,
      "currency": "USD"
    }
  }
}

// Flattened:
event_properties_purchase_amount: 29.99
event_properties_purchase_currency: "USD"
```

### **Special Behaviors and Constraints**

- **Null Handling**: Missing fields are treated as `null`, not empty string
- **Nested Limits**: `event_properties` and `user_properties` can be deeply nested
- **Array Types**: Arrays within properties can contain mixed types
- **Timestamps**: All timestamps are UTC; no timezone conversion needed
- **IP Geolocation**: `country`, `region`, `city`, `location_lat`, `location_lng` are derived from `ip_address`
- **Session ID**: Unix timestamp in milliseconds, represents session start time

## **Known Quirks & Edge Cases**

1. **2-Hour Data Delay**:
   - Event data is only available 2+ hours after `server_upload_time`
   - Real-time sync is not possible
   - Plan sync schedule accordingly

2. **No Incremental User Profile Updates**:
   - User Profile API has no "last modified" timestamp
   - Full user refresh required to detect property changes
   - High API usage for large user bases

3. **4GB Export Limit**:
   - High-volume hours may exceed 4GB limit
   - Returns HTTP 400 error
   - Solution: Request single hours or use S3 export for large datasets

4. **User Profile API Not Available in EU**:
   - EU customers cannot use User Profile API
   - Must rely solely on Export API for user data

5. **No User Enumeration**:
   - No API to list all users
   - Must extract user_ids from exported events
   - New users only discovered through events

6. **Device ID vs User ID**:
   - Users may have only device_id (anonymous)
   - Users may have only user_id (identified)
   - Users may have both (linked identity)
   - Connector must handle all three cases

7. **Event Schema Variability**:
   - Different event types have different properties
   - Schema inference requires sampling across time ranges
   - Schema may evolve as new events are added

8. **Rate Limiting on User Profile API**:
   - 600 requests/minute org-wide limit
   - Shared across all API usage
   - Can impact other Amplitude integrations

9. **Historical Data Granularity**:
   - Events before November 12, 2014 are grouped by day
   - Cannot query specific hours for old data

10. **ZIP File Handling**:
    - Export API returns compressed ZIP
    - Must decompress before parsing
    - Large ZIPs may require streaming decompression

11. **NDJSON Format**:
    - One JSON object per line (no commas between)
    - Cannot use standard JSON parsers
    - Must parse line-by-line

12. **Late-Arriving Events**:
    - Events may arrive hours or days after `event_time`
    - Use `server_upload_time` as cursor, not `event_time`
    - Implement lookback window (2-3 hours recommended)

## **Research Log**

| Source Type | URL | Accessed (UTC) | Confidence | What it confirmed |
|------------|-----|----------------|------------|-------------------|
| Official Docs | https://amplitude.com/docs/apis/analytics/export | 2026-01-09 | Highest | Export API endpoint, authentication, query parameters, response schema, rate limits |
| Official Docs | https://amplitude.com/docs/apis/analytics/user-profile | 2026-01-09 | Highest | User Profile API endpoint, authentication, query parameters, response schema, limitations |
| Official Docs | https://amplitude.com/docs/apis | 2026-01-09 | High | API overview, authentication methods, regional endpoints |
| Python Package | https://pypi.org/project/amplitude-data-wrapper/ | 2026-01-09 | Medium | Confirms Export API and User Profile API as primary data sources, pagination strategies |
| Community Discussion | https://community.amplitude.com | 2026-01-09 | Medium | Confirms 2-hour data delay, 4GB limit, no real-time export |

## **Sources and References**

- **Official Amplitude Export API Documentation** (highest confidence)
  - https://amplitude.com/docs/apis/analytics/export
  - Covers authentication, endpoints, query parameters, response format, rate limits

- **Official Amplitude User Profile API Documentation** (highest confidence)
  - https://amplitude.com/docs/apis/analytics/user-profile
  - Covers authentication, endpoints, query parameters, user properties, cohorts, computations

- **Official Amplitude API Credentials Guide** (highest confidence)
  - https://amplitude.com/docs/apis
  - How to find API keys and secret keys

- **Python Wrapper for Amplitude APIs** (medium confidence)
  - https://pypi.org/project/amplitude-data-wrapper/
  - https://github.com/navikt/amplitude-data-wrapper
  - Validates practical implementation patterns for Export and User Profile APIs

- **Amplitude Postman Collections** (high confidence)
  - https://www.postman.com/amplitude-dev-docs/amplitude-developers/
  - Example API requests and responses

When conflicts arise between sources, **official Amplitude documentation** is treated as the source of truth.

