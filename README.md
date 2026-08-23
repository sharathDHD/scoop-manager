# Scoop Manager

A GUI for the [Scoop](https://scoop.sh/) package manager on Windows, in two flavours:

- **Desktop app** — Tkinter (`scoop_manager.py`)
- **Web app** — Flask (`sccop_manager_web.py`; filename typo kept to match git history), served from `templates/`

Both share all Scoop interaction through a single module: **`scoop_core.py`**.

## Features

- Search available apps (desktop caches results in `scoop_cache.json`; web uses the
  ScoopAppFetcher SQLite catalog with offline fallback)
- Install / uninstall apps
- **Update a single app** (`scoop update <name>`) via per-row *Update* button
- **Update all apps** (`scoop update *`) via *Update All*
- All long-running commands execute on background threads/processes so the UI stays responsive:
  - desktop: output streams into a log box at the bottom of the window
  - web: progress is exposed by the `/status` endpoint and rendered live in the status panel;
    action acknowledgements use Flask flash messages
- Correct installed-status detection: `scoop list --Json` is preferred (machine-readable),
  falling back to parsing the human-readable table. Matching is done case-insensitively on the
  exact name token, so `git` no longer falsely matches `gitignore`.

## Structure

| File | Purpose |
| --- | --- |
| `scoop_core.py` | Shared logic: command construction, subprocess execution (sync + async streaming), `scoop list` JSON/table parsing, installed-status matching |
| `scoop_manager.py` | Tkinter desktop app |
| `sccop_manager_web.py` | Flask web app |
| `templates/index.html`, `templates/base.html` | Web UI |
| `scoop_app_fetcher.py` | Fetches/caches the app catalog used by the web app |
| `test_scoop_core.py` | Unit tests for the shared logic |

## Running

Requires Windows with Scoop installed and on PATH.

```bat
:: Desktop app
python scoop_manager.py

:: Web app
pip install flask requests
python sccop_manager_web.py
```

## Tests

The shared logic is fully unit-tested without Windows or Scoop (subprocess is mocked):

```bash
python -m pytest test_scoop_core.py -v
```

Covers: command construction (search/install/uninstall/update/update-all/list),
JSON and table output parsing, JSON-first/table-fallback behaviour of `get_installed_apps`,
and status-matching edge cases (case differences, substring traps such as `git` vs `gitignore`).
