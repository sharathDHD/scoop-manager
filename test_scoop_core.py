"""Tests for scoop_core — no Windows/scoop required, all subprocess calls mocked."""

import json
import subprocess
import threading

import pytest

import scoop_core


# ---------------------------------------------------------------------------
# Command construction
# ---------------------------------------------------------------------------

def test_build_search_no_query():
    assert scoop_core.cmd_search() == ["scoop", "search"]


def test_build_search_with_query():
    assert scoop_core.cmd_search("git") == ["scoop", "search", "git"]


def test_build_install():
    assert scoop_core.cmd_install("7zip") == ["scoop", "install", "7zip"]


def test_build_uninstall():
    assert scoop_core.cmd_uninstall("7zip") == ["scoop", "uninstall", "7zip"]


def test_build_update_single_app():
    assert scoop_core.cmd_update("git") == ["scoop", "update", "git"]


def test_build_update_all_is_star():
    assert scoop_core.cmd_update_all() == ["scoop", "update", "*"]
    assert scoop_core.cmd_update() == scoop_core.cmd_update_all()


def test_build_list_plain_and_json():
    assert scoop_core.cmd_list() == ["scoop", "list"]
    assert scoop_core.cmd_list(json_mode=True) == ["scoop", "list", "--Json"]


def test_format_shell_command_quotes_spaces():
    argv = scoop_core.build_scoop_command("install", "my app")
    command = scoop_core.format_shell_command(argv)
    assert "scoop" in command and "my app" in command


# ---------------------------------------------------------------------------
# run_scoop_command delegates to subprocess with a formatted command
# ---------------------------------------------------------------------------

class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_run_scoop_command_success(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return FakeCompleted(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    rc, out, err = scoop_core.run_scoop_command("update", "git")

    assert (rc, out, err) == (0, "ok", "")
    assert seen["command"] == scoop_core.format_shell_command(["scoop", "update", "git"])
    assert seen["kwargs"]["shell"] is True
    assert seen["kwargs"]["capture_output"] is True
    assert seen["kwargs"]["text"] is True


def test_run_scoop_command_missing_binary(monkeypatch):
    def fake_run(command, **kwargs):
        raise FileNotFoundError("scoop")

    monkeypatch.setattr(subprocess, "run", fake_run)
    rc, out, err = scoop_core.run_scoop_command("list")
    assert rc == 127
    assert "not found" in err


def test_run_scoop_command_timeout(monkeypatch):
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(cmd=command, timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    rc, _, err = scoop_core.run_scoop_command("update", "*")
    assert rc == 124


# ---------------------------------------------------------------------------
# High-level actions route to the right scoop subcommands
# ---------------------------------------------------------------------------

@pytest.fixture()
def recording_runner(monkeypatch):
    calls = []

    def runner(*args, **kwargs):
        calls.append(list(args))
        return 0, "", ""

    monkeypatch.setattr(scoop_core, "run_scoop_command", runner)
    return calls


def test_search_available_apps_uses_search_command(recording_runner):
    def runner(*args, **kwargs):
        recording_runner.append(list(args))
        return 0, "git 2.40 main\n", ""

    scoop_core.search_available_apps("git", runner=runner)
    assert recording_runner == [["search", "git"]]


def test_install_app_uses_install_command(recording_runner):
    scoop_core.install_app("7zip", runner=recording_runner)
    assert recording_runner == [["install", "7zip"]]


def test_uninstall_app_uses_uninstall_command(recording_runner):
    scoop_core.uninstall_app("7zip", runner=recording_runner)
    assert recording_runner == [["uninstall", "7zip"]]


def test_update_app_uses_update_command(recording_runner):
    scoop_core.update_app("git", runner=recording_runner)
    assert recording_runner == [["update", "git"]]


def test_update_all_uses_update_star(recording_runner):
    scoop_core.update_all(runner=recording_runner)
    assert recording_runner == [["update", "*"]]


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

def test_parse_installed_json_array():
    payload = json.dumps([
        {"Name": "Git", "Version": "2.40.0", "Source": "main", "Updated": "2023-05-01", "Info": ""},
        {"Name": "7zip", "Version": "21.07", "Source": "main", "Updated": "", "Info": ""},
    ])
    rows = scoop_core.parse_installed_json(payload)
    assert [r["name"] for r in rows] == ["Git", "7zip"]
    assert rows[0]["version"] == "2.40.0"
    assert rows[0]["source"] == "main"


def test_parse_installed_json_apps_object_and_lowercase_keys():
    payload = json.dumps({"apps": [{"name": "nodejs", "version": "20.1", "source": "main"}]})
    rows = scoop_core.parse_installed_json(payload)
    assert rows == [{"name": "nodejs", "version": "20.1", "source": "main",
                     "updated": "", "info": ""}]


def test_parse_installed_json_invalid_returns_none():
    assert scoop_core.parse_installed_json("Name Version\n---- -------") is None
    assert scoop_core.parse_installed_json("") is None
    assert scoop_core.parse_installed_json('{"unexpected": 1}') == []


def test_parse_installed_json_drops_nameless_entries():
    payload = json.dumps([{"Version": "1.0"}, {"Name": "git"}])
    rows = scoop_core.parse_installed_json(payload)
    assert [r["name"] for r in rows] == ["git"]


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------

TABLE_OUTPUT = """\
Name        Version Source Updated     Info
----------  ------- ------ ----------- ----
7zip        21.07   main
git         2.40.0  main   2023-05-01  base
nodejs-lts  20.1.0  main
"""

def test_parse_installed_table_basic():
    rows = scoop_core.parse_installed_table(TABLE_OUTPUT)
    assert [r["name"] for r in rows] == ["7zip", "git", "nodejs-lts"]
    git = rows[1]
    assert git["version"] == "2.40.0"
    assert git["source"] == "main"
    assert git["updated"] == "2023-05-01"
    assert git["info"] == "base"


def test_parse_installed_table_handles_no_apps_message():
    assert scoop_core.parse_installed_table("No apps installed.\n") == []


def test_parse_installed_table_skips_blank_and_separator_lines():
    rows = scoop_core.parse_installed_table("\n---- ----\n\nfoo 1.0\n")
    assert [r["name"] for r in rows] == ["foo"]


# ---------------------------------------------------------------------------
# get_installed_apps: prefer JSON, fall back to table
# ---------------------------------------------------------------------------

def test_get_installed_apps_prefers_json():
    calls = []

    def runner(*args):
        calls.append(list(args))
        if args == ("list", "--Json"):
            return 0, json.dumps([{"Name": "git"}]), ""
        return 0, TABLE_OUTPUT, ""

    rows = scoop_core.get_installed_apps(runner=runner)
    assert calls == [["list", "--Json"]]  # never needed the fallback
    assert [r["name"] for r in rows] == ["git"]


def test_get_installed_apps_falls_back_when_json_unsupported():
    calls = []

    def runner(*args):
        calls.append(list(args))
        if args == ("list", "--Json"):
            return 1, "", "unknown flag --Json"
        return 0, TABLE_OUTPUT, ""

    rows = scoop_core.get_installed_apps(runner=runner)
    assert calls == [["list", "--Json"], ["list"]]
    assert [r["name"] for r in rows] == ["7zip", "git", "nodejs-lts"]


def test_get_installed_apps_falls_back_on_non_json_payload():
    def runner(*args):
        if args == ("list", "--Json"):
            return 0, TABLE_OUTPUT, ""  # old scoop ignores the flag, prints table
        return 0, TABLE_OUTPUT, ""

    rows = scoop_core.get_installed_apps(runner=runner)
    assert [r["name"] for r in rows] == ["7zip", "git", "nodejs-lts"]


def test_get_installed_apps_raises_when_both_fail():
    def runner(*args):
        return 1, "", "boom"

    with pytest.raises(scoop_core.ScoopError):
        scoop_core.get_installed_apps(runner=runner)


# ---------------------------------------------------------------------------
# Installed-status matching edge cases
# ---------------------------------------------------------------------------

INSTALLED = [
    {"name": "git", "version": "2.40.0"},
    {"name": "gitignore", "version": "1.0"},
    {"name": "NodeJS-LTS", "version": "20.1"},
]


def test_is_installed_exact_match():
    assert scoop_core.is_installed("git", INSTALLED) is True
    assert scoop_core.is_installed("gitignore", INSTALLED) is True


def test_is_installed_case_insensitive():
    assert scoop_core.is_installed("GIT", INSTALLED) is True
    assert scoop_core.is_installed("Git", INSTALLED) is True
    assert scoop_core.is_installed("nodejs-lts", INSTALLED) is True
    assert scoop_core.is_installed("NODEJS", INSTALLED) is False


def test_is_installed_substring_trap():
    assert scoop_core.is_installed("git", INSTALLED) is True
    assert scoop_core.is_installed("ign", INSTALLED) is False
    assert scoop_core.is_installed("gitlfs", INSTALLED) is False
    assert scoop_core.is_installed("node", INSTALLED) is False  # not 'nodejs-lts'


def test_is_installed_empty_and_whitespace():
    assert scoop_core.is_installed("", INSTALLED) is False
    assert scoop_core.is_installed("  git  ", INSTALLED) is True
    assert scoop_core.is_installed("git", []) is False


def test_is_installed_accepts_legacy_raw_lines():
    raw_lines = ["git 2.40.0 main", "gitignore 1.0 main", "Name Version Source"]
    assert scoop_core.is_installed("git", raw_lines) is True
    assert scoop_core.is_installed("Git", raw_lines) is True
    assert scoop_core.is_installed("node", raw_lines) is False


def test_installed_names_dedupes_case():
    assert scoop_core.installed_names([{"name": "Git"}, {"name": "GIT"}, "git 1.0"]) == {"git"}


# ---------------------------------------------------------------------------
# Background streaming
# ---------------------------------------------------------------------------

def test_stream_scoop_async_streams_lines_and_finish_code(monkeypatch):
    class FakePopen:
        def __init__(self, command, **kwargs):
            assert "update" in command
            self.stdout = iter(["Updating 'git'...\n", "'git' was updated\n"])

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    lines, codes = [], []

    thread = scoop_core.stream_scoop_async(["scoop", "update", "git"],
                                           on_line=lines.append,
                                           on_finish=codes.append)
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert lines == ["Updating 'git'...", "'git' was updated"]
    assert codes == [0]


def test_stream_scoop_async_survives_popen_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("scoop")

    monkeypatch.setattr(subprocess, "Popen", boom)
    lines, codes = [], []
    done = threading.Event()

    def finish(rc):
        codes.append(rc)
        done.set()

    thread = scoop_core.stream_scoop_async(["scoop", "update", "*"],
                                           on_line=lines.append,
                                           on_finish=finish)
    assert done.wait(timeout=5)
    assert codes == [1]
    assert any("error" in line for line in lines)
