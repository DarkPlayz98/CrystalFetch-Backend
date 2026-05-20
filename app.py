from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import uuid
import threading
import subprocess
import shutil
import mimetypes
import requests
from pathlib import Path
from urllib.parse import urlparse


app = Flask(__name__)
CORS(app)


BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)


JOBS = {}
LOCK = threading.Lock()




def set_job(job_id, **fields):
    with LOCK:
        if job_id not in JOBS:
            JOBS[job_id] = {}
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




def guess_extension(url, content_type, fallback="mp4"):
    path_ext = Path(urlparse(url).path).suffix.lstrip(".")
    if path_ext:
        return path_ext


    if content_type:
        mime = content_type.split(";")[0].strip().lower()
        guessed = mimetypes.guess_extension(mime)
        if guessed:
            return guessed.lstrip(".")


    return fallback




def download_to_path(url, path):
    with requests.get(url, stream=True, timeout=60, allow_redirects=True) as r:
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "")


        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)


    return content_type




def process_job(job_id, url, fmt):
    raw_tmp = DOWNLOAD_DIR / f"{job_id}.download"


    try:
        set_job(job_id, status="processing", message="Downloading...", filename=None, download_url=None)


        content_type = download_to_path(url, raw_tmp)


        if fmt == "mp3":
            if shutil.which("ffmpeg") is None:
                raise RuntimeError("ffmpeg is not installed on the server.")


            out_path = DOWNLOAD_DIR / f"{job_id}.mp3"
            set_job(job_id, message="Converting to MP3...")


            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(raw_tmp),
                    "-vn",
                    "-codec:a", "libmp3lame",
                    "-q:a", "2",
                    str(out_path)
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )


            raw_tmp.unlink(missing_ok=True)


        else:
            ext = guess_extension(url, content_type, fallback="mp4")
            out_path = DOWNLOAD_DIR / f"{job_id}.{ext}"
            raw_tmp.replace(out_path)


        set_job(
            job_id,
            status="done",
            message="Ready",
            filename=out_path.name,
            download_url=f"/files/{out_path.name}"
        )


    except Exception as e:
        try:
            raw_tmp.unlink(missing_ok=True)
        except Exception:
            pass


        set_job(job_id, status="error", message=str(e))




@app.get("/")
def home():
    return "CrystalFetch backend is running."




@app.get("/api/health")
def health():
    return jsonify(ok=True)




@app.post("/api/job")
def create_job():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    fmt = (data.get("format") or "mp4").strip().lower()


    if fmt not in ("mp4", "mp3"):
        return jsonify(ok=False, error="format must be mp4 or mp3"), 400


    if not valid_http_url(url):
        return jsonify(ok=False, error="Enter a valid http/https direct media URL."), 400


    job_id = uuid.uuid4().hex
    set_job(job_id, status="queued", message="Queued", filename=None, download_url=None)


    thread = threading.Thread(target=process_job, args=(job_id, url, fmt), daemon=True)
    thread.start()


    return jsonify(ok=True, job_id=job_id)




@app.get("/api/job/<job_id>")
def job_status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify(ok=False, error="Job not found"), 404


    return jsonify(ok=True, job_id=job_id, **job)




@app.get("/files/<path:filename>")
def files(filename):
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)




if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)