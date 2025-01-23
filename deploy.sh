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
TARGET_DIR=${1:-/opt/crawler}
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
if ! sudo mkdir -p $TARGET_DIR; then
    echo "Error: Failed to create target directory" >&2
    exit 1
fi

if ! sudo chown -R $USER:$USER $TARGET_DIR; then
    echo "Error: Failed to set directory ownership" >&2
    exit 1
fi

# Copy files
if ! cp {crawler.py,requirements.txt,.env} $TARGET_DIR; then
    echo "Error: Failed to copy files" >&2
    exit 1
fi

# Create systemd service
sudo tee /etc/systemd/system/crawler.service <<EOF
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

# Setup virtual environment
if ! python3 -m venv $TARGET_DIR/venv; then
    echo "Error: Failed to create virtual environment" >&2
    exit 1
fi

if ! $TARGET_DIR/venv/bin/pip install -r $TARGET_DIR/requirements.txt; then
    echo "Error: Failed to install requirements" >&2
    exit 1
fi

# Secure permissions
chmod 600 $TARGET_DIR/.env

# Reload systemd
if ! sudo systemctl daemon-reload; then
    echo "Error: Failed to reload systemd" >&2
    exit 1
fi

if ! sudo systemctl enable crawler; then
    echo "Error: Failed to enable service" >&2
    exit 1
fi

if ! sudo systemctl start crawler; then
    echo "Error: Failed to start service" >&2
    exit 1
fi

echo "Deployment complete. Manage with:"
echo "sudo systemctl status crawler"
echo "sudo journalctl -u crawler -f"
