"""
Simplified Crawler Scheduler API
- Multi-user support with individual configurations
- Space-based website retrieval
- Configurable scheduling intervals
- Status monitoring and reporting
- Production and Debug logging modes
"""

import os
import logging
import time
import sys
import json
import requests
import threading
from typing import List, Dict, Set, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import argparse

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from dotenv import load_dotenv

# ANSI color codes for console output
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Parse command line arguments for log mode
parser = argparse.ArgumentParser(description="Crawler API Server")
parser.add_argument("--log-mode", choices=["debug", "production"], default=None, 
                   help="Logging mode: debug for verbose logs, production for minimal logs")
args, _ = parser.parse_known_args()

# Load environment variables
load_dotenv()

# Determine log mode from command line args or environment variable
LOG_MODE = args.log_mode or os.getenv("LOG_MODE", "production").lower()

# Configure logging based on mode
log_level = logging.DEBUG if LOG_MODE == "debug" else logging.WARNING

# Set up console handler with appropriate level
console_handler = logging.StreamHandler()
console_handler.setLevel(log_level)
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

# Special handler just for summary logs in production mode
if LOG_MODE == "production":
    summary_handler = logging.StreamHandler()
    summary_handler.setLevel(logging.INFO)
    summary_handler.addFilter(lambda record: "CRAWLER STATUS SUMMARY" in record.getMessage() or "Startup" in record.getMessage())
    summary_handler.setFormatter(logging.Formatter("%(message)s"))
    handlers = [console_handler, summary_handler]
else:
    handlers = [console_handler]

# Configure root logger
logging.basicConfig(
    level=logging.DEBUG if LOG_MODE == "debug" else logging.INFO,
    handlers=handlers
)

logger = logging.getLogger(__name__)
logger.info(f"{BOLD}{GREEN}Starting crawler in {LOG_MODE.upper()} mode{RESET}")

# ------------------- Data Classes -------------------
@dataclass
class AppConfig:
    """Application configuration container."""
    api_key: str
    base_url: str
    schedule_minutes: int
    website_filter: Set[str]
    status_check_interval: int = 60  # Seconds between status checks
    space_id: Optional[str] = None
    space_name: Optional[str] = None
    crawl_all_space_websites: bool = False

@dataclass
class JobStatus:
    """Track the status of crawl jobs."""
    site_id: str
    site_name: str
    run_id: Optional[str] = None
    status: str = "idle"  # idle, running, queued, complete, failed, etc.
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None
    last_update: Optional[datetime] = None
    last_successful_crawl: Optional[datetime] = None

class ConfigModel(BaseModel):
    """Model for setting/updating config via API."""
    api_key: str = Field(..., description="Must start with 'inp_'")
    base_url: str = Field(..., description="Remote crawler API base URL")
    schedule_minutes: int = Field(5, description="How often to run the crawl in minutes")
    website_filter: List[str] = Field([], description="List of website filters")
    status_check_interval: int = Field(60, description="Seconds between status checks")
    space_id: Optional[str] = Field(None, description="ID of the space to use")
    space_name: Optional[str] = Field(None, description="Name of the space to use (alternative to space_id)")
    crawl_all_space_websites: bool = Field(False, description="Whether to crawl all websites in the space")

# ------------------- Global State -------------------
# Stores configuration and status for each user
USER_CONFIGS: Dict[str, AppConfig] = {}
USER_API_CLIENTS: Dict[str, Any] = {}
USER_WEBSITES: Dict[str, List[Dict]] = {}
USER_JOBS_CREATED: Dict[str, bool] = {}
USER_JOB_STATUS: Dict[str, Dict[str, JobStatus]] = {}

# ------------------- Status Summary Generation -------------------
def generate_user_status_summary():
    """Generate a concise summary of all users' crawl job statuses for logs"""
    if LOG_MODE != "production":
        return {}  # Return empty dict instead of None
    
    # Add a timestamp to limit how often we generate summaries
    last_summary_time = getattr(generate_user_status_summary, "last_summary_time", datetime.min)
    current_time = datetime.now()
    
    # Don't generate more than one summary per minute (except for explicit calls)
    was_called_from_endpoint = getattr(generate_user_status_summary, "called_from_endpoint", False)
    time_since_last = (current_time - last_summary_time).total_seconds()
    
    if not was_called_from_endpoint and time_since_last < 60:
        return {}
        
    # Reset the flag
    generate_user_status_summary.called_from_endpoint = False
    generate_user_status_summary.last_summary_time = current_time
    
    if not USER_CONFIGS:
        logger.info(f"{BOLD}{YELLOW}No users configured yet{RESET}")
        return {"status": "no_users", "message": "No users configured yet"}
        
    summary_lines = [f"\n{BOLD}{CYAN}===== CRAWLER STATUS SUMMARY ====={RESET}"]
    summary_lines.append(f"{BOLD}{CYAN}Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    
    # Build structured summary data for API response alongside text summary
    summary_data = {
        "timestamp": current_time.isoformat(),
        "users": {}
    }
    
    # Group users by base user_id (before _space suffix)
    user_groups = {}
    for user_id, config in USER_CONFIGS.items():
        # Handle "user_spaceN" format by extracting base user id
        if "_space" in user_id:
            base_user_id = user_id.split("_space")[0]
        else:
            base_user_id = user_id
            
        if base_user_id not in user_groups:
            user_groups[base_user_id] = []
        user_groups[base_user_id].append((user_id, config))
    
    # Process each base user
    for base_user_id, user_configs in sorted(user_groups.items()):
        for user_id, config in user_configs:
            # Get space info
            space_name = config.space_name or config.space_id or "Unknown Space"
            
            # Only show space name for users with multiple spaces
            if len(user_configs) > 1:
                user_display = f"{base_user_id} - Space: {space_name}"
            else:
                user_display = base_user_id
            
            # Initialize user data in structured summary
            if base_user_id not in summary_data["users"]:
                summary_data["users"][base_user_id] = {}
            
            user_data = {
                "space_name": space_name,
                "space_id": config.space_id,
                "website_count": 0,
                "running_count": 0,
                "completed_count": 0,
                "failed_count": 0,
                "latest_crawl": None,
                "failed_sites": [],
                "running_sites": []
            }
            
            if user_id not in USER_JOB_STATUS or not USER_JOB_STATUS[user_id]:
                summary_lines.append(f"{BOLD}{YELLOW}User: {user_display} - No jobs running{RESET}")
                user_data["status"] = "no_jobs"
                summary_data["users"][base_user_id][space_name] = user_data
                continue
                
            # Count jobs by status
            running_count = 0
            failed_count = 0
            completed_count = 0
            website_count = len(USER_JOB_STATUS[user_id])
            user_data["website_count"] = website_count
            
            # Check for actively running jobs (within last 2 minutes)
            active_threshold = current_time - timedelta(minutes=2)
            
            for site_id, status in USER_JOB_STATUS[user_id].items():
                # Consider both "running" and "queued" as active jobs
                if (status.status in ("running", "queued")) and status.last_update and status.last_update > active_threshold:
                    running_count += 1
                elif status.status in ("failed", "cancelled"):
                    failed_count += 1
                elif status.status == "complete":
                    completed_count += 1
            
            user_data["running_count"] = running_count
            user_data["completed_count"] = completed_count
            user_data["failed_count"] = failed_count
            
            # Determine user's overall status color
            if failed_count > 0:
                user_color = RED
                user_data["status"] = "has_failures"
            elif running_count > 0:
                user_color = GREEN
                user_data["status"] = "running"
            else:
                user_color = BLUE
                user_data["status"] = "idle"
                
            summary_lines.append(f"{BOLD}{user_color}User: {user_display}{RESET}")
            summary_lines.append(f"  Websites: {website_count} | Running: {running_count} | Completed: {completed_count} | Failed: {failed_count}")
            
            # Add last successful crawl info
            latest_crawl = None
            for site_id, status in USER_JOB_STATUS[user_id].items():
                if status.last_successful_crawl:
                    if not latest_crawl or status.last_successful_crawl > latest_crawl:
                        latest_crawl = status.last_successful_crawl
            
            if latest_crawl:
                time_since = (current_time - latest_crawl).total_seconds()
                user_data["latest_crawl"] = latest_crawl.isoformat()
                user_data["latest_crawl_seconds_ago"] = int(time_since)
                
                if time_since < 60:
                    time_display = f"{int(time_since)}s ago"
                elif time_since < 3600:
                    time_display = f"{int(time_since // 60)}m ago"
                else:
                    time_display = f"{int(time_since // 3600)}h {int((time_since % 3600) // 60)}m ago"
                summary_lines.append(f"  Last successful crawl: {time_display}")
            
            # Show details of any failed jobs
            if failed_count > 0:
                summary_lines.append(f"  {BOLD}{RED}Failed Jobs:{RESET}")
                failed_sites = []
                for site_id, status in USER_JOB_STATUS[user_id].items():
                    if status.status in ("failed", "cancelled"):
                        error = status.error_message or "Unknown error"
                        failed_sites.append((status.site_name, error))
                
                # Remove duplicate errors
                seen = set()
                unique_failures = []
                for site_name, error in failed_sites:
                    if site_name not in seen:
                        seen.add(site_name)
                        unique_failures.append((site_name, error))
                        
                for site_name, error in unique_failures:
                    summary_lines.append(f"    - {site_name}: {error}")
                    user_data["failed_sites"].append({
                        "site_name": site_name,
                        "error": error
                    })
                    
            # Show currently running jobs
            if running_count > 0:
                summary_lines.append(f"  {BOLD}{GREEN}Running Jobs:{RESET}")
                for site_id, status in USER_JOB_STATUS[user_id].items():
                    if (status.status in ("running", "queued")) and status.last_update and status.last_update > active_threshold:
                        duration = "Unknown"
                        duration_seconds = None
                        if status.start_time:
                            duration_secs = (current_time - status.start_time).total_seconds()
                            duration_seconds = int(duration_secs)
                            duration = f"{int(duration_secs // 60)}m {int(duration_secs % 60)}s"
                        # Show status (queued or running)
                        status_display = f"({status.status} for {duration})"
                        summary_lines.append(f"    - {status.site_name} {status_display}")
                        
                        user_data["running_sites"].append({
                            "site_name": status.site_name, 
                            "status": status.status,
                            "duration_seconds": duration_seconds,
                            "duration_display": duration,
                            "run_id": status.run_id
                        })
            
            # Add this user's data to the structured summary
            summary_data["users"][base_user_id][space_name] = user_data
    
    summary_lines.append(f"{BOLD}{CYAN}===============================\n{RESET}")
    
    # Log this with special formatting that will always appear in console
    summary_message = "\n".join(summary_lines)
    logger.info(summary_message)
    
    # Return the structured summary data for API response
    return summary_data

# Add the function to APScheduler for periodic status updates
def setup_status_logger(scheduler):
    """Set up periodic status logging for production mode"""
    if LOG_MODE == "production":
        logger.info(f"{GREEN}Setting up periodic status logger (every 5 minutes){RESET}")
        scheduler.add_job(
            generate_user_status_summary,
            "interval",
            minutes=5,
            id="status_summary_logger",
            replace_existing=True
        )
        generate_user_status_summary()  # Run immediately

# ------------------- Crawler Client -------------------
class CrawlerAPIClient:
    """Handles API communication with enhanced error handling"""
    def __init__(self, config: AppConfig):
        self.config = config
        self.session = requests.Session()

        # Partial mask for logging
        masked = self.config.api_key[:10] + "..." if len(self.config.api_key) > 10 else self.config.api_key
        logger.info(f"{BLUE}Using API key='api-key': {masked}{RESET}")

        self.session.headers.update({
            "api-key": self.config.api_key,
            "accept": "application/json"
        })
        self.session.mount('https://', requests.adapters.HTTPAdapter(
            max_retries=3,
            pool_maxsize=10
        ))

    def _handle_api_error(self, response: requests.Response):
        try:
            error_data = response.json()
            intric_error_code = error_data.get("intric_error_code")
            
            # Handle "already queued" or rate limiting error
            if response.status_code == 429 and intric_error_code == 9021:
                logger.warning(f"{YELLOW}Website already has a crawl in queue/progress (code 9021){RESET}")
                # Don't raise an exception - return a special response instead
                return {"status": "queued", "intric_error_code": 9021, "already_queued": True}
                
        except ValueError:
            error_data = {"detail": "Unknown error - non-JSON response"}

        error_msg = f"API Error {response.status_code}: {error_data.get('detail', 'Unknown error')}"
        logger.error(f"{RED}{error_msg}{RESET}")
        
        if LOG_MODE == "debug":
            logger.debug(f"Error response headers: {response.headers}")
            logger.debug(f"Error response content: {response.text[:1000]}")
        
        response.raise_for_status()

    def _normalize_url(self, url: Optional[str]) -> str:
        if not url:
            return ""
        # Convert to lowercase, strip whitespace, remove trailing slashes
        normalized = url.lower().strip().rstrip('/')
        
        # Handle fragment identifiers
        if '#' in normalized:
            normalized = normalized.split('#')[0]
        
        # Handle query parameters
        if '?' in normalized:
            normalized = normalized.split('?')[0]
            
        return normalized

    def get_spaces(self) -> List[Dict]:
        """Fetch all spaces the user can access."""
        try:
            logger.info(f"{CYAN}Fetching all spaces from {self.config.base_url}/spaces/{RESET}")
            response = self.session.get(f"{self.config.base_url}/spaces/", timeout=10)
            if not response.ok:
                self._handle_api_error(response)
            data = response.json()
            spaces = data.get("items", [])
            logger.info(f"{CYAN}Found {len(spaces)} space(s).{RESET}")
            return spaces

        except requests.RequestException as e:
            logger.error(f"{RED}Network error when fetching spaces: {str(e)}{RESET}")
            raise
        except Exception as e:
            logger.error(f"{RED}Unexpected error when fetching spaces: {str(e)}{RESET}")
            raise

    def get_space_by_id(self, space_id: str) -> Dict:
        """Get a specific space by its ID."""
        try:
            logger.info(f"{CYAN}Fetching space by ID: {space_id}{RESET}")
            response = self.session.get(f"{self.config.base_url}/spaces/{space_id}/", timeout=10)
            if not response.ok:
                self._handle_api_error(response)
            return response.json()
        except requests.RequestException as e:
            logger.error(f"{RED}Network error fetching space {space_id}: {str(e)}{RESET}")
            raise

    def find_space_by_name(self, space_name: str) -> Optional[Dict]:
        """Find a space by name from the list of spaces."""
        all_spaces = self.get_spaces()
        space_name_lower = space_name.strip().lower()

        logger.info(f"{CYAN}Looking for space named '{space_name}'{RESET}")

        # First try exact match
        for sp in all_spaces:
            sp_name = sp.get("name", "").strip().lower()
            if sp_name == space_name_lower:
                logger.info(f"{GREEN}Found exact match for space '{space_name}': {sp.get('name')}{RESET}")
                return sp

        # Then try fuzzy match - handle underscore/hyphen differences
        for sp in all_spaces:
            sp_name = sp.get("name", "").strip().lower()
            if sp_name.replace("_", "-") == space_name_lower.replace("_", "-"):
                logger.info(f"{GREEN}Found fuzzy match for space '{space_name}': {sp.get('name')}{RESET}")
                return sp

        logger.warning(f"{YELLOW}No space found with name '{space_name}'{RESET}")
        return None

    def get_website_status(self, website_id: str) -> Optional[Dict]:
        """
        Get the current status of a website and its latest crawl directly.
        This is used to check if a website already has a queued or running crawl.
        """
        try:
            logger.debug(f"Checking website status for website_id={website_id}")
            response = self.session.get(
                f"{self.config.base_url}/websites/{website_id}/",
                timeout=10
            )
            if not response.ok:
                self._handle_api_error(response)
                
            website_data = response.json()
            latest_crawl = website_data.get("latest_crawl", {})
            
            # Extract the status and other details from the latest crawl
            status = latest_crawl.get("status")
            run_id = latest_crawl.get("id")
            
            if status and status in ("queued", "running"):
                logger.info(f"{YELLOW}Website {website_id} already has a {status} crawl (Run ID: {run_id}){RESET}")
                return {
                    "status": status,
                    "run_id": run_id,
                    "latest_crawl": latest_crawl,
                    "already_active": True
                }
            
            return website_data
            
        except requests.RequestException as e:
            logger.error(f"{RED}Error checking website status: {str(e)}{RESET}")
            return None
        except Exception as e:
            logger.error(f"{RED}Unexpected error when checking website status: {str(e)}{RESET}")
            return None

    def get_websites_for_space(self) -> List[Dict]:
        """Get websites from space data via the knowledge endpoint."""
        # Determine which space to use
        if not self.config.space_id and not self.config.space_name:
            logger.error(f"{RED}No space_id or space_name provided{RESET}")
            raise ValueError("You must provide either space_id or space_name")

        space_id = self.config.space_id
        if not space_id:
            found = self.find_space_by_name(self.config.space_name)
            if not found:
                logger.error(f"{RED}Could not find a space named '{self.config.space_name}'{RESET}")
                raise ValueError(f"Space with name '{self.config.space_name}' not found")
            space_id = found["id"]
            self.config.space_id = space_id

        # Use the /knowledge/ endpoint to get websites directly
        try:
            logger.info(f"{CYAN}Fetching websites for space: {space_id}{RESET}")
            response = self.session.get(f"{self.config.base_url}/spaces/{space_id}/knowledge/", timeout=10)
            if not response.ok:
                self._handle_api_error(response)
                
            data = response.json()
            websites_data = data.get("websites", {})
            all_websites = websites_data.get("items", [])
            logger.info(f"{CYAN}Found {len(all_websites)} website(s) in the space.{RESET}")
            
            # If configured to crawl all websites in the space, return all of them
            if self.config.crawl_all_space_websites:
                logger.info(f"{CYAN}Configured to crawl all websites in the space.{RESET}")
                return all_websites
            
            # Otherwise apply filters
            if not self.config.website_filter:
                logger.info(f"{CYAN}No website filter specified, returning all websites.{RESET}")
                return all_websites

            # Apply filters
            logger.info(f"{CYAN}Applying {len(self.config.website_filter)} website filters{RESET}")
                
            filtered = []
            for site in all_websites:
                site_id = str(site.get("id", "")).strip()
                site_name = str(site.get("name", "")).strip()
                site_url = str(site.get("url", "")).strip()

                site_identifiers = {
                    self._normalize_url(site_id),
                    self._normalize_url(site_name),
                    self._normalize_url(site_url)
                }
                
                for filter_str in self.config.website_filter:
                    clean_filter = self._normalize_url(filter_str)
                    
                    # Check if URL contains the filter or filter contains the URL
                    match_found = False
                    for identifier in site_identifiers:
                        if identifier and clean_filter:
                            if clean_filter in identifier or identifier in clean_filter:
                                match_found = True
                                break
                                
                    if match_found:
                        filtered.append(site)
                        logger.info(f"{GREEN}Matched filter '{filter_str}' to site '{site_name}'{RESET}")
                        break

            logger.info(f"{CYAN}Filter matched {len(filtered)} of {len(all_websites)} websites{RESET}")
            return filtered
            
        except requests.RequestException as e:
            logger.error(f"{RED}Network error fetching websites for space {space_id}: {str(e)}{RESET}")
            raise
        except Exception as e:
            logger.error(f"{RED}Unexpected error fetching websites for space {space_id}: {str(e)}{RESET}")
            raise

    def get_websites(self) -> List[Dict]:
        """Get websites using the space-based approach."""
        return self.get_websites_for_space()

    def trigger_crawl(self, website_id: str) -> Optional[Dict]:
        try:
            logger.info(f"{CYAN}Triggering crawl for website {website_id}{RESET}")
            response = self.session.post(
                f"{self.config.base_url}/websites/{website_id}/run/",
                data="",
                timeout=30
            )
            if not response.ok:
                # This now might return a special response instead of raising an exception
                result = self._handle_api_error(response)
                if result and result.get("already_queued"):
                    return result  # Return the special "already queued" response
                # If it's another error, _handle_api_error will have raised an exception
                
            return response.json()
        except requests.RequestException as e:
            logger.error(f"{RED}Crawl trigger failed: {str(e)}{RESET}")
            return None

    def get_crawl_status(self, website_id: str, run_id: str = None) -> Optional[str]:
        try:
            # If we have a specific run_id, check that run
            if run_id:
                logger.debug(f"Checking status for website_id={website_id}, run_id={run_id}")
                response = self.session.get(
                    f"{self.config.base_url}/websites/{website_id}/runs/",
                    timeout=10
                )
                if not response.ok:
                    self._handle_api_error(response)

                runs = response.json().get("items", [])
                for r in runs:
                    if r["id"] == run_id:
                        return r["status"]
                return None
            else:
                # Otherwise, check the website's latest crawl status
                website_data = self.get_website_status(website_id)
                if website_data and "latest_crawl" in website_data:
                    return website_data["latest_crawl"].get("status")
                return None
                
        except requests.RequestException as e:
            logger.error(f"{RED}Status check failed: {str(e)}{RESET}")
            return None

# ------------------- APScheduler Job Logic -------------------
def run_crawl_for_site(config: AppConfig, api_client: CrawlerAPIClient, site: Dict, user_id: str):
    """Run a crawl for a single site and monitor its progress"""
    site_id = site.get("id")
    site_name = site.get("name") or site_id

    if not site_id:
        logger.error(f"{RED}Website missing ID, skipping...{RESET}")
        return
    
    # Initialize job status for this site if it doesn't exist
    job_key = f"{site_id}"
    if user_id not in USER_JOB_STATUS:
        USER_JOB_STATUS[user_id] = {}
        
    # Check the current status of the website directly to see if it's already being crawled
    current_status = api_client.get_website_status(site_id)
    
    # If it's already active (queued or running), update our state and monitor it
    if current_status and current_status.get("already_active"):
        latest_crawl = current_status.get("latest_crawl", {})
        status = latest_crawl.get("status", "unknown")
        run_id = latest_crawl.get("id")
        
        logger.info(f"{YELLOW}Website {site_name} is already {status}, will monitor existing crawl (Run ID: {run_id}){RESET}")
        
        # Update our job status to match what's already happening
        USER_JOB_STATUS[user_id][job_key] = JobStatus(
            site_id=site_id,
            site_name=site_name,
            run_id=run_id,
            status=status,
            start_time=datetime.now(),  # We don't know the actual start time, so use now
            last_update=datetime.now(),
            # Preserve last_successful_crawl if it exists
            last_successful_crawl=USER_JOB_STATUS.get(user_id, {}).get(job_key, JobStatus(site_id, site_name)).last_successful_crawl
        )
        
        # Skip to monitoring phase
        if LOG_MODE == "debug":
            logger.info(f"{MAGENTA}Monitoring existing {status} crawl for {site_name}...{RESET}")
    else:
        # Check if we're in the middle of an existing job according to our state
        job_status = USER_JOB_STATUS.get(user_id, {}).get(job_key)
        if job_status and job_status.status in ("running", "queued"):
            # Double-check by getting the status from the API
            api_status = api_client.get_crawl_status(site_id, job_status.run_id)
            if api_status in ("running", "queued"):
                logger.info(f"{YELLOW}Skipping crawl for {site_name} - previous crawl still {api_status}{RESET}")
                
                # Update the timestamp to indicate we checked it
                USER_JOB_STATUS[user_id][job_key].last_update = datetime.now()
                return
        
        # Start a new crawl
        USER_JOB_STATUS[user_id][job_key] = JobStatus(
            site_id=site_id,
            site_name=site_name,
            status="starting",
            start_time=datetime.now(),
            last_update=datetime.now(),
            # Preserve last_successful_crawl if it exists
            last_successful_crawl=USER_JOB_STATUS.get(user_id, {}).get(job_key, JobStatus(site_id, site_name)).last_successful_crawl
        )
        
        # Log start based on mode
        if LOG_MODE == "debug":
            logger.info(f"{MAGENTA}Starting crawl job for: {site_name}{RESET}")
        else:
            logger.debug(f"Starting crawl: {site_name} ({user_id})")

        # Trigger crawl
        try:
            resp = api_client.trigger_crawl(site_id)
            if not resp:
                error_msg = f"Failed to start crawl (API returned empty response)"
                logger.error(f"{RED}{error_msg} for {site_name}{RESET}")
                # Update job status to failed
                USER_JOB_STATUS[user_id][job_key].status = "failed"
                USER_JOB_STATUS[user_id][job_key].error_message = error_msg
                USER_JOB_STATUS[user_id][job_key].end_time = datetime.now()
                USER_JOB_STATUS[user_id][job_key].last_update = datetime.now()
                
                # Update status summary immediately when a job fails in production mode
                if LOG_MODE == "production":
                    generate_user_status_summary()
                return
            
            # Special handling for "already queued" response
            if resp.get("already_queued"):
                logger.info(f"{YELLOW}Crawl for {site_name} is already queued/in progress, monitoring status...{RESET}")
                USER_JOB_STATUS[user_id][job_key].status = "queued"
                USER_JOB_STATUS[user_id][job_key].last_update = datetime.now()
                # Continue to the status monitoring loop - no run_id but we can
                # still poll for the latest runs for this site
                run_id = None
            else:
                run_id = resp.get("id")
                USER_JOB_STATUS[user_id][job_key].run_id = run_id
                USER_JOB_STATUS[user_id][job_key].status = "running"
                USER_JOB_STATUS[user_id][job_key].last_update = datetime.now()
                
                # Log differently based on mode
                if LOG_MODE == "debug":
                    logger.info(f"{GREEN}Started crawl for {site_name} (Run ID: {run_id}){RESET}")
            
        except Exception as e:
            error_msg = f"Error triggering crawl: {str(e)}"
            logger.error(f"{RED}{error_msg} for {site_name}{RESET}")
            # Update job status to failed
            USER_JOB_STATUS[user_id][job_key].status = "failed"
            USER_JOB_STATUS[user_id][job_key].error_message = error_msg
            USER_JOB_STATUS[user_id][job_key].end_time = datetime.now()
            USER_JOB_STATUS[user_id][job_key].last_update = datetime.now()
            
            # Update status summary immediately when a job fails in production mode
            if LOG_MODE == "production":
                generate_user_status_summary()
            return

    # In debug mode only, show detailed monitoring message
    if LOG_MODE == "debug":
        logger.info(f"{MAGENTA}Monitoring crawl status for {site_name}...{RESET}")
    
    # Monitor the crawl until it completes or fails
    active = True
    while active:
        try:
            # If we have a run_id, check that specific run. Otherwise, check latest status.
            if USER_JOB_STATUS[user_id][job_key].run_id:
                status = api_client.get_crawl_status(site_id, USER_JOB_STATUS[user_id][job_key].run_id)
            else:
                # When run_id is not available, check the website's latest crawl
                website_data = api_client.get_website_status(site_id)
                if website_data and "latest_crawl" in website_data:
                    latest_crawl = website_data["latest_crawl"]
                    status = latest_crawl.get("status")
                    # Update the run_id if we find it
                    if "id" in latest_crawl and latest_crawl["status"] in ("queued", "running"):
                        USER_JOB_STATUS[user_id][job_key].run_id = latest_crawl["id"]
                        if LOG_MODE == "debug":
                            logger.info(f"{GREEN}Found active run {latest_crawl['id']} for {site_name}{RESET}")
                else:
                    status = None
                
            USER_JOB_STATUS[user_id][job_key].last_update = datetime.now()
            
            if not status:
                # Only log "status not available" in debug mode
                if LOG_MODE == "debug":
                    logger.info(f"{YELLOW}Status not available yet for {site_name}{RESET}")
            else:
                USER_JOB_STATUS[user_id][job_key].status = status
                
                if status == "complete":
                    logger.info(f"{GREEN}Completed crawl for {site_name} (Run ID: {USER_JOB_STATUS[user_id][job_key].run_id}){RESET}")
                    USER_JOB_STATUS[user_id][job_key].end_time = datetime.now()
                    USER_JOB_STATUS[user_id][job_key].last_successful_crawl = datetime.now()
                    active = False
                    
                    # In production mode, only update the summary if enough time has passed
                    if LOG_MODE == "production":
                        last_summary_time = getattr(generate_user_status_summary, "last_summary_time", datetime.min)
                        if (datetime.now() - last_summary_time).total_seconds() > 60:
                            generate_user_status_summary()
                        
                elif status in ("failed", "cancelled"):
                    error_msg = f"Crawl {status}"
                    logger.error(f"{RED}{error_msg} for {site_name} (Run ID: {USER_JOB_STATUS[user_id][job_key].run_id}){RESET}")
                    USER_JOB_STATUS[user_id][job_key].status = status
                    USER_JOB_STATUS[user_id][job_key].error_message = error_msg
                    USER_JOB_STATUS[user_id][job_key].end_time = datetime.now()
                    active = False
                    
                    # Always update on failures
                    if LOG_MODE == "production":
                        generate_user_status_summary()
                        
                else:
                    # Only log intermediate statuses in debug mode
                    if LOG_MODE == "debug":
                        logger.info(f"{CYAN}{site_name} status: {status}{RESET}")

            if active:
                # In debug mode, log wait message
                if LOG_MODE == "debug":
                    logger.info(f"{MAGENTA}Waiting {config.status_check_interval}s before next status check for {site_name}...{RESET}")
                time.sleep(config.status_check_interval)

        except Exception as e:
            error_msg = f"Status check error: {str(e)}"
            logger.error(f"{RED}{error_msg} for {site_name}{RESET}")
            # Just log the error but don't update status yet - retry on next loop
            time.sleep(config.status_check_interval)

    # Final status update
    if USER_JOB_STATUS[user_id][job_key].status == "running":
        USER_JOB_STATUS[user_id][job_key].status = "unknown"
        USER_JOB_STATUS[user_id][job_key].error_message = "Final status unknown"
        
    # In debug mode only, show job finished message
    if LOG_MODE == "debug":
        logger.info(f"{GREEN}Crawl job finished for {site_name}!{RESET}")

def run_all_sites_once(config: AppConfig, api_client: CrawlerAPIClient, user_id: str):
    """Run a one-time crawl for all matching sites for a user"""
    # Log based on mode
    if LOG_MODE == "debug":
        logger.info(f"{YELLOW}=== TEST MODE (single aggregated run) ==={RESET}")
    else:
        logger.info(f"Starting test mode for user {user_id}")
        
    try:
        websites = api_client.get_websites()
    except Exception as e:
        logger.error(f"{RED}Failed to fetch websites in test mode: {str(e)}{RESET}")
        return

    if not websites:
        logger.warning(f"{YELLOW}No websites matched filter criteria.{RESET}")
        return

    # Log websites based on mode
    if LOG_MODE == "debug":
        logger.info(f"{CYAN}Found {len(websites)} websites for test mode: {[w.get('name', w.get('id')) for w in websites]}{RESET}")
    else:
        logger.info(f"Found {len(websites)} websites to crawl for user {user_id}")
        
    for site in websites:
        run_crawl_for_site(config, api_client, site, user_id)
        
    # Final log based on mode
    if LOG_MODE == "debug":
        logger.info(f"{YELLOW}=== TEST COMPLETE ==={RESET}")
    else:
        logger.info(f"Test mode completed for user {user_id}")

# ------------------- User Management Functions -------------------
def load_users_from_json():
    """Load initial user configurations from users.json file"""
    users_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")
    
    if not os.path.exists(users_file):
        logger.info(f"{YELLOW}No users.json file found, skipping initial user configuration{RESET}")
        return
    
    try:
        with open(users_file, 'r') as f:
            users_data = json.load(f)
        
        users = users_data.get("users", [])
        if not users:
            logger.info(f"{YELLOW}No users defined in users.json{RESET}")
            return
            
        logger.info(f"{GREEN}Loading {len(users)} users from users.json{RESET}")
        
        # Process each user
        for user_config in users:
            user_id = user_config.get("user_id")
            if not user_id:
                logger.warning(f"{YELLOW}Skipping user with missing ID in users.json{RESET}")
                continue
                
            # Make sure we're using the right API key for this user
            api_key = user_config.get("api_key", "").strip()
            if not api_key or not api_key.startswith("inp_"):
                logger.warning(f"{YELLOW}Invalid API key for user {user_id}, skipping{RESET}")
                continue
                
            # Check for spaces
            if "spaces" in user_config and isinstance(user_config["spaces"], list):
                spaces = user_config["spaces"]
                logger.debug(f"{BLUE}Found {len(spaces)} spaces for user {user_id}{RESET}")
                
                # Create a separate configuration for each space
                for i, space in enumerate(spaces):
                    # Use a unique ID for each space configuration
                    space_user_id = user_id if len(spaces) == 1 else f"{user_id}_space{i+1}"
                    
                    # Make sure filters are stored as a set of strings
                    website_filter = set()
                    if "website_filter" in space and isinstance(space["website_filter"], list):
                        website_filter = {w.strip() for w in space["website_filter"] if isinstance(w, str) and w.strip()}
                    
                    # Create user config for this space - ensure we use the correct API key
                    USER_CONFIGS[space_user_id] = AppConfig(
                        api_key=api_key,  # Use the API key from the user configuration
                        base_url=user_config.get("base_url", "https://sundsvall.backend.intric.ai/api/v1"),
                        schedule_minutes=space.get("schedule_minutes", 5),
                        website_filter=website_filter,
                        status_check_interval=space.get("status_check_interval", 60),
                        space_id=space.get("space_id"),
                        space_name=space.get("space_name"),
                        crawl_all_space_websites=space.get("crawl_all_space_websites", False)
                    )
                    
                    USER_API_CLIENTS[space_user_id] = CrawlerAPIClient(USER_CONFIGS[space_user_id])
                    USER_WEBSITES[space_user_id] = []
                    USER_JOBS_CREATED[space_user_id] = False
                    
                    if LOG_MODE == "debug":
                        logger.debug(f"{GREEN}Configured user {space_user_id} with space {space.get('space_name', space.get('space_id', 'unknown'))}{RESET}")
                        if website_filter:
                            logger.debug(f"{CYAN}Website filters for {space_user_id}: {list(website_filter)[:2]}... (total: {len(website_filter)}){RESET}")
            else:
                # Single space configuration - ensure we use the correct API key
                USER_CONFIGS[user_id] = AppConfig(
                    api_key=api_key,  # Use the API key from the user configuration
                    base_url=user_config.get("base_url", "https://sundsvall.backend.intric.ai/api/v1"),
                    schedule_minutes=user_config.get("schedule_minutes", 5),
                    website_filter=set(user_config.get("website_filter", [])),
                    status_check_interval=user_config.get("status_check_interval", 60),
                    space_id=user_config.get("space_id"),
                    space_name=user_config.get("space_name"),
                    crawl_all_space_websites=user_config.get("crawl_all_space_websites", False)
                )
                
                USER_API_CLIENTS[user_id] = CrawlerAPIClient(USER_CONFIGS[user_id])
                USER_WEBSITES[user_id] = []
                USER_JOBS_CREATED[user_id] = False
        
        logger.info(f"{GREEN}Successfully loaded {len(USER_CONFIGS)} user configurations from users.json{RESET}")
        
    except json.JSONDecodeError:
        logger.error(f"{RED}Invalid JSON format in users.json file{RESET}")
    except Exception as e:
        logger.error(f"{RED}Error loading users from users.json: {str(e)}{RESET}")

def clear_jobs(user_id: str):
    """Remove all jobs for a specific user from APScheduler"""
    global USER_JOBS_CREATED
    user_job_prefix = f"{user_id}_crawl_"
    
    for job in scheduler.get_jobs():
        if job.id.startswith(user_job_prefix):
            logger.info(f"{RED}Removing job: {job.id}{RESET}")
            scheduler.remove_job(job.id)

    USER_JOBS_CREATED[user_id] = False

    # Set all job statuses to stopped
    if user_id in USER_JOB_STATUS:
        for site_id in USER_JOB_STATUS[user_id]:
            USER_JOB_STATUS[user_id][site_id].status = "stopped"
            USER_JOB_STATUS[user_id][site_id].end_time = datetime.now()
            USER_JOB_STATUS[user_id][site_id].last_update = datetime.now()

def start_configured_users():
    """Start crawling for all configured users from users.json"""
    logger.info(f"{GREEN}Starting crawlers for {len(USER_CONFIGS)} configured users...{RESET}")
    
    for user_id in list(USER_CONFIGS.keys()):
        try:
            if user_id in USER_CONFIGS and user_id in USER_API_CLIENTS:
                # Fetch websites first
                websites = USER_API_CLIENTS[user_id].get_websites()
                USER_WEBSITES[user_id] = websites
                
                if not websites:
                    logger.warning(f"{YELLOW}No websites found for {user_id}, not scheduling jobs{RESET}")
                    continue
                
                # Initialize job status tracking for this user
                if user_id not in USER_JOB_STATUS:
                    USER_JOB_STATUS[user_id] = {}

                # Schedule jobs for each site with staggered start times
                for i, site in enumerate(websites):
                    site_id = site.get("id")
                    site_name = site.get("name", "Unknown") or site_id
                    
                    if not site_id:
                        continue
                        
                    # Initialize job status
                    USER_JOB_STATUS[user_id][site_id] = JobStatus(
                        site_id=site_id,
                        site_name=site_name,
                        status="idle",
                        last_update=datetime.now()
                    )
                    
                    job_id = f"{user_id}_crawl_{site_id}"
                    
                    # Stagger initial runs to avoid overloading
                    stagger_seconds = min(i * 20, 300)
                    next_run_time = datetime.now() + timedelta(seconds=stagger_seconds)
                    
                    scheduler.add_job(
                        run_crawl_for_site,
                        "interval",
                        minutes=USER_CONFIGS[user_id].schedule_minutes,
                        args=[USER_CONFIGS[user_id], USER_API_CLIENTS[user_id], site, user_id],
                        id=job_id,
                        next_run_time=next_run_time,
                        max_instances=1,
                        coalesce=True,
                        misfire_grace_time=600
                    )
                
                USER_JOBS_CREATED[user_id] = True
                logger.info(f"{GREEN}Scheduled {len(websites)} sites for user {user_id}{RESET}")
                
        except Exception as e:
            logger.error(f"{RED}Error starting crawler for {user_id}: {str(e)}{RESET}")

def refresh_websites_for_user(user_id: str):
    """Refresh the website list for a user and schedule new websites"""
    if user_id not in USER_CONFIGS or user_id not in USER_API_CLIENTS:
        logger.warning(f"{YELLOW}Cannot refresh websites for unknown user {user_id}{RESET}")
        return
        
    try:
        # Get the current websites
        current_websites = set(site.get("id") for site in USER_WEBSITES.get(user_id, []) if site.get("id"))
        
        # Fetch the latest websites from the API
        latest_websites = USER_API_CLIENTS[user_id].get_websites()
        USER_WEBSITES[user_id] = latest_websites
        
        # Find new websites that weren't scheduled before
        new_websites = []
        for site in latest_websites:
            site_id = site.get("id")
            if site_id and site_id not in current_websites:
                new_websites.append(site)
                
        if new_websites:
            logger.info(f"{GREEN}Found {len(new_websites)} new websites for user {user_id}, scheduling them now{RESET}")
            
            # Initialize job status tracking if needed
            if user_id not in USER_JOB_STATUS:
                USER_JOB_STATUS[user_id] = {}
                
            # Schedule new websites
            for i, site in enumerate(new_websites):
                site_id = site.get("id")
                site_name = site.get("name", "Unknown") or site_id
                
                if not site_id:
                    continue
                    
                # Initialize job status
                USER_JOB_STATUS[user_id][site_id] = JobStatus(
                    site_id=site_id,
                    site_name=site_name,
                    status="idle",
                    last_update=datetime.now()
                )
                
                job_id = f"{user_id}_crawl_{site_id}"
                
                # Start with a small stagger to avoid all hitting at once
                stagger_seconds = min(i * 10, 120)
                next_run_time = datetime.now() + timedelta(seconds=stagger_seconds)
                
                scheduler.add_job(
                    run_crawl_for_site,
                    "interval",
                    minutes=USER_CONFIGS[user_id].schedule_minutes,
                    args=[USER_CONFIGS[user_id], USER_API_CLIENTS[user_id], site, user_id],
                    id=job_id,
                    next_run_time=next_run_time,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=600
                )
                
                logger.info(f"{GREEN}Scheduled new website: {site_name} for user {user_id}{RESET}")
                
            USER_JOBS_CREATED[user_id] = True
            
            # Update status summary immediately in production mode
            if LOG_MODE == "production":
                generate_user_status_summary()
        else:
            if LOG_MODE == "debug":
                logger.info(f"{BLUE}No new websites found for user {user_id}{RESET}")
                
    except Exception as e:
        logger.error(f"{RED}Error refreshing websites for user {user_id}: {str(e)}{RESET}")

def setup_website_refresh_job(scheduler):
    """Set up a job to periodically check for new websites in all spaces"""
    # Check for new websites every hour by default
    refresh_interval_minutes = int(os.getenv("WEBSITE_REFRESH_INTERVAL", "60"))
    
    if refresh_interval_minutes > 0:
        logger.info(f"{GREEN}Setting up periodic website refresh job every {refresh_interval_minutes} minutes{RESET}")
        
        # Function to refresh all users
        def refresh_all_users():
            logger.info(f"{CYAN}Checking for new websites for all users...{RESET}")
            for user_id in list(USER_CONFIGS.keys()):
                refresh_websites_for_user(user_id)
        
        scheduler.add_job(
            refresh_all_users,
            "interval",
            minutes=refresh_interval_minutes,
            id="website_refresh_job",
            replace_existing=True
        )
    else:
        logger.info(f"{YELLOW}Website refresh job disabled (interval set to {refresh_interval_minutes}){RESET}")

# ------------------- FastAPI Setup -------------------
app = FastAPI(
    title="Crawler Scheduler API",
    description="Multi-user crawler scheduler API for Intric integration",
    version="1.0.0",
)

# Initialize scheduler
scheduler = BackgroundScheduler(executors={'default': ThreadPoolExecutor(10)})
scheduler.start()

# Set up status logger
setup_status_logger(scheduler)

# ------------------- FastAPI Endpoints -------------------
@app.post("/config/{user_id}")
def set_config(user_id: str, payload: ConfigModel):
    """Set or update user configuration"""
    if not payload.api_key.startswith("inp_"):
        raise HTTPException(status_code=400, detail="API key must start with 'inp_'")

    if not (payload.space_id or payload.space_name):
        raise HTTPException(status_code=400, detail="Either space_id or space_name must be provided")

    # Clear existing jobs for this user
    clear_jobs(user_id)

    USER_CONFIGS[user_id] = AppConfig(
        api_key=payload.api_key,
        base_url=payload.base_url,
        schedule_minutes=payload.schedule_minutes,
        website_filter={w.strip().lower().rstrip('/') for w in payload.website_filter if w.strip()},
        status_check_interval=payload.status_check_interval,
        space_id=payload.space_id,
        space_name=payload.space_name,
        crawl_all_space_websites=payload.crawl_all_space_websites
    )
    USER_API_CLIENTS[user_id] = CrawlerAPIClient(USER_CONFIGS[user_id])
    USER_WEBSITES[user_id] = []
    USER_JOBS_CREATED[user_id] = False
    
    return {
        "detail": f"Config set for user {user_id}. Call /start/{user_id} to schedule or /test/{user_id} for one-shot run.",
        "config": {
            "api_key": USER_CONFIGS[user_id].api_key[:5] + "..." + USER_CONFIGS[user_id].api_key[-3:],
            "base_url": USER_CONFIGS[user_id].base_url,
            "schedule_minutes": USER_CONFIGS[user_id].schedule_minutes,
            "website_filter": list(USER_CONFIGS[user_id].website_filter),
            "space_id": USER_CONFIGS[user_id].space_id,
            "space_name": USER_CONFIGS[user_id].space_name,
            "status_check_interval": USER_CONFIGS[user_id].status_check_interval
        }
    }

@app.post("/start/{user_id}")
def start_scheduling(user_id: str):
    """Start scheduling crawls for a user"""
    if user_id not in USER_CONFIGS or user_id not in USER_API_CLIENTS:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found. Call /config/{user_id} first.")

    if USER_JOBS_CREATED.get(user_id, False):
        return {
            "detail": f"Jobs for user {user_id} already created and running.",
            "user_id": user_id,
            "websites_count": len(USER_WEBSITES.get(user_id, []))
        }

    # Fetch websites
    try:
        USER_WEBSITES[user_id] = USER_API_CLIENTS[user_id].get_websites()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch websites: {str(e)}")

    if not USER_WEBSITES[user_id]:
        logger.warning(f"No websites matched filter for user {user_id}, no jobs to schedule.")
        return {
            "detail": "No websites matched filter, nothing scheduled.",
            "user_id": user_id,
            "websites_count": 0
        }

    # Initialize job status tracking
    if user_id not in USER_JOB_STATUS:
        USER_JOB_STATUS[user_id] = {}

    # Create job for each site with staggered initial runs
    for i, site in enumerate(USER_WEBSITES[user_id]):
        site_id = site.get("id")
        site_name = site.get("name") or site_id
        if not site_id:
            continue

        # Initialize job status
        USER_JOB_STATUS[user_id][site_id] = JobStatus(
            site_id=site_id,
            site_name=site_name,
            status="idle",
            last_update=datetime.now()
        )
            
        job_id = f"{user_id}_crawl_{site_id}"
        
        # Calculate staggered start time
        stagger_seconds = min(i * 20, 300)
        next_run_time = datetime.now() + timedelta(seconds=stagger_seconds)
        
        logger.info(f"Scheduling site {site_id} every {USER_CONFIGS[user_id].schedule_minutes} min for user {user_id}")
        
        scheduler.add_job(
            run_crawl_for_site,
            "interval",
            minutes=USER_CONFIGS[user_id].schedule_minutes,
            args=[USER_CONFIGS[user_id], USER_API_CLIENTS[user_id], site, user_id],
            id=job_id,
            next_run_time=next_run_time,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=600
        )

    USER_JOBS_CREATED[user_id] = True
    
    return {
        "detail": f"Scheduled {len(USER_WEBSITES[user_id])} sites at {USER_CONFIGS[user_id].schedule_minutes}-minute intervals.",
        "user_id": user_id,
        "websites_count": len(USER_WEBSITES[user_id])
    }

@app.post("/stop/{user_id}")
def stop_scheduling(user_id: str):
    """Stop all scheduled crawl jobs for a user"""
    if user_id not in USER_CONFIGS:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        
    # Remove scheduled jobs but preserve configuration
    clear_jobs(user_id)
    
    return {
        "detail": f"All scheduled jobs for user {user_id} stopped. Configuration preserved.",
        "user_id": user_id
    }

@app.post("/test/{user_id}")
def test_crawling(user_id: str):
    """Run all matched sites once for a user"""
    if user_id not in USER_CONFIGS or user_id not in USER_API_CLIENTS:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found. Call /config/{user_id} first.")

    # Run in a separate thread to not block the API response
    thread = threading.Thread(
        target=run_all_sites_once,
        args=[USER_CONFIGS[user_id], USER_API_CLIENTS[user_id], user_id]
    )
    thread.start()
    return {
        "detail": f"Test crawl started for user {user_id}. Check logs for progress and completion.",
        "user_id": user_id
    }

@app.get("/status/{user_id}")
def get_status(user_id: str):
    """Get current config and status for a user"""
    if user_id not in USER_CONFIGS:
        raise HTTPException(
            status_code=404,
            detail=f"No config set for user {user_id}. Call /config/{user_id} first."
        )

    # Get job IDs
    job_list = scheduler.get_jobs()
    job_ids = [job.id for job in job_list if job.id.startswith(f"{user_id}_crawl_")]
    
    # Get space name if we only have ID
    space_name = USER_CONFIGS[user_id].space_name
    if USER_CONFIGS[user_id].space_id and not space_name:
        try:
            space_data = USER_API_CLIENTS[user_id].get_space_by_id(USER_CONFIGS[user_id].space_id)
            space_name = space_data.get("name", "Unknown")
        except Exception:
            space_name = "Error fetching name"

    # Convert job statuses to response format
    job_statuses = []
    if user_id in USER_JOB_STATUS:
        for site_id, status in USER_JOB_STATUS[user_id].items():
            job_statuses.append({
                "site_id": status.site_id,
                "site_name": status.site_name,
                "status": status.status,
                "run_id": status.run_id,
                "start_time": status.start_time,
                "end_time": status.end_time,
                "error_message": status.error_message,
                "last_update": status.last_update,
                "last_successful_crawl": status.last_successful_crawl
            })

    # Get list of websites
    websites_matched = []
    if user_id in USER_WEBSITES and USER_WEBSITES[user_id]:
        websites_matched = [
            w.get("name") or w.get("id") or "unknown" 
            for w in USER_WEBSITES.get(user_id, [])
        ]

    return {
        "user_id": user_id,
        "config": {
            "api_key": USER_CONFIGS[user_id].api_key[:5] + "..." + USER_CONFIGS[user_id].api_key[-3:],
            "base_url": USER_CONFIGS[user_id].base_url,
            "schedule_minutes": USER_CONFIGS[user_id].schedule_minutes,
            "status_check_interval": USER_CONFIGS[user_id].status_check_interval,
            "website_filter": list(USER_CONFIGS[user_id].website_filter),
            "space_id": USER_CONFIGS[user_id].space_id,
            "space_name": space_name
        },
        "websites_matched": websites_matched,
        "jobs_created": USER_JOBS_CREATED.get(user_id, False),
        "active_job_ids": job_ids,
        "job_count": len(job_ids),
        "job_statuses": job_statuses
    }

@app.get("/users")
def list_users():
    """List all configured users"""
    return {
        "users": list(USER_CONFIGS.keys()),
        "total": len(USER_CONFIGS)
    }

@app.get("/system/health")
def health_check():
    """Simple health check endpoint"""
    job_count = len(scheduler.get_jobs())
    user_count = len(USER_CONFIGS)
    
    return {
        "status": "ok",
        "users": user_count,
        "jobs": job_count,
        "scheduler_running": scheduler.running
    }

@app.post("/system/status-summary")
def generate_status_summary():
    """Generate a status summary for all users"""
    generate_user_status_summary.called_from_endpoint = True
    summary_data = generate_user_status_summary()
    
    # Return the structured summary in the response
    return {
        "detail": "Status summary generated",
        "timestamp": datetime.now().isoformat(),
        "summary": summary_data
    }

# ------------------- Application Startup/Shutdown -------------------
@app.on_event("startup")
def startup_event():
    """Initialize the application on startup"""
    # Clear any existing state
    USER_CONFIGS.clear()
    USER_API_CLIENTS.clear()
    USER_WEBSITES.clear()
    USER_JOBS_CREATED.clear()
    USER_JOB_STATUS.clear()
    
    # Load from users.json
    load_users_from_json()
    
    # Start crawlers for all configured users
    start_configured_users()
    
    # Set up the website refresh job
    setup_website_refresh_job(scheduler)
    
    logger.info(f"{GREEN}Crawler API started. Scheduler running: {scheduler.running}{RESET}")
    
    # Generate initial status summary in production mode
    if LOG_MODE == "production":
        generate_user_status_summary()

@app.on_event("shutdown")
def shutdown_event():
    logger.info("Shutting down APScheduler...")
    scheduler.shutdown()

# For running directly with Python
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)