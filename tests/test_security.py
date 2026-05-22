from miniagent.security import redact_obj, redact_text, shell_env


def test_redact_text_removes_secret_values():
    env = {"DEEPSEEK_API_KEY": "sk-secret-value"}
    assert "sk-secret-value" not in redact_text("key=sk-secret-value", env=env)


def test_redact_obj_redacts_secret_keys():
    data = {"api_key": "abc", "nested": {"token": "def"}}
    result = redact_obj(data)
    assert result["api_key"] == "<redacted>"
    assert result["nested"]["token"] == "<redacted>"


def test_shell_env_uses_allowlist(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    env = shell_env(cwd="D:/miniAgent")
    assert "DEEPSEEK_API_KEY" not in env
    assert env["PWD"] == "D:/miniAgent"
