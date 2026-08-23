"""Flask web version of the Scoop Manager GUI (filename typo kept for git history).

Serves templates/index.html which expects these endpoints:
  GET  /get_apps?page=&per_page=&search=
  POST /install_app | /uninstall_app | /update_app   {json: {"app_name": "..."}}
  POST /update_all
  GET  /status      -> background-job progress/log for polling clients
"""

import json
import os
import sqlite3
import threading

from flask import Flask, flash, get_flashed_messages, jsonify, render_template, request

import scoop_core
from scoop_app_fetcher import ScoopAppFetcher

FALLBACK_CACHE_FILE = "scoop_cache.json"

app = Flask(__name__)
app.secret_key = os.environ.get("SCOOP_MANAGER_SECRET", "scoop-manager-dev-key")

_fetcher = None
_fetcher_lock = threading.Lock()


def get_fetcher():
    global _fetcher
    with _fetcher_lock:
        if _fetcher is None:
            _fetcher = ScoopAppFetcher()
            try:
                _fetcher.update_data()
            except Exception:
                pass  # offline -> fall back to cache/catalog below
        return _fetcher


# ---------------------------------------------------------------------------
# Background job registry (one long-running scoop command at a time)
# ---------------------------------------------------------------------------

_job_lock = threading.Lock()
_job = {"running": False, "label": "", "log": [], "returncode": None}


def start_job(label, argv):
    """Start a scoop command in the background. Returns False if one is running."""
    with _job_lock:
        if _job["running"]:
            return False
        _job.update(running=True, label=label, log=[], returncode=None)

    def on_line(line):
        with _job_lock:
            _job["log"].append(line)

    def on_finish(returncode):
        with _job_lock:
            _job["returncode"] = returncode
            _job["running"] = False

    scoop_core.stream_scoop_async(argv, on_line=on_line, on_finish=on_finish)
    return True


# ---------------------------------------------------------------------------
# Catalog helpers
# ---------------------------------------------------------------------------

def load_fallback_catalog():
    """Offline fallback list of apps from the repo's scoop_cache.json."""
    try:
        with open(FALLBACK_CACHE_FILE, 'r') as cache_file:
            raw = json.load(cache_file)
        return [{
            "Name": entry.get("App Name", ""),
            "Description": entry.get("Description", ""),
            "Version": entry.get("Version", ""),
            "committed": "",
        } for entry in raw if isinstance(entry, dict)]
    except (OSError, ValueError):
        return []


def get_available_rows(page, per_page, search_query):
    """Rows for the available-apps table: DB first, cached catalog fallback."""
    columns = ["Name", "Description", "Version", "Committed"]
    rows = []
    try:
        rows = get_fetcher().get_apps_info_paginated(columns, page, per_page, search_query)
    except (sqlite3.Error, KeyError):
        rows = []
    normalized = [{
        "Name": row.get("Name", ""),
        "Description": row.get("Description", ""),
        "Version": row.get("Version", "") or "",
        "committed": str(row.get("Committed", "") or ""),
    } for row in rows]

    if normalized:
        return normalized

    catalog = load_fallback_catalog()
    if search_query:
        needle = search_query.lower()
        catalog = [entry for entry in catalog if needle in entry["Name"].lower()]
    offset = max(page - 1, 0) * per_page
    return catalog[offset:offset + per_page]


def get_installed_rows():
    """Normalized installed-app dicts; raises nothing."""
    try:
        return scoop_core.get_installed_apps()
    except scoop_core.ScoopError:
        return []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/get_apps")
def get_apps():
    try:
        page = max(int(request.args.get("page", 1)), 1)
        per_page = min(max(int(request.args.get("per_page", 50)), 1), 200)
    except ValueError:
        page, per_page = 1, 50
    search_query = request.args.get("search", "").strip()

    available = get_available_rows(page, per_page, search_query)
    installed = get_installed_rows()

    # Server-side status matching: case-insensitive exact name tokens,
    # never raw-line substring comparison.
    for entry in available:
        entry["status"] = "Installed" if scoop_core.is_installed(entry["Name"], installed) else "Available"

    return jsonify({
        "page": page,
        "installed_apps": [{
            "Name": row["name"],
            "Version": row.get("version", ""),
            "Source": row.get("source", ""),
            "Updated": row.get("updated", ""),
            "Info": row.get("info", ""),
        } for row in installed],
        "available_apps": available,
    })


def _run_action(action_label, argv_builder, app_name):
    if not app_name:
        return jsonify(message="Missing app_name"), 400
    if start_job(f"{action_label} {app_name}", argv_builder(app_name)):
        flash(f"Started {action_label.lower()}ing {app_name}", "info")
        return jsonify(message=f"{action_label} of {app_name} started")
    return jsonify(message="Another operation is already running. Check the status panel."), 409


@app.route("/install_app", methods=["POST"])
def install_app_route():
    data = request.get_json(silent=True) or {}
    return _run_action("Install", scoop_core.cmd_install, str(data.get("app_name", "")).strip())


@app.route("/uninstall_app", methods=["POST"])
def uninstall_app_route():
    data = request.get_json(silent=True) or {}
    return _run_action("Uninstall", scoop_core.cmd_uninstall, str(data.get("app_name", "")).strip())


@app.route("/update_app", methods=["POST"])
def update_app_route():
    data = request.get_json(silent=True) or {}
    return _run_action("Update", scoop_core.cmd_update, str(data.get("app_name", "")).strip())


@app.route("/update_all", methods=["POST"])
def update_all_route():
    if start_job("Update all apps", scoop_core.cmd_update_all()):
        flash("Started updating all installed apps", "info")
        return jsonify(message="Updating all apps...")
    return jsonify(message="Another operation is already running. Check the status panel."), 409


@app.route("/status")
def status():
    with _job_lock:
        snapshot = {
            "running": _job["running"],
            "label": _job["label"],
            "log": list(_job["log"]),
            "returncode": _job["returncode"],
        }
    messages = [{"category": category, "text": text}
                for category, text in get_flashed_messages(with_categories=True)]
    snapshot["messages"] = messages
    return jsonify(snapshot)


if __name__ == "__main__":
    app.run(debug=True)
