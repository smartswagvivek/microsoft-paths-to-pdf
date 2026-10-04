"""Learnfolio API. Run one instance; export jobs and history share one data directory."""
import os
import re
import secrets
import subprocess
import sys
import threading
from datetime import datetime, timezone
from urllib.parse import urlsplit

from flask import Flask, g, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

from jobs import EXPORTS, FILES, ROOT, Jobs, validate


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 32768
    key = os.environ.get("API_KEY", "")
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8501"))
    if host not in ("127.0.0.1", "localhost", "::1") and len(key) < 32:
        raise ValueError("Set API_KEY to a random secret of at least 32 characters before hosting publicly.")
    origins = {value.strip().rstrip("/") for value in os.environ.get(
        "ALLOWED_ORIGINS", f"http://127.0.0.1:{port},http://localhost:{port}"
    ).split(",") if value.strip()}
    for origin in origins:
        parsed = urlsplit(origin)
        if (parsed.scheme not in ("https", "http") or not parsed.netloc or "*" in origin
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("ALLOWED_ORIGINS must contain exact origins, without paths or wildcards.")
    if not key:
        app.config["TRUSTED_HOSTS"] = ["127.0.0.1", "localhost", "[::1]"]
    jobs = Jobs()
    app.extensions["jobs"] = jobs
    preview_lock = threading.Lock()

    @app.before_request
    def authorize():
        origin = request.headers.get("Origin")
        if origin and origin not in origins:
            return jsonify(error="This website is not in the backend's ALLOWED_ORIGINS."), 403
        if request.method == "OPTIONS":
            return "", 204
        protected = request.path.startswith(("/api/", "/files/", "/preview/"))
        if protected and request.path != "/api/health" and key:
            supplied = request.headers.get("Authorization", "")
            if not secrets.compare_digest(supplied.encode(), ("Bearer " + key).encode()):
                return jsonify(error="Backend authentication failed."), 401
            workspace = request.headers.get("X-Workspace-ID", "")
            if not re.fullmatch(r"[a-f0-9]{32}", workspace):
                return jsonify(error="A valid workspace is required."), 403
            g.workspace = workspace
        else:
            g.workspace = "local"
        if request.method == "POST" and not key and not origin:
            return jsonify(error="Local exports must be submitted from the Learnfolio website."), 403

    @app.after_request
    def response_headers(response):
        origin = request.headers.get("Origin")
        if origin in origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Learnfolio-Isolation"] = "workspace-v1"
        # HTML exports are downloads. Sandbox them if a browser opens one directly.
        if request.path.startswith("/files/"):
            response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src data:; font-src data:; style-src 'unsafe-inline'"
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", app="learnfolio")

    @app.get("/api/state")
    def state():
        with jobs.lock:
            history = jobs.history(owner=g.workspace)
            active = jobs.active if jobs.active and owned_job(jobs.active) else None
            return jsonify(active=active, busy=bool(jobs.active), history=history,
                           server_time=datetime.now(timezone.utc).isoformat())

    def owned_job(job_id):
        job = jobs.snapshot(job_id)
        return job if job and job.get("owner", "local") == g.workspace else None

    @app.post("/api/jobs")
    def start_job():
        try:
            return jsonify(id=jobs.start(validate(request.get_json()), owner=g.workspace)), 202
        except (ValueError, TypeError) as error:
            return jsonify(error=str(error)), 400
        except RuntimeError as error:
            return jsonify(error=str(error)), 409

    @app.get("/api/jobs/<job_id>")
    def get_job(job_id):
        job = owned_job(job_id)
        return (jsonify(job), 200) if job else (jsonify(error="Export not found."), 404)

    @app.get("/files/<job_id>/<kind>")
    def download(job_id, kind):
        with jobs.lock:
            job = owned_job(job_id)
            if kind not in FILES or not job or kind not in job["downloads"]:
                return jsonify(error="File expired or is not available."), 404
            name, mime = FILES[kind]
            return send_file(EXPORTS / job_id / name, mimetype=mime, as_attachment=True, download_name=name)

    @app.get("/preview/<job_id>/<number>")
    def preview(job_id, number):
        job = owned_job(job_id)
        if not job or "pdf" not in job["downloads"]:
            return jsonify(error="Preview not available."), 404
        if number != "info" and (not number.isdigit() or not 1 <= int(number) <= 5000):
            return jsonify(error="Invalid page number."), 400
        cache = EXPORTS / job_id / ("preview-info.json" if number == "info" else f"preview-{int(number)}.png")
        with preview_lock:
            with jobs.lock:
                if not owned_job(job_id):
                    return jsonify(error="This export has expired."), 404
                if cache.exists():
                    return send_file(cache, mimetype="application/json" if number == "info" else "image/png")
            if not cache.exists():
                try:
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "preview.py"), str(EXPORTS / job_id / "combined_lessons.pdf"), number],
                        capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except subprocess.TimeoutExpired:
                    return jsonify(error="Preview timed out. Download the PDF to continue reading."), 504
                with jobs.lock:
                    if not owned_job(job_id):
                        return jsonify(error="This export has expired."), 404
                    if result.returncode:
                        return jsonify(error="This page could not be previewed. The PDF download is still available."), 400
                    cache.write_bytes(result.stdout)
                    return send_file(cache, mimetype="application/json" if number == "info" else "image/png")

    # Same files as GitHub Pages, for convenient local use. No directory browsing.
    @app.get("/")
    def index():
        return send_file(ROOT.parent / "frontend" / "index.html")

    @app.get("/assets/<name>")
    def asset(name):
        if name not in ("app.js", "app.css", "favicon.svg"):
            return jsonify(error="Not found."), 404
        return send_file(ROOT.parent / "frontend" / "assets" / name)

    @app.get("/assets/fonts/Oswald.ttf")
    def font():
        return send_file(ROOT.parent / "frontend/assets/fonts/Oswald.ttf", mimetype="font/ttf")

    return app


if __name__ == "__main__":
    from waitress import serve

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8501"))
    app = create_app()
    print(f"Learnfolio is running on http://{host}:{port}", flush=True)
    try:
        serve(app, host=host, port=port, threads=4)
    finally:
        app.extensions["jobs"].close()
