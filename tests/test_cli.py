"""CLI-level tests for wildlint (main / check_file / file walking).

The checker-level tests in test_wildlint.py exercise ``check_source`` directly;
these exercise the harness: directory walking + excludes, the error/exit-code
model, ``# noqa`` suppression read from real files, ``[tool.wildlint]`` config,
and ``--format json``. They drive ``cli.main`` against files on disk via the
``tmp_path`` fixture and read stdout/stderr/exit through ``capsys``.
"""

from __future__ import annotations

import json

from wildlint.cli import main

# A compact WL001 trigger (default tier): guarded .replace-to-empty.
_WL001 = "def f(p):\n    if p.startswith('/x/'):\n        return p.replace('/x/', '')\n"


def _run(argv, capsys):
    rc = main(argv)
    out, err = capsys.readouterr()
    return rc, out, err


# --------------------------------------------------------------------------- #
# default directory exclusions
# --------------------------------------------------------------------------- #


def test_default_exclude_skips_venv(tmp_path, capsys):
    (tmp_path / "good.py").write_text(_WL001)
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "bad.py").write_text(_WL001)
    rc, out, _ = _run([str(tmp_path)], capsys)
    assert rc == 1
    assert "good.py" in out
    assert ".venv" not in out


def test_no_default_exclude_includes_venv(tmp_path, capsys):
    (tmp_path / "good.py").write_text(_WL001)
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "bad.py").write_text(_WL001)
    rc, out, _ = _run(["--no-default-exclude", str(tmp_path)], capsys)
    assert "good.py" in out
    assert ".venv" in out


def test_explicit_file_arg_under_excluded_dir_is_scanned(tmp_path, capsys):
    # An explicit file argument is scanned as-is even when it lives under a
    # default-excluded dir (preserves the pre-commit contract).
    venv = tmp_path / ".venv"
    venv.mkdir()
    bad = venv / "bad.py"
    bad.write_text(_WL001)
    rc, out, _ = _run([str(bad)], capsys)
    assert rc == 1
    assert "bad.py" in out


def test_explicit_excluded_dir_root_is_scanned(tmp_path, capsys):
    # Pointing wildlint directly at an excluded dir scans it (root exemption).
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "bad.py").write_text(_WL001)
    rc, out, _ = _run([str(venv)], capsys)
    assert rc == 1
    assert "bad.py" in out


# --------------------------------------------------------------------------- #
# loud failure (syntax error / missing path) + clean exit
# --------------------------------------------------------------------------- #


def test_syntax_error_to_stderr_and_nonzero(tmp_path, capsys):
    f = tmp_path / "bad.py"
    f.write_text("def (\n")
    rc, out, err = _run([str(f)], capsys)
    assert rc == 1
    assert out == ""  # findings stay on stdout; nothing to find
    assert "SyntaxError" in err
    assert str(f) in err


def test_missing_path_to_stderr_and_nonzero(tmp_path, capsys):
    missing = tmp_path / "nope.py"
    rc, out, err = _run([str(missing)], capsys)
    assert rc == 1
    assert "no such file" in err
    assert str(missing) in err


def test_clean_file_exits_zero(tmp_path, capsys):
    f = tmp_path / "clean.py"
    f.write_text("def f(p):\n    return p.removeprefix('/x/').split()\n")
    rc, out, err = _run([str(f)], capsys)
    assert rc == 0
    assert out == ""


# --------------------------------------------------------------------------- #
# # noqa inline suppression
# --------------------------------------------------------------------------- #


def test_noqa_bare_suppresses(tmp_path, capsys):
    f = tmp_path / "f.py"
    f.write_text(
        "def f(p):\n"
        "    if p.startswith('/x/'):\n"
        "        return p.replace('/x/', '')  # noqa\n"
    )
    rc, out, _ = _run([str(f)], capsys)
    assert rc == 0
    assert "WL001" not in out


def test_noqa_specific_code_suppresses(tmp_path, capsys):
    f = tmp_path / "f.py"
    f.write_text(
        "def f(p):\n"
        "    if p.startswith('/x/'):\n"
        "        return p.replace('/x/', '')  # noqa: WL001\n"
    )
    rc, out, _ = _run([str(f)], capsys)
    assert rc == 0
    assert "WL001" not in out


def test_noqa_wrong_code_still_fires(tmp_path, capsys):
    f = tmp_path / "f.py"
    f.write_text(
        "def f(p):\n"
        "    if p.startswith('/x/'):\n"
        "        return p.replace('/x/', '')  # noqa: WL002\n"
    )
    rc, out, _ = _run([str(f)], capsys)
    assert rc == 1
    assert "WL001" in out


def test_noqa_inside_string_literal_does_not_suppress(tmp_path, capsys):
    # The noqa text is inside a string literal, not a comment -- tokenize must
    # not treat it as a directive, so WL002 still fires (pedantic).
    f = tmp_path / "f.py"
    f.write_text("x = 'a # noqa b'.split(' ')\n")
    rc, out, _ = _run(["--pedantic", str(f)], capsys)
    assert rc == 1
    assert "WL002" in out


# --------------------------------------------------------------------------- #
# [tool.wildlint] config
# --------------------------------------------------------------------------- #


def test_config_select_restricts(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text("[tool.wildlint]\nselect = ['WL002']\n")
    f = tmp_path / "f.py"
    f.write_text(_WL001 + "y = name.split(' ')\n")  # WL001 (default) + WL002 (pedantic)
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run([str(f)], capsys)
    assert "WL002" in out
    assert "WL001" not in out  # select restricted to WL002


def test_config_pedantic_enables(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text("[tool.wildlint]\npedantic = true\n")
    f = tmp_path / "f.py"
    f.write_text("y = name.split(' ')\n")  # WL002, pedantic-only
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run([str(f)], capsys)
    assert "WL002" in out


def test_config_exclude(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.wildlint]\nexclude = ['vendor/*']\n"
    )
    (tmp_path / "good.py").write_text(_WL001)
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "bad.py").write_text(_WL001)
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run(["."], capsys)
    assert "good.py" in out
    assert "vendor" not in out


def test_cli_select_overrides_config(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text("[tool.wildlint]\nselect = ['WL002']\n")
    f = tmp_path / "f.py"
    f.write_text(_WL001 + "y = name.split(' ')\n")
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run(["--select", "WL001", str(f)], capsys)
    assert "WL001" in out
    assert "WL002" not in out  # CLI --select won


# --------------------------------------------------------------------------- #
# --format json
# --------------------------------------------------------------------------- #


def test_json_output_shape(tmp_path, capsys):
    (tmp_path / "good.py").write_text(_WL001)
    missing = tmp_path / "missing.py"
    rc, out, _ = _run(
        ["--format", "json", str(tmp_path / "good.py"), str(missing)], capsys
    )
    assert rc == 1
    payload = json.loads(out)
    assert "findings" in payload and "errors" in payload
    assert any(f["code"] == "WL001" for f in payload["findings"])
    assert payload["findings"][0].keys() == {"path", "line", "col", "code", "message"}
    assert any("no such file" in e for e in payload["errors"])


def test_json_clean_is_empty(tmp_path, capsys):
    f = tmp_path / "clean.py"
    f.write_text("def f(p):\n    return p.removeprefix('/x/').split()\n")
    rc, out, _ = _run(["--format", "json", str(f)], capsys)
    assert rc == 0
    payload = json.loads(out)
    assert payload["findings"] == [] and payload["errors"] == []
