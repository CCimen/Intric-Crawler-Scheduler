#!/usr/bin/env python3
"""
Multi-user startup script for the crawler.
This script reads users.json and configures all users automatically.
"""
import os
import sys
import json
import time
import logging
import requests
import argparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

def configure_user(api_url, user_config):
    """Configure a single user with potentially multiple spaces"""
    user_id = user_config['user_id']
    api_key = user_config['api_key']
    base_url = user_config['base_url']
    
    # Check if we're using the old format (single space) or new format (multiple spaces)
    if 'spaces' in user_config:
        # New format with multiple spaces
        spaces = user_config['spaces']
        logger.info(f"Configuring user {user_id} with {len(spaces)} spaces")
        
        success_count = 0
        for i, space_config in enumerate(spaces):
            # Create a unique sub-user ID for each space
            space_user_id = f"{user_id}_space{i+1}" if len(spaces) > 1 else user_id
            
            # Create payload for this space configuration
            payload = {
                "api_key": api_key,
                "base_url": base_url,
                "schedule_minutes": space_config.get("schedule_minutes", 5),
                "website_filter": space_config.get("website_filter", []),
                "status_check_interval": space_config.get("status_check_interval", 60),
                "space_id": space_config.get("space_id"),
                "space_name": space_config.get("space_name"),
                "crawl_all_space_websites": space_config.get("crawl_all_space_websites", False)
            }
            
            try:
                logger.info(f"Configuring {space_user_id} with space {space_config.get('space_name') or space_config.get('space_id')}")
                
                # Set the configuration for this space
                resp = requests.post(f"{api_url}/config/{space_user_id}", json=payload, timeout=30)
                resp.raise_for_status()
                
                # Start the crawler for this space
                resp = requests.post(f"{api_url}/start/{space_user_id}", timeout=30)
                resp.raise_for_status()
                result = resp.json()
                logger.info(f"Started {space_user_id}: {result['detail']}")
                
                # Then run a test crawl to ensure it starts immediately
                logger.info(f"Triggering immediate initial crawl for {space_user_id}")
                test_resp = requests.post(f"{api_url}/test/{space_user_id}", timeout=15)
                if test_resp.ok:
                    logger.info(f"Initial crawl triggered for {space_user_id}")
                
                success_count += 1
                
                # Add a slight delay between spaces to prevent overloading
                if i < len(spaces) - 1:
                    time.sleep(2)
                    
            except Exception as e:
                logger.error(f"Error setting up {space_user_id}: {str(e)}")
        
        return success_count > 0
    else:
        # Old format with single space - use existing code
        payload = {
            "api_key": api_key,
            "base_url": base_url,
            "schedule_minutes": user_config.get("schedule_minutes", 5),
            "website_filter": user_config.get("website_filter", []),
            "status_check_interval": user_config.get("status_check_interval", 60),
            "space_id": user_config.get("space_id"),
            "space_name": user_config.get("space_name"),
            "crawl_all_space_websites": user_config.get("crawl_all_space_websites", False)
        }
        
        try:
            logger.info(f"Configuring user {user_id}")
            # Set the user configuration
            resp = requests.post(f"{api_url}/config/{user_id}", json=payload, timeout=30)
            resp.raise_for_status()
            logger.info(f"Configuration set for user {user_id}")
            
            # Start the crawler for this user
            resp = requests.post(f"{api_url}/start/{user_id}", timeout=30)
            resp.raise_for_status()
            result = resp.json()
            logger.info(f"Started user {user_id}: {result['detail']}")
            
            # Then run a test crawl to ensure it starts immediately
            logger.info(f"Triggering immediate initial crawl for {user_id}")
            test_resp = requests.post(f"{api_url}/test/{user_id}", timeout=15)
            if test_resp.ok:
                logger.info(f"Initial crawl triggered for {user_id}")
            
            return True
        except Exception as e:
            logger.error(f"Error setting up user {user_id}: {str(e)}")
            return False

def main():
    parser = argparse.ArgumentParser(description="Start crawler for multiple users from JSON config")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="API URL (default: http://127.0.0.1:8000)")
    parser.add_argument("--config", default="/app/users.json", help="Path to users.json config file")
    parser.add_argument("--wait", type=int, default=5, help="Seconds to wait for API server to start")
    args = parser.parse_args()
    
    api_url = args.api
    config_file = args.config
    
    # Wait for the API to be available
    logger.info(f"Waiting {args.wait} seconds for API server to start...")
    time.sleep(args.wait)
    
    # Check if API is available
    max_retries = 5
    retry_delay = 3
    
    for i in range(max_retries):
        try:
            resp = requests.get(f"{api_url}/system/health", timeout=5)
            if resp.ok:
                logger.info("API server is up and running!")
                break
            logger.warning(f"API server not ready (attempt {i+1}/{max_retries})")
        except Exception as e:
            logger.warning(f"API server not ready: {str(e)} (attempt {i+1}/{max_retries})")
        
        if i < max_retries - 1:
            logger.info(f"Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)
    else:
        logger.error(f"API server at {api_url} is not responding after {max_retries} attempts")
        logger.error("Exiting...")
        return 1
    
    # Load user configurations
    try:
        logger.info(f"Loading user configurations from {config_file}")
        with open(config_file, 'r') as f:
            config_data = json.load(f)
        
        users = config_data.get('users', [])
        if not users:
            logger.error("No users found in configuration file")
            return 1
        
        logger.info(f"Found {len(users)} users in configuration")
        
        # Configure all users
        success_count = 0
        for user_config in users:
            if configure_user(api_url, user_config):
                success_count += 1
        
        logger.info(f"Successfully configured and started {success_count}/{len(users)} users")
        
        # Keep the script running to observe logs
        logger.info("All users configured. Crawler is running in the background.")
        logger.info("Press Ctrl+C to exit (container will continue running)")
        
        # Wait indefinitely (container will be kept alive by the FastAPI process)
        while True:
            time.sleep(3600)  # Sleep for an hour - this is just to keep the script alive
            
    except KeyboardInterrupt:
        logger.info("Startup script exiting. Crawler will continue running.")
        return 0
    except FileNotFoundError:
        logger.error(f"Configuration file not found: {config_file}")
        return 1
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in configuration file: {config_file}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())