# IntricCrawlerScript

A scheduled website crawler with enhanced error handling and status monitoring.

## Features
- Scheduled crawling at configurable intervals
- Website filtering capabilities
- Detailed logging and error handling
- Status monitoring with configurable check intervals
- API integration with automatic retries

## Installation

1. Clone the repository:
```bash
git clone https://github.com/CCimen/IntricCrawlerScript.git
cd IntricCrawlerScript
```

2. Install requirements:
```bash
pip install -r requirements.txt
```

3. Configure your environment:
```bash
cp .example.env .env
nano .env  # Edit with your configuration
```

## Configuration

Rename `.example.env` to `.env` and configure:

```env
# Required
API_KEY=xxxxx

BASE_URL=https://sundsvall.backend.intric.ai/api/v1

# How often it should run the crawler in minutes
SCHEDULE_MINUTES=5

# Enter the URL(s) of the website(s) you want to crawl
# Separate multiple websites with commas
WEBSITE_FILTER=https://sundsvall.se/nyheter/nyhetsarkiv/2025-01-22-har-iordningstalls-ny-lokal-vid-hallplats-stenstan---ett-varmt-valkomnande-i-vinterkylan
```

## Usage

Run in test mode (single execution):
```bash
python crawler.py --test
```

Run as a scheduled service:
```bash
python crawler.py
```

## Deployment

For Linux servers, use the included `deploy.sh` script:

1. Make the script executable:
```bash
chmod +x deploy.sh
```

2. Run the deployment:
```bash
./deploy.sh
```

The deployment script will:
- Create a systemd service
- Set up logging
- Configure automatic restarts
- Enable the service to start on boot

## Requirements

See `requirements.txt` for Python package dependencies.

## License

MIT License - See LICENSE file for details.
