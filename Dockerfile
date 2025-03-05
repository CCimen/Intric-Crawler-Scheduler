FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application files
COPY main.py .
COPY startup.py .
COPY crawler.py .

# Make sure the startup script is executable
RUN chmod +x /app/startup.py

# Copy the default configuration file
COPY users.json .

# Default to production logging mode (can be overridden with environment variables)
ENV LOG_MODE=production
# Set the interval for checking for new websites (in minutes)
ENV WEBSITE_REFRESH_INTERVAL=5

# Document the ports
EXPOSE 8000

# More verbose logging for debugging and longer initial wait
CMD ["sh", "-c", "python -m uvicorn main:app --host 0.0.0.0 --port 8000 --log-level info & sleep 30 && python startup.py --wait 15 --api http://127.0.0.1:8000"]