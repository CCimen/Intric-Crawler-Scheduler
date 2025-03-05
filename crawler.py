#!/usr/bin/env python3
"""
Simplified crawler script that can be run directly without UI.
This script will create a user from environment variables and start crawling.
"""

import os
import sys
import argparse
import logging
import requests
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Run the crawler with minimal resources")
    parser.add_argument("--test", action="store_true", help="Run in test mode (one-time crawl)")
    parser.add_argument("--user", default="default_user", help="User ID to use (default: default_user)")
    parser.add_argument("--port", type=int, default=8000, help="Port for the FastAPI server (default: 8000)")
    args = parser.parse_args()
    
    api_url = f"http://localhost:{args.port}"
    user_id = args.user
    test_mode = args.test
    
    load_dotenv()  # Load environment variables from .env file
    
    # Verify we have the required environment variables
    if not os.getenv('API_KEY'):
        logger.error("Missing API_KEY in environment variables")
        logger.error("Please set API_KEY in your .env file")
        return 1
        
    if not (os.getenv('SPACE_ID') or os.getenv('SPACE_NAME')):
        logger.error("Missing SPACE_ID or SPACE_NAME in environment variables")
        logger.error("Please set either SPACE_ID or SPACE_NAME in your .env file")
        return 1
    
    logger.info(f"Setting up user '{user_id}' from environment variables")
    logger.info(f"Space: {os.getenv('SPACE_NAME') or os.getenv('SPACE_ID')}")
    
    # Check if API server is running
    try:
        response = requests.get(f"{api_url}/system/health", timeout=2)
        if not response.ok:
            logger.error(f"API server at {api_url} is not responding correctly")
            logger.error(f"Please start the server with: uvicorn main:app --host 0.0.0.0 --port {args.port}")
            return 1
    except Exception as e:
        logger.error(f"Cannot connect to API server at {api_url}: {str(e)}")
        logger.error(f"Please start the server with: uvicorn main:app --host 0.0.0.0 --port {args.port}")
        return 1
    
    # Create user from environment variables
    try:
        response = requests.post(f"{api_url}/env_user/{user_id}")
        if not response.ok:
            error = response.json().get("detail", "Unknown error")
            logger.error(f"Failed to create user: {error}")
            return 1
        
        logger.info(f"User {user_id} created successfully")
        
        # Run in test mode or start scheduler
        if test_mode:
            logger.info("Running in test mode (one-time crawl)")
            response = requests.post(f"{api_url}/test/{user_id}")
        else:
            logger.info("Starting scheduled crawling")
            response = requests.post(f"{api_url}/start/{user_id}")
            
        if not response.ok:
            error = response.json().get("detail", "Unknown error")
            logger.error(f"Failed to start crawling: {error}")
            return 1
        
        result = response.json().get("detail", "")
        logger.info(result)
        
        if test_mode:
            logger.info("Test crawl initiated. Check logs for progress.")
        else:
            logger.info("Crawler is now running in the background.")
            logger.info(f"To check status: curl http://localhost:{args.port}/status/{user_id}")
            logger.info(f"To stop crawling: curl -X POST http://localhost:{args.port}/stop/{user_id}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())