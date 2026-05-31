---
title: "OpenCode adapter"
type: navigation
docs_shell: true
---

# OpenCode adapter

Reads sessions from a running local [OpenCode](https://github.com/sst/opencode)
HTTP server and converts them into the standard llmwiki session markdown.

**AI-session adapter** (`is_ai_session = True`) - fires by default when the
OpenCode API is reachable.

## Source

The current OpenCode session store is DB/API-backed. llmwiki intentionally
uses the public local API instead of reading SQLite tables directly:

- `GET /session` lists sessions.
- `GET /session/:sessionID/message` returns messages and parts.
- The default base URL is `http://127.0.0.1:4096`.

If OpenCode is not running, `llmwiki sync` skips this adapter with a warning
and continues with Claude/Codex.

## Configuration

The defaults work when OpenCode is running on its default local port:

```jsonc
{
  "opencode": {
    "enabled": true,
    "base_url": "http://127.0.0.1:4096",
    "limit": 100
  }
}
```

Authentication is optional and only needed if the OpenCode server requires it:

```jsonc
{
  "opencode": {
    "auth_token": "...",
    "username": "opencode",
    "password": "..."
  }
}
```

The adapter also accepts the same keys under `adapters.opencode` for
compatibility with other adapter configuration examples.

## Output

Standard `raw/sessions/<YYYY-MM-DDTHH-MM>-<project>-<slug>.md` files with:

- `tags: [opencode, session-transcript]`
- `sessionId` from the OpenCode session id
- `project` derived from the OpenCode session directory/path
- user, assistant, file, and tool parts rendered as readable transcript turns

## Code

- Adapter: `llmwiki/adapters/opencode.py`
- Compatibility shim: `llmwiki/adapters/contrib/opencode.py`
- Tests: `tests/test_opencode_adapter.py`, `tests/test_opencode_convert.py`
