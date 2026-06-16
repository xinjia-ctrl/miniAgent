from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EngineEvent(BaseModel):
    type: str
    data: dict[str, Any] = Field(default_factory=dict)


REQUEST_START = "request_start"
ASSISTANT_DELTA = "assistant_delta"
ASSISTANT_MESSAGE = "assistant_message"
TOOL_START = "tool_start"
TOOL_RESULT = "tool_result"
TOOL_ERROR = "tool_error"
PERMISSION_DECISION = "permission_decision"
SESSION_SAVED = "session_saved"
DONE = "done"
ERROR = "error"
