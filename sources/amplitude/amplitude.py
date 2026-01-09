import requests
import base64
import json
import zipfile
import io
from pyspark.sql.types import *
from datetime import datetime, timedelta
from typing import Iterator, Any
import time


class LakeflowConnect:
    """
    Amplitude connector implementing LakeflowConnect interface.
    
    Supports two tables:
    - events: Raw event data from Export API (append mode, time-based incremental)
    - user_profiles: User properties, cohorts, computations from User Profile API (snapshot mode)
    """
    
    # Constants
    EXPORT_DELAY_HOURS = 2  # Data available 2+ hours after server_upload_time
    MAX_TIME_RANGE_DAYS = 365  # Maximum time range per Export API request
    USER_PROFILE_RATE_LIMIT = 600  # Requests per minute
    BATCH_SIZE_HOURS = 24  # Number of hours to fetch in a single Export API call
    
    def __init__(self, options: dict[str, str]) -> None:
        """
        Initialize the Amplitude connector.
        
        Required options:
            - api_key: Amplitude API key (for Export API)
            - secret_key: Amplitude Secret key (for Export API and User Profile API)
        
        Optional options:
            - region: "US" (default) or "EU"
            - start_date: Start date for initial events sync (YYYY-MM-DD format)
                         Defaults to 30 days ago
        """
        # Validate required credentials
        if "api_key" not in options:
            raise ValueError("api_key is required")
        if "secret_key" not in options:
            raise ValueError("secret_key is required")
        
        self.api_key = options["api_key"]
        self.secret_key = options["secret_key"]
        
        # Region configuration
        self.region = options.get("region", "US").upper()
        
        # Set base URLs based on region
        if self.region == "EU":
            self.export_base_url = "https://analytics.eu.amplitude.com/api/2/export"
            # User Profile API not supported in EU
            self.user_profile_base_url = None
        else:
            self.export_base_url = "https://amplitude.com/api/2/export"
            self.user_profile_base_url = "https://profile-api.amplitude.com/v1/userprofile"
        
        # Authentication headers
        # Export API uses Basic Auth with api_key:secret_key
        auth_str = f"{self.api_key}:{self.secret_key}"
        self.export_auth_header = base64.b64encode(auth_str.encode()).decode()
        
        # User Profile API uses Api-Key header
        # Official Amplitude docs say to use secret_key, but some accounts may require api_key
        # We'll store both and implement fallback logic in the fetch method
        self.user_profile_auth_key = self.secret_key  # Primary: secret_key per official docs
        self.user_profile_auth_key_fallback = self.api_key  # Fallback: api_key for some accounts
        self.user_profile_headers = {
            "Authorization": f"Api-Key {self.user_profile_auth_key}",
            "Content-Type": "application/json"
        }
        
        # Historical data settings
        self.start_date = options.get("start_date")
        if self.start_date:
            try:
                datetime.strptime(self.start_date, "%Y-%m-%d")
            except ValueError:
                raise ValueError("start_date must be in YYYY-MM-DD format")
        
        # Rate limiting for User Profile API
        self.last_request_time = 0
        self.request_count = 0
        self.request_window_start = time.time()

    def list_tables(self) -> list[str]:
        """
        List available tables.
        
        Returns:
            - events: Raw event data from Export API
            - user_profiles: User profile data from User Profile API (US region only)
        """
        tables = ["events"]
        
        # user_profiles only available in US region
        if self.region == "US":
            tables.append("user_profiles")
        
        return tables

    def get_table_schema(
        self, table_name: str, table_options: dict[str, str]
    ) -> StructType:
        """
        Get the schema for the specified table.
        
        Args:
            table_name: Name of the table ("events" or "user_profiles")
            table_options: Additional options (not used for Amplitude)
        """
        if table_name not in self.list_tables():
            raise ValueError(
                f"Table '{table_name}' is not supported. "
                f"Supported tables: {', '.join(self.list_tables())}"
            )
        
        if table_name == "events":
            return self._get_events_schema()
        elif table_name == "user_profiles":
            return self._get_user_profiles_schema()
        else:
            raise ValueError(f"Unknown table: {table_name}")

    def _get_events_schema(self) -> StructType:
        """
        Schema for the events table based on Amplitude Export API response.
        
        All fields from the Export API are included. Nested event_properties,
        user_properties, group_properties, and groups are kept as JSON strings
        to preserve dynamic schemas.
        """
        return StructType([
            # Event identifiers
            StructField("uuid", StringType(), True),
            StructField("event_id", LongType(), True),
            StructField("event_type", StringType(), True),
            StructField("$insert_id", StringType(), True),
            
            # Timestamps
            StructField("event_time", StringType(), True),  # ISO 8601
            StructField("server_received_time", StringType(), True),
            StructField("server_upload_time", StringType(), True),
            StructField("client_event_time", StringType(), True),
            StructField("client_upload_time", StringType(), True),
            StructField("processed_time", StringType(), True),
            
            # User identifiers
            StructField("user_id", StringType(), True),
            StructField("device_id", StringType(), True),
            StructField("amplitude_id", LongType(), True),
            StructField("session_id", LongType(), True),
            
            # Dynamic properties (stored as JSON strings)
            StructField("event_properties", StringType(), True),
            StructField("user_properties", StringType(), True),
            StructField("group_properties", StringType(), True),
            StructField("groups", StringType(), True),
            
            # App/Platform info
            StructField("app", LongType(), True),
            StructField("platform", StringType(), True),
            StructField("os_name", StringType(), True),
            StructField("os_version", StringType(), True),
            StructField("device_type", StringType(), True),
            StructField("device_family", StringType(), True),
            StructField("device_carrier", StringType(), True),
            
            # Version info
            StructField("version_name", StringType(), True),
            StructField("start_version", StringType(), True),
            StructField("library", StringType(), True),
            
            # Location
            StructField("country", StringType(), True),
            StructField("region", StringType(), True),
            StructField("city", StringType(), True),
            StructField("dma", StringType(), True),
            StructField("location_lat", DoubleType(), True),
            StructField("location_lng", DoubleType(), True),
            StructField("ip_address", StringType(), True),
            
            # Other
            StructField("language", StringType(), True),
            StructField("paying", StringType(), True),  # Can be boolean or null
            StructField("amplitude_attribution_ids", StringType(), True),
            StructField("sample_rate", StringType(), True),
            StructField("data", StringType(), True),  # Additional data blob
        ])

    def _get_user_profiles_schema(self) -> StructType:
        """
        Schema for the user_profiles table from User Profile API.
        
        Includes user_id, device_id, and dynamic properties stored as JSON.
        """
        return StructType([
            StructField("user_id", StringType(), True),
            StructField("device_id", StringType(), True),
            StructField("amp_props", StringType(), True),  # JSON string of user properties
            StructField("cohort_ids", ArrayType(StringType()), True),
            StructField("recommendations", StringType(), True),  # JSON string
            StructField("computations", StringType(), True),  # JSON string
        ])

    def read_table_metadata(
        self, table_name: str, table_options: dict[str, str]
    ) -> dict:
        """
        Get metadata for the specified table.
        
        Args:
            table_name: Name of the table
            table_options: Additional options (not used)
        
        Returns:
            Metadata dict with primary_keys, cursor_field (if applicable), and ingestion_type
        """
        if table_name not in self.list_tables():
            raise ValueError(
                f"Table '{table_name}' is not supported. "
                f"Supported tables: {', '.join(self.list_tables())}"
            )
        
        if table_name == "events":
            return {
                "primary_keys": ["uuid"],
                "cursor_field": "server_upload_time",
                "ingestion_type": "append"
            }
        elif table_name == "user_profiles":
            return {
                "primary_keys": ["user_id"],
                "ingestion_type": "snapshot"
            }
        else:
            raise ValueError(f"Unknown table: {table_name}")

    def read_table(
        self, table_name: str, start_offset: dict, table_options: dict[str, str]
    ) -> tuple[Iterator[dict], dict]:
        """
        Read data from the specified table.
        
        Args:
            table_name: Name of the table to read
            start_offset: Starting offset for incremental reads
            table_options: Additional options for reading the table
                For user_profiles:
                    - user_ids: Comma-separated list of user IDs to fetch (required)
                    - get_cohort_ids: "true" to include cohort IDs
                    - get_computations: "true" to include computations
        
        Returns:
            Tuple of (iterator of records, end_offset)
        """
        if table_name not in self.list_tables():
            raise ValueError(
                f"Table '{table_name}' is not supported. "
                f"Supported tables: {', '.join(self.list_tables())}"
            )
        
        if table_name == "events":
            return self._read_events(start_offset, table_options)
        elif table_name == "user_profiles":
            return self._read_user_profiles(start_offset, table_options)
        else:
            raise ValueError(f"Unknown table: {table_name}")

    def _read_events(
        self, start_offset: dict, table_options: dict[str, str]
    ) -> tuple[Iterator[dict], dict]:
        """
        Read events from the Export API.
        
        The Export API returns events by hour ranges. We track progress using
        the last successfully synced hour.
        
        start_offset format:
            {
                "last_hour": "YYYYMMDDTHH"  # Last successfully synced hour
            }
            If None/empty, starts from start_date or 30 days ago
        """
        # Determine start time
        if start_offset and "last_hour" in start_offset:
            # Continue from last synced hour + 1
            last_hour_str = start_offset["last_hour"]
            last_hour = datetime.strptime(last_hour_str, "%Y%m%dT%H")
            start_time = last_hour + timedelta(hours=1)
        else:
            # Initial sync - start from configured start_date or 30 days ago
            if self.start_date:
                start_time = datetime.strptime(self.start_date, "%Y-%m-%d")
            else:
                start_time = datetime.now() - timedelta(days=30)
            start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # End time is current time minus EXPORT_DELAY_HOURS (data availability delay)
        end_time = datetime.now() - timedelta(hours=self.EXPORT_DELAY_HOURS)
        end_time = end_time.replace(minute=0, second=0, microsecond=0)
        
        # If start_time is after end_time, no new data available
        if start_time >= end_time:
            # Return empty iterator with same offset (signals no new data)
            return iter([]), start_offset if start_offset else {"last_hour": None}
        
        # Limit batch size to BATCH_SIZE_HOURS
        batch_end_time = min(
            start_time + timedelta(hours=self.BATCH_SIZE_HOURS - 1),
            end_time
        )
        
        # Format times for API
        start_str = start_time.strftime("%Y%m%dT%H")
        end_str = batch_end_time.strftime("%Y%m%dT%H")
        
        # Fetch events for this time range
        iterator = self._fetch_events_batch(start_str, end_str)
        
        # New offset is the end of this batch
        new_offset = {"last_hour": end_str}
        
        return iterator, new_offset

    def _fetch_events_batch(self, start_hour: str, end_hour: str) -> Iterator[dict]:
        """
        Fetch a batch of events from the Export API for the given hour range.
        
        Args:
            start_hour: Start hour in YYYYMMDDTHH format
            end_hour: End hour in YYYYMMDDTHH format
        
        Yields:
            Event records as dictionaries
        """
        url = f"{self.export_base_url}?start={start_hour}&end={end_hour}"
        headers = {
            "Authorization": f"Basic {self.export_auth_header}"
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=300)
            
            # Handle different response codes
            if response.status_code == 404:
                # No data for this time range
                return
            elif response.status_code == 400:
                # Likely exceeded 4GB limit
                raise ValueError(
                    f"Export request failed with 400. Time range {start_hour} to {end_hour} "
                    "may exceed 4GB limit. Try reducing BATCH_SIZE_HOURS."
                )
            elif response.status_code == 401:
                raise ValueError("Authentication failed. Check your api_key and secret_key.")
            elif response.status_code != 200:
                raise ValueError(
                    f"Export API request failed with status {response.status_code}: "
                    f"{response.text}"
                )
            
            # Response is a ZIP file containing NDJSON files
            zip_data = io.BytesIO(response.content)
            
            with zipfile.ZipFile(zip_data) as zip_file:
                # Process each file in the ZIP
                for filename in zip_file.namelist():
                    with zip_file.open(filename) as file:
                        # Each line is a JSON object
                        for line in file:
                            line = line.decode('utf-8').strip()
                            if line:
                                event = json.loads(line)
                                # Process event to convert nested objects to JSON strings
                                yield self._process_event(event)
        
        except requests.exceptions.Timeout:
            raise ValueError(
                f"Export API request timed out for range {start_hour} to {end_hour}. "
                "Try reducing BATCH_SIZE_HOURS."
            )
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Export API request failed: {str(e)}")

    def _process_event(self, event: dict) -> dict:
        """
        Process an event record from the Export API.
        
        Converts nested objects (event_properties, user_properties, etc.) to JSON strings
        to preserve dynamic schemas while keeping top-level fields as native types.
        """
        processed = {}
        
        # Copy all fields, converting nested dicts to JSON strings
        for key, value in event.items():
            if key in ["event_properties", "user_properties", "group_properties", "groups", "data"]:
                # Convert nested objects to JSON strings
                if value:
                    processed[key] = json.dumps(value)
                else:
                    processed[key] = None
            elif key == "paying":
                # paying can be boolean or null, convert to string for consistency
                processed[key] = str(value) if value is not None else None
            else:
                # Keep other fields as-is
                processed[key] = value
        
        return processed

    def _read_user_profiles(
        self, start_offset: dict, table_options: dict[str, str]
    ) -> tuple[Iterator[dict], dict]:
        """
        Read user profiles from the User Profile API.
        
        Since this is snapshot mode and the API doesn't support bulk export,
        the caller must provide a list of user_ids to fetch in table_options.
        
        table_options:
            - user_ids: Required. Comma-separated list of user IDs to fetch
            - get_cohort_ids: Optional. "true" to include cohort IDs
            - get_computations: Optional. "true" to include computations
        
        start_offset: Not used for snapshot mode, but tracks progress within batch
            {
                "user_index": <index of last processed user>
            }
        """
        if self.region == "EU":
            raise ValueError("User Profile API is not supported in EU region")
        
        # Validate required options
        if "user_ids" not in table_options:
            raise ValueError(
                "table_options must include 'user_ids' (comma-separated list of user IDs to fetch)"
            )
        
        # Parse user IDs - can be a list or comma-separated string
        user_ids_input = table_options["user_ids"]
        if isinstance(user_ids_input, list):
            user_ids = [str(uid).strip() for uid in user_ids_input if str(uid).strip()]
        elif isinstance(user_ids_input, str):
            user_ids = [uid.strip() for uid in user_ids_input.split(",") if uid.strip()]
        else:
            raise ValueError("user_ids must be a list or comma-separated string")
        
        if not user_ids:
            raise ValueError("user_ids cannot be empty")
        
        # Parse options
        get_cohort_ids = table_options.get("get_cohort_ids", "false").lower() == "true"
        get_computations = table_options.get("get_computations", "false").lower() == "true"
        
        # Determine starting index
        if start_offset and "user_index" in start_offset:
            start_index = start_offset["user_index"] + 1
        else:
            start_index = 0
        
        # If we've processed all users, return empty iterator with same offset
        if start_index >= len(user_ids):
            return iter([]), start_offset if start_offset else {"user_index": -1}
        
        # Fetch profiles for remaining users
        iterator = self._fetch_user_profiles(
            user_ids[start_index:],
            get_cohort_ids,
            get_computations
        )
        
        # New offset is the last user index
        new_offset = {"user_index": len(user_ids) - 1}
        
        return iterator, new_offset

    def _fetch_user_profiles(
        self,
        user_ids: list[str],
        get_cohort_ids: bool,
        get_computations: bool
    ) -> Iterator[dict]:
        """
        Fetch user profiles from the User Profile API.
        
        Implements rate limiting (600 requests/minute).
        
        Args:
            user_ids: List of user IDs to fetch
            get_cohort_ids: Whether to include cohort IDs
            get_computations: Whether to include computations
        
        Yields:
            User profile records as dictionaries
        """
        for user_id in user_ids:
            # Rate limiting: max 600 requests per minute
            self._enforce_rate_limit()
            
            # Build query parameters
            params = {
                "user_id": user_id,
                "get_amp_props": "true"
            }
            
            if get_cohort_ids:
                params["get_cohort_ids"] = "true"
            
            if get_computations:
                params["get_computations"] = "true"
            
            try:
                response = requests.get(
                    self.user_profile_base_url,
                    params=params,
                    headers=self.user_profile_headers,
                    timeout=30
                )
                
                # Handle response codes
                if response.status_code == 401:
                    error_detail = response.text
                    # Check if it's a feature access issue
                    if "Profile API feature" in error_detail or "does not have access" in error_detail:
                        # Profile API not available for this account - raise clear error
                        raise ValueError(
                            "Your Amplitude organization does not have access to the Profile API feature. "
                            "The Profile API is only available on certain Amplitude plans (typically Enterprise tier). "
                            "Please upgrade your Amplitude subscription or contact Amplitude support to enable this feature. "
                            "Alternatively, use only the 'events' table which is available on all plans."
                        )
                    # Check if Invalid Api-Key - try fallback with api_key instead of secret_key
                    if "Invalid Api-Key" in error_detail and not hasattr(self, '_user_profile_auth_tried_fallback'):
                        print("Info: Authentication with secret_key failed, trying api_key fallback...")
                        self._user_profile_auth_tried_fallback = True
                        # Update header to use api_key instead
                        self.user_profile_headers["Authorization"] = f"Api-Key {self.user_profile_auth_key_fallback}"
                        # Retry the request with api_key
                        response = requests.get(
                            self.user_profile_base_url,
                            params=params,
                            headers=self.user_profile_headers,
                            timeout=30
                        )
                        # Check the retry response
                        if response.status_code == 401:
                            retry_error = response.text
                            if "Profile API feature" in retry_error or "does not have access" in retry_error:
                                raise ValueError(
                                    "Your Amplitude organization does not have access to the Profile API feature. "
                                    "The Profile API is only available on certain Amplitude plans (typically Enterprise tier). "
                                    "Please upgrade your Amplitude subscription or contact Amplitude support to enable this feature."
                                )
                            raise ValueError(f"Authentication failed with both secret_key and api_key. Response: {retry_error}")
                    else:
                        raise ValueError(f"Authentication failed. Check your credentials. Response: {error_detail}")
                elif response.status_code == 429:
                    # Rate limit exceeded - wait and retry
                    time.sleep(60)  # Wait 1 minute
                    self._reset_rate_limit()
                    # Retry the request
                    response = requests.get(
                        self.user_profile_base_url,
                        params=params,
                        headers=self.user_profile_headers,
                        timeout=30
                    )
                
                if response.status_code == 200:
                    data = response.json()
                    user_data = data.get("userData", {})
                    
                    if user_data:
                        # Process the user profile
                        yield self._process_user_profile(user_data)
                else:
                    # Log error but continue with other users
                    error_msg = response.json().get("error", response.text)
                    if "not seen before" in error_msg:
                        # User doesn't exist, skip silently
                        continue
                    else:
                        print(f"Warning: Failed to fetch profile for user {user_id}: {error_msg}")
            
            except requests.exceptions.RequestException as e:
                print(f"Warning: Request failed for user {user_id}: {str(e)}")
                continue

    def _process_user_profile(self, user_data: dict) -> dict:
        """
        Process a user profile from the User Profile API response.
        
        Converts nested objects to JSON strings while keeping top-level fields native.
        """
        processed = {
            "user_id": user_data.get("user_id"),
            "device_id": user_data.get("device_id"),
            "cohort_ids": user_data.get("cohort_ids"),
        }
        
        # Convert amp_props to JSON string if present
        amp_props = user_data.get("amp_props")
        if amp_props:
            processed["amp_props"] = json.dumps(amp_props)
        else:
            processed["amp_props"] = None
        
        # Convert recommendations to JSON string if present
        recommendations = user_data.get("recommendations")
        if recommendations:
            processed["recommendations"] = json.dumps(recommendations)
        else:
            processed["recommendations"] = None
        
        # Convert computations/propensities to JSON string if present
        # Check for both computations and propensities keys
        if amp_props and any(k.startswith("computed-") for k in amp_props.keys()):
            # Computations are in amp_props, already handled
            processed["computations"] = None
        else:
            computations = user_data.get("computations")
            propensities = user_data.get("propensities")
            if computations or propensities:
                comp_data = {
                    "computations": computations,
                    "propensities": propensities
                }
                processed["computations"] = json.dumps(comp_data)
            else:
                processed["computations"] = None
        
        return processed

    def _enforce_rate_limit(self):
        """
        Enforce rate limit of 600 requests per minute for User Profile API.
        """
        current_time = time.time()
        
        # Reset counter if we're in a new 60-second window
        if current_time - self.request_window_start >= 60:
            self._reset_rate_limit()
        
        # If we've made 600 requests in this window, wait
        if self.request_count >= self.USER_PROFILE_RATE_LIMIT:
            sleep_time = 60 - (current_time - self.request_window_start)
            if sleep_time > 0:
                time.sleep(sleep_time)
            self._reset_rate_limit()
        
        # Increment request count
        self.request_count += 1

    def _reset_rate_limit(self):
        """Reset rate limit tracking."""
        self.request_window_start = time.time()
        self.request_count = 0

