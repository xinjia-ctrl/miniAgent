from __future__ import annotations

from pycode_agent.audit import AuditLogger


def test_audit_logger_redacts_sensitive_values(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(path)

    logger.log("model_request", {"api_key": "secret", "nested": {"token": "abc"}})

    content = path.read_text(encoding="utf-8")
    assert "secret" not in content
    assert "abc" not in content
    assert "***" in content
