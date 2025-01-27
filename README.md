# IntricCrawlerScript

A scheduled website crawler with enhanced error handling and status monitoring.

## Features

- **Individual Website Scheduling**: Each website is crawled according to its own interval, so a long-running crawl on one site **doesn't block others**.
- **Configurable scheduling** at fixed intervals (via `SCHEDULE_MINUTES`)
- **Website filtering** capabilities
- **Detailed logging** and error handling
- **Status monitoring** with configurable check intervals
- **API integration** with automatic retries

---

## Requirements

- **Python 3** (with `python3-venv` installed for virtual environments)
- **systemd** (for deployment on most modern Linux distros)
- **pip** (to install Python packages)
- For local usage: Ability to create and activate a virtual environment (`venv`)
- For server deployment: Sufficient permissions to write to the target directory (e.g. `/opt/crawler` or any user-owned folder like `~/crawler`)

---

## Configuration

All application settings reside in a `.env` file. A sample configuration is provided:

```bash
cp .example.env .env
nano .env
```

The `.env` file holds necessary environment variables:

```env
# Required
API_KEY=xxxxx
BASE_URL=https://sundsvall.backend.intric.ai/api/v1

# How often to run the crawler (in minutes)
SCHEDULE_MINUTES=5

# Websites to crawl (comma-separated)
WEBSITE_FILTER=https://sundsvall1.se,https://sundsvall2.se
```

> **Note:** 
> - Make sure your API key follows the expected format (if your code checks that it starts with `inp_`).  
> - Adjust the `BASE_URL`, `SCHEDULE_MINUTES`, and `WEBSITE_FILTER` as needed.
> - **Multiple URLs**: Separate them with commas. The script will create **individual** scheduled jobs for each site.

---

## Quick Start (Local Development)

> **Important:** Modern Linux distributions often protect the system Python installation. Installing packages with `pip` at the system level can trigger "externally-managed-environment" errors. Instead, use a **virtual environment**.

1. **Clone the repository**:
    ```bash
    git clone https://github.com/CCimen/IntricCrawlerScript.git
    cd IntricCrawlerScript
    ```

2. **Create and activate a virtual environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
    - If `python3-venv` isn’t available, install it (e.g., on Ubuntu/Debian):
      ```bash
      sudo apt update
      sudo apt install python3-venv
      ```

3. **Install Python dependencies**:
    ```bash
    pip install --upgrade pip  # optional but recommended
    pip install -r requirements.txt
    ```

4. **Set up your environment (.env file)**:
    ```bash
    cp .example.env .env
    nano .env  # Edit your configuration
    ```

5. **Test the script locally**:
    - **Single (test) execution**:
      ```bash
      python crawler.py --test
      ```
      > This runs the crawler **once** for each website in your `.env` and exits.
    - **Scheduled crawling**:
      ```bash
      python crawler.py
      ```
      > Each website is scheduled **separately** at the interval in `SCHEDULE_MINUTES`. Long-running crawls for one site will not block shorter crawls for others.

6. **Deactivate the virtual environment** (when done):
    ```bash
    deactivate
    ```

---

## Usage

- **Single execution** (test mode):
  ```bash
  python crawler.py --test
  ```
  Runs each matched website once in series, then exits.
- **Scheduled mode**:
  ```bash
  python crawler.py
  ```
  Creates a background scheduler that spawns **one job per website**. Each site runs at the configured interval (`SCHEDULE_MINUTES`). If a site’s crawl is still in progress when its next slot arrives, that site’s new crawl is deferred until the previous one completes. Other sites remain unaffected and run on schedule.

Once deployed as a systemd service (see below), the crawler automatically runs in the background on the schedule defined by `SCHEDULE_MINUTES`.

---

## Deployment (Linux Server)

For production use, you can deploy this script as a systemd service with the included `deploy.sh` script. This script will:

- Copy your `crawler.py`, `requirements.txt`, and `.env` to the target directory
- Create a **virtual environment** in that directory
- Install the required Python packages
- Generate a systemd service unit file

1. **Ensure you have prerequisites**:
    ```bash
    sudo apt update
    sudo apt install python3 python3-venv
    # systemd is usually installed by default on most distros
    ```

2. **Clone the repository** (if not already cloned):
    ```bash
    git clone https://github.com/CCimen/IntricCrawlerScript.git
    cd IntricCrawlerScript
    ```

3. **Prepare `.env`** (see [Configuration](#configuration)):
    ```bash
    cp .example.env .env
    nano .env
    ```

4. **Run the deployment script**:
    ```bash
    chmod +x deploy.sh
    ./deploy.sh ~/crawler
    ```
    - You can specify a custom path (e.g., `/opt/crawler`). By default, it uses a `deployment` folder in your current directory.
    - **Note**: If you choose `/opt/crawler` or another directory outside your user’s home, ensure you have **write permissions** there (or create and change ownership beforehand). Otherwise, the script will fail with “Cannot write to target directory.”

5. **Enable and start the service**:
    1. **Copy the generated service file** into `/etc/systemd/system`:
        ```bash
        sudo cp ~/crawler/systemd/crawler.service /etc/systemd/system/
        ```
    2. **Reload systemd**:
        ```bash
        sudo systemctl daemon-reload
        ```
    3. **Enable** the service (starts on system boot):
        ```bash
        sudo systemctl enable crawler
        ```
    4. **Start** the service:
        ```bash
        sudo systemctl start crawler
        ```

6. **Check status and logs**:
    - **Service status**:
      ```bash
      sudo systemctl status crawler
      ```
    - **View logs** (follow mode):
      ```bash
      sudo journalctl -u crawler -f
      ```

After this, the **systemd service** runs in the background. Each website listed in your `WEBSITE_FILTER` will be crawled on its own schedule (every `SCHEDULE_MINUTES`).

---

## License

MIT License - See [LICENSE](LICENSE) for details.
