from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import uuid
import threading
import time
import yt_dlp
from pathlib import Path
from urllib.parse import urlparse

app = Flask(__name__)
CORS(app)

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

JOBS = {}
LOCK = threading.Lock()
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB limit

def set_job(job_id, **fields):
    with LOCK:
        if job_id not in JOBS:
            JOBS[job_id] = {'timestamp': time.time()}
        JOBS[job_id].update(fields)

def get_job(job_id):
    with LOCK:
        return dict(JOBS.get(job_id, {}))

def valid_http_url(url):
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

def process_job(job_id, url, fmt):
    try:
        set_job(job_id, status="processing", message="Extracting media...", filename=None, download_url=None)
        
        ydl_opts = {
            'outtmpl': str(DOWNLOAD_DIR / f"{job_id}.%(ext)s"),
            'noplaylist': True,
            'max_filesize': MAX_FILE_SIZE,
            'quiet': True,
            'no_warnings': True
        }

        if fmt == "mp3":
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
            expected_ext = 'mp3'
        else:
            ydl_opts.update({
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'merge_output_format': 'mp4',
            })
            expected_ext = 'mp4'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        final_path = DOWNLOAD_DIR / f"{job_id}.{expected_ext}"
        
        if not final_path.exists():
            downloaded_files = list(DOWNLOAD_DIR.glob(f"{job_id}.*"))
            if not downloaded_files:
                raise RuntimeError("Failed to process or download video.")
            final_path = downloaded_files[0]

        final_size = os.path.getsize(final_path) / (1024 * 1024) 

        set_job(
            job_id,
            status="done",
            message=f"Ready ({final_size:.1f} MB)",
            filename=final_path.name,
            download_url=f"/files/{final_path.name}"
        )

    except Exception as e:
        for f in DOWNLOAD_DIR.glob(f"{job_id}.*"):
            f.unlink(missing_ok=True)
            
        error_msg = str(e)
        if "Unsupported URL" in error_msg:
            error_msg = "Unsupported URL or private video."
        elif "max_filesize" in error_msg.lower():
            error_msg = "Video exceeds the 100MB limit."
            
        set_job(job_id, status="error", message=error_msg)

def cleanup_old_files():
    while True:
        time.sleep(1800)
        current_time = time.time()
        with LOCK:
            expired_jobs = [jid for jid, data in JOBS.items() if current_time - data.get('timestamp', current_time) > 3600]
            for jid in expired_jobs:
                filename = JOBS[jid].get('filename')
                if filename:
                    file_path = DOWNLOAD_DIR / filename
                    file_path.unlink(missing_ok=True)
                del JOBS[jid]

cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
cleanup_thread.start()

@app.get("/")
def home():
    return "CrystalFetch backend is running on Render."

@app.get("/api/health")
def health():
    return jsonify(ok=True)

@app.post("/api/job")
def create_job():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    fmt = (data.get("format") or "mp4").strip().lower()

    if fmt not in ("mp4", "mp3"):
        return jsonify(ok=False, error="Format must be MP4 or MP3"), 400
    if not valid_http_url(url):
        return jsonify(ok=False, error="Invalid URL. Enter a valid link."), 400

    job_id = uuid.uuid4().hex
    set_job(job_id, status="queued", message="Starting extractor...", filename=None, download_url=None)

    thread = threading.Thread(target=process_job, args=(job_id, url, fmt), daemon=True)
    thread.start()

    return jsonify(ok=True, job_id=job_id)

@app.get("/api/job/<job_id>")
def job_status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify(ok=False, error="Job expired or not found"), 404
    return jsonify(ok=True, job_id=job_id, **job)

@app.get("/files/<path:filename>")
def files(filename):
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)
    
