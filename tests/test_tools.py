from types import SimpleNamespace

from miniagent import tools
from miniagent.tool_registry import parse_direct_command


def test_read_file_uses_real_line_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_ROOT", tmp_path.resolve())
    path = tmp_path / "sample.txt"
    path.write_text("a\nb\nc\n", encoding="utf-8")

    result = tools.read_file("sample.txt", start=1, end=2)

    assert "1: a" in result
    assert "2: b" in result


def test_find_files_skips_ignored_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_ROOT", tmp_path.resolve())
    (tmp_path / "miniagent").mkdir()
    (tmp_path / "miniagent" / "cli.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "hidden.py").write_text("ignore\n", encoding="utf-8")

    result = tools.find_files("*.py")

    assert "miniagent" in result
    assert "hidden.py" not in result


def test_search_text_fallback_finds_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_ROOT", tmp_path.resolve())
    monkeypatch.setattr(tools.shutil, "which", lambda _name: None)
    path = tmp_path / "app.py"
    path.write_text("def target():\n    return 1\n", encoding="utf-8")

    result = tools.search_text("target")

    assert "app.py:1:def target()" in result


def test_read_many_files_accepts_list(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_ROOT", tmp_path.resolve())
    (tmp_path / "a.txt").write_text("A\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("B\n", encoding="utf-8")

    result = tools.read_many_files(["a.txt", "b.txt"])

    assert "# a.txt" in result
    assert "# b.txt" in result


def test_path_escape_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_ROOT", tmp_path.resolve())
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")

    try:
        try:
            result = tools.read_file("../outside.txt")
        except ValueError as exc:
            result = str(exc)
    finally:
        outside.unlink(missing_ok=True)

    assert "路径逃逸" in result


def test_apply_patch_requires_exact_match(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_ROOT", tmp_path.resolve())
    path = tmp_path / "sample.txt"
    path.write_text("dup\ndup\n", encoding="utf-8")

    result = tools.apply_patch([
        {"path": "sample.txt", "old_text": "dup", "new_text": "x"},
    ])

    assert "期望 1 次" in result
    assert path.read_text(encoding="utf-8") == "dup\ndup\n"


def test_binary_file_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_ROOT", tmp_path.resolve())
    path = tmp_path / "bin.dat"
    path.write_bytes(b"a\x00b")

    try:
        result = tools.read_file("bin.dat")
    except ValueError as exc:
        result = str(exc)

    assert "二进制" in result


def test_direct_command_invalid_line_number_uses_default():
    name, args = parse_direct_command("read_file README.md nope 2")

    assert name == "read_file"
    assert args["start"] == 1
    assert args["end"] == 2


def test_run_shell_uses_shell_false_for_external_command(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(tools.subprocess, "run", fake_run)

    result = tools.run_shell("git status --short")

    assert "exit_code: 0" in result
    assert calls[0][0] == ["git", "status", "--short"]
    assert calls[0][1]["shell"] is False


def test_run_shell_maps_cmd_builtin_without_raw_shell(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(tools.subprocess, "run", fake_run)

    tools.run_shell("dir")

    assert calls[0][0] == ["cmd.exe", "/d", "/c", "dir"]
    assert calls[0][1]["shell"] is False


def test_run_shell_rejects_redirection():
    result = tools.run_shell("echo hi > a.txt")

    assert "exit_code: -1" in result
    assert "不支持管道、重定向或命令串联" in result


def test_run_shell_rejects_compact_redirection():
    result = tools.run_shell("echo hi>a.txt")

    assert "exit_code: -1" in result
    assert "不支持管道、重定向或命令串联" in result


def test_run_shell_rejects_nested_shell():
    result = tools.run_shell("powershell -Command Get-ChildItem")

    assert "exit_code: -1" in result
    assert "不支持嵌套 shell" in result
