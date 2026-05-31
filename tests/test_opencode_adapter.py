"""Tests for the OpenCode API adapter."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError

from llmwiki.adapters.opencode import OpenCodeAdapter


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _session(session_id="ses_123", updated=1234567890000):
    return {
        "id": session_id,
        "title": "Implement feature",
        "directory": "/work/my-project",
        "time": {"created": 1234567800000, "updated": updated},
        "model": {"id": "claude-sonnet", "providerID": "anthropic"},
    }


def _messages():
    return [
        {
            "info": {
                "id": "msg_1",
                "sessionID": "ses_123",
                "role": "user",
                "time": {"created": 1234567800000},
            },
            "parts": [{"type": "text", "text": "Add OpenCode sync"}],
        },
        {
            "info": {
                "id": "msg_2",
                "sessionID": "ses_123",
                "role": "assistant",
                "time": {"created": 1234567810000},
                "modelID": "claude-sonnet",
            },
            "parts": [
                {"type": "text", "text": "Implemented."},
                {
                    "type": "tool",
                    "tool": "bash",
                    "state": {"status": "completed", "input": {"cmd": "pytest"}, "output": "ok"},
                },
            ],
        },
    ]


def test_adapter_registered():
    from llmwiki.adapters import REGISTRY, discover_adapters

    discover_adapters()
    assert REGISTRY["opencode"] is OpenCodeAdapter


def test_discovers_sessions_from_api(monkeypatch):
    def fake_urlopen(request, timeout):
        assert request.full_url == "http://127.0.0.1:4096/experimental/session?limit=100"
        return _Response([_session()])

    monkeypatch.setattr("llmwiki.adapters.opencode.urlopen", fake_urlopen)

    adapter = OpenCodeAdapter()
    paths = adapter.discover_sessions()

    assert paths == [Path("opencode-api") / "ses_123.jsonl"]
    assert adapter.source_state_key(paths[0]) == "opencode::ses_123"
    assert adapter.source_mtime(paths[0]) == 1234567890000.0
    assert adapter.derive_project_slug(paths[0]) == "my-project"


def test_discover_gracefully_skips_unavailable_api(monkeypatch):
    def fake_urlopen(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr("llmwiki.adapters.opencode.urlopen", fake_urlopen)

    assert OpenCodeAdapter().discover_sessions() == []


def test_read_records_fetches_messages_and_preserves_session(monkeypatch):
    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/experimental/session?limit=100"):
            return _Response([_session()])
        if request.full_url.endswith("/session/ses_123/message"):
            return _Response(_messages())
        raise AssertionError(request.full_url)

    monkeypatch.setattr("llmwiki.adapters.opencode.urlopen", fake_urlopen)

    adapter = OpenCodeAdapter()
    path = adapter.discover_sessions()[0]
    records = adapter.read_records(path)

    assert records is not None
    assert records[0]["type"] == "opencode_session"
    assert records[1]["info"]["role"] == "user"


def test_normalize_records_maps_opencode_messages(monkeypatch):
    adapter = OpenCodeAdapter()
    records = [{"type": "opencode_session", "session": _session()}, *_messages()]

    out = adapter.normalize_records(records)

    assert out[0]["type"] == "init"
    assert out[0]["sessionId"] == "ses_123"
    assert out[1]["type"] == "user"
    assert out[1]["message"]["content"] == "Add OpenCode sync"
    assert out[2]["type"] == "assistant"
    assert out[2]["message"]["model"] == "claude-sonnet"
    assert out[2]["message"]["content"][0] == {"type": "text", "text": "Implemented."}
    assert out[2]["message"]["content"][1]["type"] == "tool_use"


def test_config_supports_base_url_limit_and_auth_token(monkeypatch):
    seen = []

    def fake_urlopen(request, timeout):
        seen.append((request.full_url, timeout))
        return _Response([])

    monkeypatch.setattr("llmwiki.adapters.opencode.urlopen", fake_urlopen)

    adapter = OpenCodeAdapter({"opencode": {
        "base_url": "http://localhost:9999/",
        "limit": 3,
        "auth_token": "abc",
        "timeout": 2,
    }})
    assert adapter.discover_sessions() == []

    assert seen == [("http://localhost:9999/experimental/session?limit=3&auth_token=abc", 2.0)]
