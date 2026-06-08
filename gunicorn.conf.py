import os

# Gunicorn configuration file
# This binds Gunicorn to the PORT environment variable provided by Railway at runtime,
# defaulting to 8080 if not set. This avoids shell expansion issues in Dockerfile CMD.

port = os.environ.get("PORT", "8080")
bind = f"0.0.0.0:{port}"

# Production configurations
workers = 2
threads = 4
timeout = 120
