"""Shared Scoop logic used by both the Tkinter app and the Flask web app.

Contains:
  - pure command builders (search/install/uninstall/update/update-all/list)
  - subprocess execution helpers (sync + background streaming)
  - parsing of `scoop list` output (JSON preferred, table fallback)
  - case-insensitive, exact-token installed-status matching

Nothing in here touches a GUI toolkit, so it can be unit tested on any OS.
"""

import json
import os
import shlex
import subprocess
import threading

SCOOP_TIMEOUT = 1800  # installs/updates can be slow


class ScoopError(RuntimeError):
    """Raised when a scoop command fails or its output cannot be parsed."""


# ---------------------------------------------------------------------------
# Command construction (pure functions)
# ---------------------------------------------------------------------------

def build_scoop_command(*args):
    """Return the argv list for a scoop subcommand, e.g. ['scoop', 'update', 'git']."""
    return ["scoop"] + [str(a) for a in args]


def cmd_search(query=""):
    return build_scoop_command("search", query) if query else build_scoop_command("search")


def cmd_install(app_name):
    return build_scoop_command("install", app_name)


def cmd_uninstall(app_name):
    return build_scoop_command("uninstall", app_name)


def cmd_update(app_name="*"):
    """`scoop update <name>`; '*' means every installed app."""
    return build_scoop_command("update", app_name)


def cmd_update_all():
    return build_scoop_command("update", "*")


def cmd_list(json_mode=False):
    return build_scoop_command("list", "--Json") if json_mode else build_scoop_command("list")


def format_shell_command(argv):
    """Join argv into a shell command string usable with shell=True."""
    if os.name == "nt":
        return subprocess.list2cmdline(list(argv))
    return shlex.join(argv)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_scoop_command(*args, timeout=SCOOP_TIMEOUT):
    """Run `scoop <args>` synchronously. Returns (returncode, stdout, stderr)."""
    command = format_shell_command(build_scoop_command(*args))
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return 127, "", "'scoop' was not found on PATH"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s: {command}"


def stream_scoop_async(args, on_line=None, on_finish=None):
    """Run `scoop <args>` in a daemon thread, streaming combined output line by line.

    on_line(str) fires per output line; on_finish(returncode) once at the end.
    Returns the started Thread so callers can join if they wish.
    """
    command = format_shell_command(list(args))

    def worker():
        returncode = 0
        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:
                text = line.rstrip("\r\n")
                if text and on_line:
                    on_line(text)
            returncode = proc.wait()
        except Exception as exc:  # noqa: BLE001 - surfaced to UI callback
            if on_line:
                on_line(f"error: {exc}")
            returncode = 1
        if on_finish:
            on_finish(returncode)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_TABLE_HEADER_TOKENS = {"name", "version", "source", "updated", "info"}


def _blank_row():
    return {"name": "", "version": "", "source": "", "updated": "", "info": ""}


def parse_installed_json(text):
    """Normalize `scoop list --Json` output.

    Scoop emits either a bare JSON array or an object like {"apps": [...]},
    with PascalCase keys (Name/Version/Source/Updated/Info) depending on
    version. Returns a list of normalized row dicts, or None if the text is
    not valid JSON.
    """
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if isinstance(data, dict):
        data = data.get("apps", [])
    if not isinstance(data, list):
        return None

    rows = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        lower = {str(k).lower(): v for k, v in entry.items()}
        name = str(lower.get("name", "") or "").strip()
        if not name:
            continue
        rows.append({
            "name": name,
            "version": str(lower.get("version", "") or "").strip(),
            "source": str(lower.get("source", "") or "").strip(),
            "updated": str(lower.get("updated", "") or "").strip(),
            "info": str(lower.get("info", "") or "").strip(),
        })
    return rows


def parse_installed_table(text):
    """Parse human-readable `scoop list` table output into normalized rows.

    Skips blank lines, dashed separator rules and the header row; takes the
    first whitespace-separated token as the app name (scoop manifest names
    never contain spaces).
    """
    rows = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        # Dashed separator rule lines such as '----- ------'
        if set(stripped) <= set("-= "):
            continue
        parts = stripped.split()
        if parts[0].lower() in _TABLE_HEADER_TOKENS and len(parts) > 1:
            continue
        if parts[0].lower() == "no" and "installed" in stripped.lower():
            continue  # e.g. 'No apps installed'
        row = _blank_row()
        row["name"] = parts[0]
        if len(parts) > 1:
            row["version"] = parts[1]
        if len(parts) > 2:
            row["source"] = parts[2]
        if len(parts) > 3:
            row["updated"] = parts[3]
        if len(parts) > 4:
            row["info"] = " ".join(parts[4:])
        rows.append(row)
    return rows


def get_installed_apps(runner=None):
    """Return installed apps as a list of normalized row dicts.

    Prefers machine-readable `scoop list --Json`; silently falls back to the
    plain table when the JSON flag is unsupported or the payload is not valid
    JSON. Raises ScoopError only when both attempts fail at the process level.
    """
    runner = runner or run_scoop_command

    rc, out, err = runner("list", "--Json")
    if rc == 0:
        parsed = parse_installed_json(out)
        if parsed is not None:
            return parsed

    rc, out, err = runner("list")
    if rc != 0:
        raise ScoopError((err.strip() or out.strip()) or "scoop list failed")
    return parse_installed_table(out)


# ---------------------------------------------------------------------------
# Installed-status matching
# ---------------------------------------------------------------------------

def installed_names(installed_apps):
    """Set of lowercase installed app names from normalized dicts or legacy strings."""
    names = set()
    for item in installed_apps or []:
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
        else:
            tokens = str(item).split()
            name = tokens[0] if tokens else ""
        if name:
            names.add(name.lower())
    return names


def is_installed(app_name, installed_apps):
    """Case-insensitive EXACT-token match.

    'git' must match 'Git' but never 'gitignore'; matching happens on the
    parsed name column, never on whole raw output lines.
    """
    wanted = str(app_name).strip().lower()
    return bool(wanted) and wanted in installed_names(installed_apps)


# ---------------------------------------------------------------------------
# High-level actions
# ---------------------------------------------------------------------------

def search_available_apps(query="", runner=None):
    runner = runner or run_scoop_command
    rc, out, err = runner(*cmd_search(query)[1:])
    if rc != 0:
        raise ScoopError(err.strip() or "scoop search failed")
    return [line for line in out.splitlines() if line.strip()]


def install_app(app_name, runner=None):
    return (runner or run_scoop_command)(*cmd_install(app_name)[1:])


def uninstall_app(app_name, runner=None):
    return (runner or run_scoop_command)(*cmd_uninstall(app_name)[1:])


def update_app(app_name, runner=None):
    return (runner or run_scoop_command)(*cmd_update(app_name)[1:])


def update_all(runner=None):
    return (runner or run_scoop_command)(*cmd_update_all()[1:])
