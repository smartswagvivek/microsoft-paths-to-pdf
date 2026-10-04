"""Validate export settings and manage one background export at a time."""
import json
import os
import logging
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from exporter import FONT_STACKS, input_urls

ROOT = Path(__file__).resolve().parent
if os.name == "nt":
    default_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "Learnfolio/data"
else:
    default_data = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "learnfolio/data"
DATA = Path(os.environ.get("DATA_DIR", str(default_data))).resolve()
EXPORTS = DATA / "exports"
FILES = {"pdf": ("combined_lessons.pdf", "application/pdf"),
         "html": ("combined_lessons.html", "text/html; charset=utf-8"),
         "report": ("extraction_report.json", "application/json")}
RETENTION_SECONDS = 3600


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def validate(data):
    if not isinstance(data, dict):
        raise ValueError("Please send an export configuration.")
    urls = data.get("urls", "")
    if not isinstance(urls, str):
        raise ValueError("Paste one learning-path or module URL per line.")
    config = {"urls": input_urls(urls)}
    for key, default, choices in (
        ("paper", "A4", ("A4", "Letter")),
        ("font", "Times New Roman", tuple(FONT_STACKS)),
        ("font_size", 12, (10, 11, 12, 13, 14)), ("line_height", 1.5, (1.2, 1.35, 1.5)),
    ):
        value = data.get(key, default)
        if isinstance(value, bool) or value not in choices:
            raise ValueError(f"Invalid {key.replace('_', ' ')}.")
        config[key] = value
    for key, default in (("images", True), ("unit_break", False), ("allow_partial", False)):
        value = data.get(key, default)
        if not isinstance(value, bool):
            raise ValueError(f"Invalid {key} option.")
        config[key] = value
    for key in ("title", "selector"):
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > 500:
            raise ValueError(f"{key.capitalize()} must be under 500 characters.")
        config[key] = value.strip()
    delay = data.get("delay", 1.0)
    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not 0.5 <= delay <= 5:
        raise ValueError("Request spacing must be between 0.5 and 5 seconds.")
    config["delay"] = delay
    return config


class Jobs:
    def __init__(self):
        self.lock = threading.RLock()
        self.items = {}
        self.active = None
        self.pending_deletion = set()
        self.wake_cleanup = threading.Event()
        self.closed = threading.Event()
        for path in EXPORTS.glob("*/state.json"):
            try:
                if not re.fullmatch(r"[0-9a-f]{32}", path.parent.name) or path.parent.resolve().parent != EXPORTS.resolve():
                    continue
                job = json.loads(path.read_text(encoding="utf-8"))
                if job["id"] != path.parent.name:
                    continue
                if job["status"] == "running":
                    job.update(status="failed", error="The server stopped during this export. Please try again.")
                # Legacy and interrupted exports retain their original age across restarts.
                if not job.get("expires_at"):
                    started = timestamp(job.get("completed_at") or job["created_at"])
                    job["expires_at"] = datetime.fromtimestamp(started + RETENTION_SECONDS, timezone.utc).isoformat()
                timestamp(job["expires_at"])
                self.items[job["id"]] = job
            except (ValueError, KeyError, TypeError, OSError):
                continue
        self.cleanup()
        self.cleaner = threading.Thread(target=self._cleanup_loop, daemon=True, name="export-expiry")
        self.cleaner.start()

    def close(self):
        self.closed.set()
        self.wake_cleanup.set()
        self.cleaner.join(timeout=5)

    def _cleanup_loop(self):
        while not self.closed.is_set():
            self.wake_cleanup.clear()
            self.cleanup()
            with self.lock:
                deadlines = [timestamp(job["expires_at"]) for job in self.items.values() if job.get("expires_at")]
            delay = min(60, max(1, min(deadlines) - time.time())) if deadlines else 60
            self.wake_cleanup.wait(delay)

    def cleanup(self):
        """Remove expired folders and memory, including incomplete/orphaned output."""
        with self.lock:
            now = time.time()
            for job_id, job in list(self.items.items()):
                if job_id != self.active and job.get("expires_at") and timestamp(job["expires_at"]) <= now:
                    # Expired data is inaccessible even if Windows temporarily locks a file.
                    del self.items[job_id]
                    self.pending_deletion.add(job_id)
            try:
                folders = list(EXPORTS.iterdir()) if EXPORTS.exists() else []
                self.pending_deletion.intersection_update(folder.name for folder in folders)
                for folder in folders:
                    if not re.fullmatch(r"[0-9a-f]{32}", folder.name) or folder.name == self.active:
                        continue
                    if folder.resolve().parent != EXPORTS.resolve() or not folder.is_dir():
                        continue
                    job = self.items.get(folder.name)
                    if job:
                        continue
                    state_file = folder / "state.json"
                    try:
                        state = json.loads(state_file.read_text(encoding="utf-8"))
                        if not isinstance(state, dict):
                            raise ValueError("Invalid export state")
                        expiry = timestamp(state["expires_at"]) if state.get("expires_at") else timestamp(state["created_at"]) + RETENTION_SECONDS
                    except (ValueError, KeyError, TypeError, OSError):
                        expiry = folder.stat().st_mtime + RETENTION_SECONDS
                    if folder.name in self.pending_deletion or expiry <= now:
                        self.pending_deletion.add(folder.name)
                        try:
                            shutil.rmtree(folder)
                            self.pending_deletion.discard(folder.name)
                        except OSError:
                            logging.exception("Could not delete expired export %s; cleanup will retry", folder.name)
            except OSError:
                logging.exception("Could not scan export storage; cleanup will retry")

    def save(self, job):
        path = EXPORTS / job["id"] / "state.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        for attempt in range(6):
            try:
                temp.replace(path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.1 * (attempt + 1))

    def snapshot(self, job_id):
        with self.lock:
            self.cleanup()
            job = self.items.get(job_id)
            return json.loads(json.dumps(job)) if job else None

    def history(self, owner=None):
        with self.lock:
            self.cleanup()
            return [{k: j.get(k) for k in ("id", "title", "created_at", "expires_at", "status", "summary")}
                    for j in sorted((j for j in self.items.values() if owner is None or j.get("owner", "local") == owner),
                                    key=lambda j: j["created_at"], reverse=True)[:30]]

    def start(self, config, owner="local"):
        with self.lock:
            if self.active:
                raise RuntimeError("An export is already running. Wait for it to finish.")
            job_id = uuid.uuid4().hex
            folder = EXPORTS / job_id
            folder.mkdir(parents=True)
            (folder / "job.json").write_text(json.dumps(config), encoding="utf-8")
            job = {"id": job_id, "owner": owner, "title": config["title"] or "Microsoft Learn export",
                   "created_at": datetime.now(timezone.utc).isoformat(), "status": "running",
                   "progress": 0, "message": "Opening Microsoft Learn…", "logs": [],
                   "summary": {}, "warnings": [], "errors": [], "downloads": [], "error": ""}
            self.items[job_id] = job
            self.active = job_id
            self.save(job)
            threading.Thread(target=self.run, args=(job_id,), daemon=True).start()
            return job_id

    def run(self, job_id):
        folder = EXPORTS / job_id
        job = self.items[job_id]
        try:
            with subprocess.Popen(
                [sys.executable, "-u", str(ROOT / "exporter.py"), "--worker", str(folder / "job.json")],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ) as process, (folder / "execution.log").open("w", encoding="utf-8") as log:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    try:
                        event = json.loads(line)
                    except ValueError:
                        event = {"type": "log", "message": line.strip()}
                    with self.lock:
                        message = event.get("message", "")
                        job["logs"].append(message)
                        job["logs"] = job["logs"][-1500:]
                        if event.get("type") == "progress":
                            job["progress"] = event.get("fraction", 0)
                            job["message"] = message
                        elif event.get("type") == "error":
                            job["error"] = message
                        elif event.get("type") == "warning":
                            job["warnings"].append({"message": message})
                code = process.wait()
            report_path = folder / "extraction_report.json"
            report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
            with self.lock:
                job.update({key: report[key] for key in ("title", "summary", "warnings", "errors") if key in report})
                success = code == 0 and (folder / "combined_lessons.pdf").is_file()
                job["status"] = report.get("status", "captured") if success else "failed"
                job["message"] = "Your study copy is ready." if success else "Export could not be completed."
                job["error"] = "" if success else report.get("fatal_error") or job["error"] or f"Worker exited with code {code}."
                job["progress"] = 1 if success else job["progress"]
                job["downloads"] = [key for key, (name, _) in FILES.items()
                                    if (folder / name).is_file() and (key != "pdf" or success)]
        except Exception as exc:
            with self.lock:
                job.update(status="failed", error=str(exc), message="Export could not be completed.")
        finally:
            with self.lock:
                completed = datetime.now(timezone.utc)
                job["completed_at"] = completed.isoformat()
                job["expires_at"] = (completed + timedelta(seconds=RETENTION_SECONDS)).isoformat()
                self.active = None
                try:
                    self.save(job)
                finally:
                    self.wake_cleanup.set()
