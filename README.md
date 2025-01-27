# IntricCrawlerScript

A scheduled website crawler with enhanced error handling and status monitoring.

## Features

- Scheduled crawling at configurable intervals
- Website filtering capabilities
- Detailed logging and error handling
- Status monitoring with configurable check intervals
- API integration with automatic retries

---

## Quick Start (Local Development)

> **Important:** Modern Linux distributions often protect the system Python installation.  
> Installing packages with `pip` at the system level (without a virtual environment)  
> can cause conflicts and trigger errors like **"externally-managed-environment"**.

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
    - If you don’t have `python3-venv`, install it (for Ubuntu/Debian) with:
      ```bash
      sudo apt update
      sudo apt install python3-venv
      ```

3. **Install requirements**:
    ```bash
    pip install --upgrade pip  # optional but recommended
    pip install -r requirements.txt
    ```

4. **Configure your environment**:
    ```bash
    cp .example.env .env
    nano .env  # Edit .env with your configuration
    ```

5. **Test the script locally**:
    - **Single execution** (test mode):
      ```bash
      python crawler.py --test
      ```
    - **Scheduled crawling**:
      ```bash
      python crawler.py
      ```

6. **Deactivate the virtual environment** (when done):
    ```bash
    deactivate
    ```

---

## Deployment (Linux Server)

This project includes a deployment script, `deploy.sh`, which **automatically creates a virtual environment** in your deployment folder and sets up a systemd service. This way, you don’t have to worry about conflicts with the system Python.

1. **Make sure you have the required packages**:
    - **Python 3**, including the `venv` module:
      ```bash
      sudo apt update
      sudo apt install python3 python3-venv
      ```
    - **systemd** (most modern Linux distros include this by default).

2. **Clone the repository**:
    ```bash
    git clone https://github.com/CCimen/IntricCrawlerScript.git
    cd IntricCrawlerScript
    ```

3. **Create and configure `.env`**:
    ```bash
    cp .example.env .env
    nano .env  # Edit with your actual credentials/URLs
    ```

4. **Run the deployment script**:
    ```bash
    chmod +x deploy.sh
    ./deploy.sh /opt/crawler
    ```
    - You can provide a custom path (e.g., `/opt/crawler`); otherwise, it defaults to a `deployment` folder inside the current directory.
    - The script will:
      - Copy necessary files (`crawler.py`, `requirements.txt`, `.env`) into the target directory.
      - Create a **virtual environment** at `$TARGET_DIR/venv`.
      - Install the dependencies (`pip install -r requirements.txt`).
      - Generate a systemd service file in `$TARGET_DIR/systemd/crawler.service`.

5. **Enable and start the service**:
    1. **Copy the service file** to systemd:
        ```bash
        sudo cp /opt/crawler/systemd/crawler.service /etc/systemd/system/
        ```
    2. **Reload systemd**:
        ```bash
        sudo systemctl daemon-reload
        ```
    3. **Enable the service** (so it starts on boot):
        ```bash
        sudo systemctl enable crawler
        ```
    4. **Start the service**:
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

---

## Configuration

The `.env` file holds all necessary configuration variables:

```env
# Required
API_KEY=xxxxx
BASE_URL=https://sundsvall.backend.intric.ai/api/v1

# How often to run the crawler (in minutes)
SCHEDULE_MINUTES=5

# Websites to crawl (comma-separated)
WEBSITE_FILTER=https://sundsvall.se/nyheter/nyhetsarkiv/2025-01-22-har-iordningstalls-ny-lokal-vid-hallplats-stenstan---ett-varmt-valkomnande-i-vinterkylan
```

---

## Usage

- **Single execution** (test mode):
  ```bash
  python crawler.py --test
  ```
- **Scheduled mode**:
  ```bash
  python crawler.py
  ```

Once deployed as a systemd service, the crawler will run in the background according to the schedule defined in `SCHEDULE_MINUTES`.

---

## Requirements

All Python package dependencies are in `requirements.txt`:

```
requests>=2.31.0
python-dotenv>=1.0.0
apscheduler>=3.10.0
```

Use a **virtual environment** to avoid potential conflicts with the system Python (PEP 668).

---

## License

MIT License - See [LICENSE](LICENSE) file for details.
