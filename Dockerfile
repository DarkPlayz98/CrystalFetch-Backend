FROM python:3.11-slim

# Install ffmpeg (Required for yt-dlp to work!)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
RUN mkdir -p downloads

# Render will provide its own PORT, but we set a default just in case
ENV PORT=10000 

# Run gunicorn using Render's port
CMD sh -c "gunicorn -b 0.0.0.0:${PORT} app:app"
