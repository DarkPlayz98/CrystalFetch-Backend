FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
RUN mkdir -p downloads

# Tell Render we are strictly using port 10000
EXPOSE 10000

# Bulletproof startup command without shell variables
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000"]
