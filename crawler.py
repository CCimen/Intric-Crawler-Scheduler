"""
Website Crawler Scheduler with Enhanced Error Handling

FIXES APPLIED:
1. Added null checks for website fields
2. Improved URL normalization
3. Added debug logging for filter matching
"""

import os
import logging
import time
import sys
import signal
from argparse import ArgumentParser
from dataclasses import dataclass
from typing import List, Dict, Set, Optional, Tuple
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("crawler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class AppConfig:
    """Application configuration container"""
    api_key: str
    base_url: str
    schedule_minutes: int
    website_filter: Set[str]
    test_mode: bool
    status_check_interval: int = 60  # Seconds between status checks

class CrawlerAPIClient:
    """Handles API communication with enhanced error handling"""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "api-key": self.config.api_key,
            "accept": "application/json"
        })
        self.session.mount('https://', requests.adapters.HTTPAdapter(
            max_retries=3,
            pool_maxsize=10
        ))

    def _handle_api_error(self, response: requests.Response):
        """Handle API errors with detailed logging"""
        try:
            error_data = response.json()
        except ValueError:
            error_data = {"detail": "Unknown error - non-JSON response"}

        logger.error(f"API Error {response.status_code}: {error_data.get('detail', 'Unknown error')}")
        logger.debug(f"Error response headers: {response.headers}")
        logger.debug(f"Error response content: {response.text[:1000]}")

        if response.status_code == 422:
            raise ValueError(f"Validation error: {error_data.get('detail', 'Check request parameters')}")
        response.raise_for_status()

    def _normalize_url(self, url: Optional[str]) -> str:
        """Normalize URLs for consistent comparison"""
        if not url:
            return ""
        return url.lower().strip().rstrip('/')

    def get_websites(self) -> List[Dict]:
        """Fetch and filter registered websites with exact matching"""
        try:
            logger.info(f"Fetching websites from {self.config.base_url}")
            response = self.session.get(
                f"{self.config.base_url}/websites/?for_tenant=false",
                timeout=10
            )

            if not response.ok:
                self._handle_api_error(response)

            all_websites = response.json().get("items", [])
            logger.info(f"Found {len(all_websites)} total websites")

            if not self.config.website_filter:
                return all_websites

            filtered = []
            for site in all_websites:
                # Safely get values with fallbacks
                site_id = str(site.get("id", "")).strip()
                site_name = str(site.get("name", "")).strip()
                site_url = str(site.get("url", "")).strip()

                # Create normalized identifiers
                site_identifiers = {
                    self._normalize_url(site_id),
                    self._normalize_url(site_name),
                    self._normalize_url(site_url)
                }

                # Debug log identifiers
                logger.debug(f"Checking site: {site_name} | ID: {site_id} | URL: {site_url}")
                logger.debug(f"Site identifiers: {site_identifiers}")

                # Check against filters
                for filter_str in self.config.website_filter:
                    clean_filter = self._normalize_url(filter_str)
                    if clean_filter in site_identifiers:
                        filtered.append(site)
                        logger.info(f"Matched filter '{filter_str}' to site '{site_name}'")
                        break

            logger.info(f"Filter matched {len(filtered)} of {len(all_websites)} websites")
            return filtered

        except requests.RequestException as e:
            logger.error(f"Network error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise

    def trigger_crawl(self, website_id: str) -> Optional[Dict]:
        """Initiate a crawl with error handling"""
        try:
            logger.info(f"Triggering crawl for website {website_id}")
            response = self.session.post(
                f"{self.config.base_url}/websites/{website_id}/run/",
                data="",
                timeout=30
            )

            if not response.ok:
                self._handle_api_error(response)

            return response.json()
        except requests.RequestException as e:
            logger.error(f"Crawl trigger failed: {str(e)}")
            return None

    def get_crawl_status(self, website_id: str, run_id: str) -> Optional[str]:
        """Check crawl status with error handling"""
        try:
            logger.debug(f"Checking status for {run_id}")
            response = self.session.get(
                f"{self.config.base_url}/websites/{website_id}/runs/",
                timeout=10
            )

            if not response.ok:
                self._handle_api_error(response)

            runs = response.json().get("items", [])
            return next(
                (run["status"] for run in runs if run["id"] == run_id),
                None
            )
        except requests.RequestException as e:
            logger.error(f"Status check failed: {str(e)}")
            return None

def run_crawl_job(config: AppConfig, api_client: CrawlerAPIClient):
    """Execute and monitor crawling process with error tracking"""
    logger.info("Starting crawl job")
    
    try:
        websites = api_client.get_websites()
        if not websites:
            logger.warning("No websites matched filter criteria")
            logger.info(f"Filter used: {config.website_filter}")
            return
            
        logger.info(f"Processing {len(websites)} websites: {[w.get('name') for w in websites]}")

    except Exception as e:
        logger.error(f"Crawl job aborted: {str(e)}")
        logger.debug("Error traceback:", exc_info=True)
        return

    active_runs = []
    for website in websites:
        website_id = website.get("id")
        if not website_id:
            logger.error("Website missing ID, skipping")
            continue
            
        website_name = website.get("name", website_id)
        
        try:
            if response := api_client.trigger_crawl(website_id):
                active_runs.append((website_id, response["id"], website_name))
                logger.info(f"Started crawl for {website_name} (ID: {response['id']})")
            else:
                logger.error(f"Failed to start crawl for {website_name}")
        except Exception as e:
            logger.error(f"Error triggering crawl for {website_name}: {str(e)}")

    while active_runs:
        remaining = []
        for website_id, run_id, name in active_runs:
            try:
                status = api_client.get_crawl_status(website_id, run_id)
                if not status:
                    remaining.append((website_id, run_id, name))
                    continue
                
                if status == "complete":
                    logger.info(f"Completed crawl for {name} ({run_id})")
                elif status in ("failed", "cancelled"):
                    logger.error(f"Crawl failed for {name} ({status})")
                else:
                    remaining.append((website_id, run_id, name))
                    logger.info(f"{name} status: {status}")
            except Exception as e:
                logger.error(f"Status check error for {name}: {str(e)}")
                remaining.append((website_id, run_id, name))

        active_runs = remaining
        if active_runs:
            logger.info(f"Waiting {config.status_check_interval}s for status updates...")
            time.sleep(config.status_check_interval)

    logger.info("Crawl job finished")

def load_config() -> AppConfig:
    """Load and validate configuration with strict checks"""
    load_dotenv()
    
    parser = ArgumentParser(description="Website Crawler Scheduler")
    parser.add_argument("--test", action="store_true", help="Run once in test mode")
    parser.add_argument("--websites", type=str, help="Comma-separated website identifiers")
    args = parser.parse_args()

    api_key = os.getenv("API_KEY", "").strip()
    if not api_key.startswith("inp_"):
        logger.error("Invalid API key format - must start with 'inp_'")
        sys.exit(1)

    base_url = os.getenv("BASE_URL", "https://sundsvall.backend.intric.ai/api/v1").strip()
    if not base_url.startswith(("http://", "https://")):
        logger.error(f"Invalid BASE_URL: {base_url}")
        sys.exit(1)

    try:
        schedule = int(os.getenv("SCHEDULE_MINUTES", "300"))
        if schedule < 1:
            raise ValueError
    except ValueError:
        logger.error("SCHEDULE_MINUTES must be positive integer")
        sys.exit(1)

    website_filter = set()
    if os.getenv("WEBSITE_FILTER"):
        website_filter.update(os.getenv("WEBSITE_FILTER").split(","))
    if args.websites:
        website_filter.update(args.websites.split(","))

    return AppConfig(
        api_key=api_key,
        base_url=base_url,
        schedule_minutes=schedule,
        website_filter={s.strip().lower().rstrip('/') for s in website_filter if s.strip()},
        test_mode=args.test
    )

def main():
    """Main application workflow"""
    config = load_config()
    api_client = CrawlerAPIClient(config)
    
    if config.test_mode:
        logger.info("=== TEST MODE ===")
        run_crawl_job(config, api_client)
        logger.info("=== TEST COMPLETE ===")
        return

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_crawl_job,
        'interval',
        minutes=config.schedule_minutes,
        args=[config, api_client],
        next_run_time=datetime.now() + timedelta(seconds=5)
    )

    def shutdown(signum, frame):
        logger.info("Shutting down...")
        scheduler.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    scheduler.start()
    logger.info(f"Scheduler started. Interval: {config.schedule_minutes} minutes")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)

if __name__ == "__main__":
    main()