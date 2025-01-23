#!/bin/bash
# Usage: ./deploy.sh /opt/crawler

TARGET_DIR=${1:-/opt/crawler}

# Create directory
sudo mkdir -p $TARGET_DIR
sudo chown -R $USER:$USER $TARGET_DIR

# Copy files
cp {crawler.py,requirements.txt,.env} $TARGET_DIR

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
python3 -m venv $TARGET_DIR/venv
$TARGET_DIR/venv/bin/pip install -r $TARGET_DIR/requirements.txt

# Secure permissions
chmod 600 $TARGET_DIR/.env

# Reload systemd
sudo systemctl daemon-reload
sudo systemctl enable crawler
sudo systemctl start crawler

echo "Deployment complete. Manage with:"
echo "sudo systemctl status crawler"
echo "sudo journalctl -u crawler -f"