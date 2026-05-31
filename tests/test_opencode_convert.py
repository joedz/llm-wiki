"""Integration coverage for OpenCode API sources in convert_all."""

from __future__ import annotations

import json
from pathlib import Path

from llmwiki.convert import convert_all


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_convert_all_imports_opencode_api_session(tmp_path, monkeypatch):
    session = {
        "id": "ses_abc",
        "title": "OpenCode sync",
        "directory": str(tmp_path / "demo-project"),
        "time": {"created": 1700000000000, "updated": 1700000001000},
        "model": {"id": "claude-sonnet", "providerID": "anthropic"},
    }
    messages = [
        {
            "info": {
                "id": "msg_1",
                "sessionID": "ses_abc",
                "role": "user",
                    "time": {"created": 1700000000000},
            },
            "parts": [{"type": "text", "text": "Collect OpenCode conversations"}],
        },
        {
            "info": {
                "id": "msg_2",
                "sessionID": "ses_abc",
                "role": "assistant",
                    "time": {"created": 1700000001000},
                "modelID": "claude-sonnet",
            },
            "parts": [{"type": "text", "text": "Done"}],
        },
    ]

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/experimental/session?limit=100"):
            return _Response([session])
        if request.full_url.endswith("/session/ses_abc/message"):
            return _Response(messages)
        raise AssertionError(request.full_url)

    monkeypatch.setattr("llmwiki.adapters.opencode.urlopen", fake_urlopen)

    out_dir = tmp_path / "raw" / "sessions"
    state_file = tmp_path / ".llmwiki-state.json"
    config_file = tmp_path / "config.json"
    config_file.write_text("{}", encoding="utf-8")

    rc = convert_all(
        adapters=["opencode"],
        out_dir=out_dir,
        state_file=state_file,
        config_file=config_file,
        ignore_file=tmp_path / ".llmwikiignore",
    )

    assert rc == 0
    written = list(out_dir.glob("*.md"))
    assert len(written) == 1
    text = written[0].read_text(encoding="utf-8")
    assert "tags: [opencode, session-transcript]" in text
    assert "Collect OpenCode conversations" in text
    assert "sessionId: ses_abc" in text

    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["opencode::ses_abc"] == 1700000001000.0
