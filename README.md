# Intric Crawler Scheduler

A Docker-based scheduler that helps you automatically crawl websites in Intric spaces at configurable intervals.

## Overview

This application allows you to:

- Schedule crawls for multiple users' Intric spaces
- Configure different crawling intervals for each space
- Select specific websites within a space or crawl all websites
- Monitor crawling status through API and logs
- Automatically detect new websites added to your spaces

The scheduler communicates with the Intric API (`https://sundsvall.backend.intric.ai`) to initiate website crawls at defined intervals, helping keep your knowledge base up-to-date automatically.

## Installation

### Prerequisites

- Docker
- Docker Compose

### Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/CCimen/intric-crawler-scheduler.git
   cd intric-crawler-scheduler
   ```

2. Copy and edit the example users.json file:

   ```bash
   cp example-users.json users.json
   nano users.json  # Edit with your API keys and space configurations
   ```

3. Build and start the container:
   ```bash
   docker-compose build
   docker-compose up -d
   ```

## Configuration

### Users.json Structure

Configure the `users.json` file with your Intric API keys and spaces:

```json
{
  "users": [
    {
      "user_id": "user1",
      "api_key": "inp_your_api_key_here",
      "base_url": "https://sundsvall.backend.intric.ai/api/v1",
      "spaces": [
        {
          "space_name": "space-name",
          "schedule_minutes": 60,
          "website_filter": ["https://example.com", "https://example.org"],
          "crawl_all_space_websites": false
        },
        {
          "space_id": "space-id-string",
          "schedule_minutes": 120,
          "crawl_all_space_websites": true
        },
        {
          "space_name": "future-space",
          "schedule_minutes": 60,
          "website_filter": [],
          "crawl_all_space_websites": true
        }
      ]
    }
  ]
}
```

### Configuration Options

#### User Level Options

| Option   | Description                             |
| -------- | --------------------------------------- |
| user_id  | Unique identifier for the user          |
| api_key  | Your Intric API key (starts with inp\_) |
| base_url | Intric API base URL                     |
| spaces   | Array of space configurations           |

#### Space Level Options

| Option                   | Description                                   |
| ------------------------ | --------------------------------------------- |
| space_id                 | ID of the space to crawl                      |
| space_name               | Name of the space (alternative to space_id)   |
| schedule_minutes         | How often to run crawls (in minutes)          |
| website_filter           | List of specific websites to crawl (optional) |
| crawl_all_space_websites | If true, crawl all websites in the space      |

You must provide either `space_id` or `space_name` for each space.

### Future-Use Spaces

You can add spaces with no websites (empty spaces) to your configuration. The system will periodically check for new websites added to these spaces and automatically start crawling them. This lets you:

1. Configure spaces now that you plan to populate later
2. Add websites to spaces through the Intric interface
3. Have them automatically discovered and crawled without restarting

To control how often the system checks for new websites, adjust the `WEBSITE_REFRESH_INTERVAL` environment variable in your docker-compose.yml file.

## Usage

### Docker Commands

Start the service:

```bash
docker-compose up -d
```

Start with debug logging:

```bash
LOG_MODE=debug docker-compose up -d
```

View logs:

```bash
docker-compose logs -f
```

Restart after updating users.json:

```bash
docker-compose restart
```

Stop the service:

```bash
docker-compose down
```

### Logging Modes

The application supports two logging modes:

- **Production Mode (Default)**: Shows minimal logs with periodic status summaries

  ```bash
  LOG_MODE=production docker-compose up -d
  ```

- **Debug Mode**: Shows detailed logs for troubleshooting
  ```bash
  LOG_MODE=debug docker-compose up -d
  ```

### Web Interface

Access the API documentation:

```
http://localhost:8000/docs
```

This provides a Swagger UI where you can explore and test the API endpoints.

### Key API Endpoints

- `/config/{user_id}` - Set configuration for a user
- `/start/{user_id}` - Start crawling for a user
- `/stop/{user_id}` - Stop crawling for a user
- `/test/{user_id}` - Run a one-time crawl
- `/status/{user_id}` - Get status of a user's crawls
- `/system/status-summary` - Generate a status summary

## Monitoring

In production mode, the system logs a status summary every 5 minutes showing:

- Running crawls
- Completed crawls
- Failed crawls
- Last successful crawl time

View the status summary:

```bash
docker-compose logs -f | grep "CRAWLER STATUS SUMMARY" -A 50
```

## Environment Variables

These variables can be set in your docker-compose.yml file:

| Variable                 | Description                               | Default    |
| ------------------------ | ----------------------------------------- | ---------- |
| LOG_MODE                 | Logging mode (debug/production)           | production |
| WEBSITE_REFRESH_INTERVAL | Minutes between checking for new websites | 60         |
| TZ                       | Timezone for logs                         | UTC        |

Example docker-compose.yml snippet:

```yaml
environment:
  - TZ=Europe/Stockholm
  - LOG_MODE=production
  - WEBSITE_REFRESH_INTERVAL=60 # Check for new websites every 60 minutes
```

You can also modify these variables directly in the Dockerfile:

```dockerfile
ENV LOG_MODE=production
ENV WEBSITE_REFRESH_INTERVAL=60
```
