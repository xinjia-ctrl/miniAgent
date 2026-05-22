from miniagent import tools


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
