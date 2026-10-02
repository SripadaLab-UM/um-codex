# Adapted from IHS DataLab's backend/tests/test_text_encoding.py at 0213185 (its
# scan; not its slice of DataLab).
"""Every text file UM-Codex reads or writes says it is UTF-8.

Without ``encoding=``, Python uses the computer's locale encoding: cp1252 on
most Windows computers, where writing "→" raises UnicodeEncodeError, and
reading a tool's output can fail the same way. Ruff's PLW1514 catches
the calls whose receiver it can tell is a path; the scan here also catches
``something.read_text()`` on any object, ``os.fdopen`` and text-mode
``subprocess`` calls.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Not images/: those scripts run in the Linux container, whose locale is UTF-8.
SCANNED = [REPO / "src", REPO / "scripts"]

# Calls named ``open`` that aren't file opens (os.open returns a descriptor).
NOT_FILES = {"os", "tarfile", "webbrowser", "zipfile", "self", "opener"}
SUBPROCESS = {"run", "Popen", "check_output", "check_call", "call"}
TEMPFILES = {"NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile"}


def _binary(mode: ast.expr | None) -> bool:
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value


def _is_true(value: ast.expr | None) -> bool:
    return isinstance(value, ast.Constant) and value.value is True


def _receiver(func: ast.Attribute) -> str:
    value = func.value
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    return ""


def _problem(call: ast.Call) -> str | None:
    """Why this call reads or writes text without saying UTF-8, if it does."""
    keywords = {k.arg: k.value for k in call.keywords if k.arg}
    if "encoding" in keywords:
        return None
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if name in {"read_text", "write_text"}:
        return name
    if name == "open":
        if isinstance(func, ast.Attribute):
            if _receiver(func) in NOT_FILES:
                return None
            mode = call.args[0] if call.args else keywords.get("mode")
        else:
            mode = call.args[1] if len(call.args) > 1 else keywords.get("mode")
        return None if _binary(mode) else "open in text mode"
    if name == "fdopen":
        mode = call.args[1] if len(call.args) > 1 else keywords.get("mode")
        return None if _binary(mode) else "fdopen in text mode"
    if name in TEMPFILES:
        mode = call.args[0] if call.args else keywords.get("mode")
        return "temporary file in text mode" if mode is not None and not _binary(mode) else None
    if name in {"FileHandler", "TextIOWrapper"}:
        return name
    text = _is_true(keywords.get("text")) or _is_true(keywords.get("universal_newlines"))
    # UM-Codex passes subprocess.run in as `run` (a Runner), so a bare
    # run(...) counts too.
    if text and name in SUBPROCESS and (isinstance(func, ast.Name) or _receiver(func) == "subprocess"):
        return f"subprocess.{name} with text=True"
    return None


def _problems() -> list[str]:
    found = []
    for root in SCANNED:
        for path in sorted(root.rglob("*.py")):
            if ".venv" in path.parts or "node_modules" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            # os.fdopen(thing.open(), "rb"): the inner open returns a descriptor.
            descriptors = {
                id(arg)
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "fdopen"
                for arg in node.args[:1]
            }
            for node in ast.walk(tree):
                if id(node) in descriptors:
                    continue
                if isinstance(node, ast.Call) and (why := _problem(node)):
                    found.append(f"{path.relative_to(REPO)}:{node.lineno}: {why}")
    return found


def test_every_text_file_is_opened_as_utf8() -> None:
    assert _problems() == [], "say encoding='utf-8' (and errors= for a tool's output)"


def test_the_scan_sees_the_mistakes_it_is_for() -> None:
    def problem(source: str) -> str | None:
        call = ast.parse(source).body[0]
        assert isinstance(call, ast.Expr) and isinstance(call.value, ast.Call)
        return _problem(call.value)

    assert problem("report.write_text(text)")
    assert problem("open(path, 'w')")
    assert problem("path.open('a')")
    assert problem("os.fdopen(fd, newline='')")
    assert problem("subprocess.run(['git'], capture_output=True, text=True)")
    assert problem("run(['icacls'], capture_output=True, text=True)")
    assert problem("tempfile.NamedTemporaryFile('w')")
    assert problem("logging.FileHandler(path)")
    assert not problem("report.write_text(text, encoding='utf-8')")
    assert not problem("open(path, 'rb')")
    assert not problem("os.open(path, os.O_RDONLY)")
    assert not problem("subprocess.run(['git'], capture_output=True)")
    assert not problem("subprocess.run(['git'], encoding='utf-8', errors='replace')")
