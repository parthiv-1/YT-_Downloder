# Use Python 3.11 slim image
FROM python:3.11-slim

# Install system dependencies (FFmpeg and Node.js)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Run the application with gunicorn, binding to the PORT environment variable provided by Railway
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT yd.app:app"]
