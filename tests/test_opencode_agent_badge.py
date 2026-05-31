"""OpenCode sessions should render as OpenCode, not generic Agent."""

from __future__ import annotations

from llmwiki.build import detect_agent_label
from llmwiki.convert import DEFAULT_CONFIG, Redactor, render_session_markdown
from pathlib import Path


def test_opencode_tag_detects_agent_label():
    assert detect_agent_label({"tags": ["opencode", "session-transcript"]}) == (
        "OpenCode",
        "agent-opencode",
    )


def test_opencode_explicit_agent_detects_agent_label():
    assert detect_agent_label({"agent": "opencode"}) == ("OpenCode", "agent-opencode")


def test_render_session_markdown_emits_agent_frontmatter():
    records = [{
        "type": "user",
        "sessionId": "ses_123",
        "timestamp": "2026-05-08T12:25:00Z",
        "message": {"role": "user", "content": "hello"},
    }]
    md, _, _ = render_session_markdown(
        records,
        Path("opencode-api/ses_123.jsonl"),
        "opencode_web",
        Redactor(DEFAULT_CONFIG),
        DEFAULT_CONFIG,
        False,
        adapter_name="opencode",
    )
    assert "tags: [opencode, session-transcript]" in md
    assert "agent: opencode" in md
