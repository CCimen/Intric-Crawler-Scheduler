#!/bin/bash
# Usage: ./deploy.sh /opt/crawler

# Error handling and validation
cleanup() {
    echo "Cleaning up failed deployment..."
    sudo rm -rf $TARGET_DIR
    sudo rm -f /etc/systemd/system/crawler.service
    exit 1
}
trap cleanup ERR

# Validate target directory
TARGET_DIR=${1:-$(pwd)/deployment}
if [ ! -w $(dirname $TARGET_DIR) ]; then
    echo "Error: Cannot write to target directory" >&2
    exit 1
fi

# Check for required commands
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is required but not installed" >&2
    exit 1
fi

if ! command -v systemctl &> /dev/null; then
    echo "Systemd is required but not found" >&2
    exit 1
fi

# Verify .env exists
if [ ! -f .env ]; then
    echo "Error: .env file not found" >&2
    exit 1
fi

# Create directory
if ! mkdir -p $TARGET_DIR; then
    echo "Error: Failed to create target directory" >&2
    exit 1
fi

# Copy files
if ! cp {crawler.py,requirements.txt,.env} $TARGET_DIR; then
    echo "Error: Failed to copy files" >&2
    exit 1
fi

# Create systemd service
mkdir -p $TARGET_DIR/systemd
tee $TARGET_DIR/systemd/crawler.service <<EOF
[Unit]
Description=Website Crawler Service
After=network.target

[Service]
User=$USER
WorkingDirectory=$TARGET_DIR
ExecStart=$TARGET_DIR/venv/bin/python $TARGET_DIR/crawler.py
Restart=always
Environment="PATH=$TARGET_DIR/venv/bin:/usr/bin"

[Install]
WantedBy=multi-user.target
EOF

# Check for venv capability
if ! python3 -c "import ensurepip" &> /dev/null; then
    echo "Python venv module is not available"
    echo "Attempting to install python3-venv..."
    
    if command -v apt &> /dev/null; then
        if sudo apt update && sudo apt install -y python3-venv; then
            echo "python3-venv installed successfully"
        else
            echo "Error: Failed to install python3-venv" >&2
            echo "Please install it manually with:" >&2
            echo "sudo apt install python3-venv" >&2
            exit 1
        fi
    else
        echo "Error: Could not detect apt package manager" >&2
        echo "Please install python3-venv using your system's package manager" >&2
        exit 1
    fi
fi

# Setup virtual environment
echo "Creating virtual environment..."
if ! python3 -m venv $TARGET_DIR/venv; then
    echo "Error: Failed to create virtual environment" >&2
    echo "This might be due to missing python3-venv package" >&2
    echo "On Debian/Ubuntu systems, install it with:" >&2
    echo "sudo apt install python3-venv" >&2
    exit 1
fi

if ! $TARGET_DIR/venv/bin/pip install -r $TARGET_DIR/requirements.txt; then
    echo "Error: Failed to install requirements" >&2
    exit 1
fi

# Secure permissions
chmod 600 $TARGET_DIR/.env

echo -e "\n\033[1;36m=== Deployment Instructions ===\033[0m"
echo -e "\033[1;36mSystemd service file created at $TARGET_DIR/systemd/crawler.service\033[0m"
echo -e "\n\033[1;36mTo enable the service, run these commands:\033[0m"
echo -e "\033[1;36m1. sudo cp $TARGET_DIR/systemd/crawler.service /etc/systemd/system/\033[0m"
echo -e "\033[1;36m2. sudo systemctl daemon-reload\033[0m"
echo -e "\033[1;36m3. sudo systemctl enable crawler\033[0m"
echo -e "\033[1;36m4. sudo systemctl start crawler\033[0m"

echo -e "\n\033[1;36m=== Management Commands ===\033[0m"
echo -e "\033[1;36m• Check status: sudo systemctl status crawler\033[0m"
echo -e "\033[1;36m• View logs: sudo journalctl -u crawler -f\033[0m"
echo -e "\033[1;36m\nDeployment complete!\033[0m"
