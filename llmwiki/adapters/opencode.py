"""OpenCode adapter.

Reads sessions from a running local OpenCode HTTP API and normalizes the
returned messages into the shared Claude-style record shape used by llmwiki.
The adapter is read-only: it only calls list/get-message endpoints.
"""

from __future__ import annotations

import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from llmwiki.adapters import register
from llmwiki.adapters.base import BaseAdapter, _safe_project_slug


def _cfg(config: dict[str, Any] | None) -> dict[str, Any]:
    raw = config or {}
    top = raw.get("opencode", {})
    nested = raw.get("adapters", {}).get("opencode", {})
    out: dict[str, Any] = {}
    if isinstance(top, dict):
        out.update(top)
    if isinstance(nested, dict):
        out.update(nested)
    return out


def _millis_to_iso(value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return ""
    # OpenCode timestamps are epoch milliseconds.
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def _short_json(value: Any, limit: int = 800) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 15].rstrip() + "... [truncated]"


@register("opencode")
class OpenCodeAdapter(BaseAdapter):
    """OpenCode - reads sessions from http://127.0.0.1:4096."""

    SUPPORTED_SCHEMA_VERSIONS = ["api-v1"]
    DEFAULT_BASE_URL = "http://127.0.0.1:4096"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        ad_cfg = _cfg(config)
        self.base_url = str(ad_cfg.get("base_url") or self.DEFAULT_BASE_URL).rstrip("/")
        self.limit = int(ad_cfg.get("limit") or 100)
        self.timeout = float(ad_cfg.get("timeout") or 1.5)
        self.auth_token = str(ad_cfg.get("auth_token") or "")
        self.username = str(ad_cfg.get("username") or "")
        self.password = str(ad_cfg.get("password") or "")
        self._sessions_by_path: dict[str, dict[str, Any]] = {}
        self._paths_by_session_id: dict[str, Path] = {}

    @property
    def session_store_path(self):  # type: ignore[override]
        return Path("opencode-api")

    @classmethod
    def is_available(cls) -> bool:
        try:
            adapter = cls()
            adapter._get_json("/experimental/session", {"limit": 1})
            return True
        except Exception:
            return False

    def _url(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = self.base_url + path
        params = {k: v for k, v in (query or {}).items() if v is not None}
        if self.auth_token:
            params["auth_token"] = self.auth_token
        if not params:
            return url
        sep = "&" if "?" in url else "?"
        return url + sep + urlencode(params)

    def _headers(self) -> dict[str, str]:
        if not self.username and not self.password:
            return {}
        token = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    def _get_json(self, path: str, query: dict[str, Any] | None = None) -> Any:
        request = Request(self._url(path, query), headers=self._headers())
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def discover_sessions(self) -> list[Path]:
        try:
            payload = self._get_json("/experimental/session", {"limit": self.limit})
        except HTTPError as e:
            print(f"  warning: OpenCode API returned HTTP {e.code}; skipping opencode", file=sys.stderr)
            return []
        except (OSError, URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"  warning: OpenCode API unavailable at {self.base_url}; skipping opencode ({e})", file=sys.stderr)
            return []

        sessions = payload.get("items", []) if isinstance(payload, dict) else payload
        if not isinstance(sessions, list):
            return []

        self._sessions_by_path.clear()
        self._paths_by_session_id.clear()
        paths: list[Path] = []
        for session in sessions:
            if not isinstance(session, dict):
                continue
            session_id = str(session.get("id") or "")
            if not session_id:
                continue
            safe_id = _safe_project_slug(session_id)
            path = Path("opencode-api") / f"{safe_id}.jsonl"
            self._sessions_by_path[str(path)] = session
            self._paths_by_session_id[session_id] = path
            paths.append(path)
        return paths

    def source_mtime(self, path: Path) -> float:
        session = self._session_for_path(path)
        time = session.get("time") if isinstance(session.get("time"), dict) else {}
        updated = time.get("updated") or time.get("created")
        if isinstance(updated, (int, float)) and not isinstance(updated, bool):
            return float(updated)
        return 0.0

    def source_state_key(self, path: Path) -> str | None:
        session = self._session_for_path(path)
        session_id = session.get("id")
        return f"opencode::{session_id}" if session_id else None

    def derive_project_slug(self, path: Path) -> str:
        session = self._session_for_path(path)
        directory = str(session.get("directory") or "")
        rel_path = str(session.get("path") or "")
        if rel_path and rel_path not in (".", "/"):
            return _safe_project_slug(Path(rel_path).name)
        if directory:
            return _safe_project_slug(Path(directory).name)
        project = session.get("project")
        if isinstance(project, dict) and project.get("name"):
            return _safe_project_slug(str(project["name"]))
        return "opencode"

    def read_records(self, path: Path) -> list[dict[str, Any]] | None:
        session = self._session_for_path(path)
        session_id = str(session.get("id") or "")
        if not session_id:
            return []
        try:
            messages = self._get_json(f"/session/{session_id}/message")
        except HTTPError as e:
            print(f"  warning: OpenCode message fetch failed for {session_id}: HTTP {e.code}", file=sys.stderr)
            return []
        except (OSError, URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"  warning: OpenCode message fetch failed for {session_id}: {e}", file=sys.stderr)
            return []
        if not isinstance(messages, list):
            return []
        return [{"type": "opencode_session", "session": session}, *messages]

    def normalize_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        session: dict[str, Any] = {}
        out: list[dict[str, Any]] = []

        for rec in records:
            if not isinstance(rec, dict):
                continue
            if rec.get("type") == "opencode_session":
                raw = rec.get("session")
                session = raw if isinstance(raw, dict) else {}
                time = session.get("time") if isinstance(session.get("time"), dict) else {}
                out.append({
                    "type": "init",
                    "sessionId": session.get("id", ""),
                    "cwd": session.get("directory", ""),
                    "timestamp": _millis_to_iso(time.get("created") or time.get("updated")),
                })
                continue
            converted = self._convert_message(rec, session)
            if converted:
                out.append(converted)
        return out

    def is_subagent(self, path: Path) -> bool:
        return False

    def _session_for_path(self, path: Path) -> dict[str, Any]:
        return self._sessions_by_path.get(str(path), {})

    def _convert_message(self, message: dict[str, Any], session: dict[str, Any]) -> dict[str, Any] | None:
        info = message.get("info")
        parts = message.get("parts")
        if not isinstance(info, dict) or not isinstance(parts, list):
            return None
        role = str(info.get("role") or "")
        timestamp = _millis_to_iso((info.get("time") or {}).get("created"))
        base = {
            "sessionId": info.get("sessionID") or session.get("id", ""),
            "timestamp": timestamp,
            "cwd": session.get("directory", ""),
        }

        if role == "user":
            content = self._user_content(parts)
            if not content.strip():
                return None
            return {
                **base,
                "type": "user",
                "message": {"role": "user", "content": content},
            }

        if role == "assistant":
            content = self._assistant_content(parts, info)
            if not content:
                return None
            model = info.get("modelID") or (session.get("model") or {}).get("id", "")
            return {
                **base,
                "type": "assistant",
                "message": {"role": "assistant", "content": content, "model": model},
            }
        return None

    def _user_content(self, parts: list[Any]) -> str:
        chunks: list[str] = []
        for part in parts:
            if not isinstance(part, dict) or part.get("ignored"):
                continue
            ptype = part.get("type")
            if ptype == "text":
                chunks.append(str(part.get("text") or ""))
            elif ptype == "file":
                name = part.get("filename") or part.get("url") or "file"
                mime = part.get("mime") or "unknown"
                chunks.append(f"[Attached file: {name} ({mime})]")
            elif ptype == "subtask":
                chunks.append(f"[Subtask: {part.get('description') or part.get('prompt') or ''}]")
            elif ptype == "compaction":
                chunks.append("[Compaction request]")
        return "\n\n".join(c for c in chunks if c)

    def _assistant_content(self, parts: list[Any], info: dict[str, Any]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype == "text":
                text = str(part.get("text") or "")
                if text:
                    blocks.append({"type": "text", "text": text})
            elif ptype == "reasoning":
                continue
            elif ptype == "tool":
                blocks.append(self._tool_block(part))
            elif ptype == "file":
                name = part.get("filename") or part.get("url") or "file"
                mime = part.get("mime") or "unknown"
                blocks.append({"type": "text", "text": f"[Attached file: {name} ({mime})]"})
            elif ptype in {"step-start", "step-finish", "snapshot", "patch"}:
                continue
            else:
                text = _short_json(part)
                if text:
                    blocks.append({"type": "text", "text": f"[{ptype or 'part'}] {text}"})

        error = info.get("error")
        if error:
            blocks.append({"type": "text", "text": f"[Error] {_short_json(error)}"})
        return blocks

    def _tool_block(self, part: dict[str, Any]) -> dict[str, Any]:
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        tool = str(part.get("tool") or "tool")
        status = state.get("status") or "unknown"
        text = f"Tool {tool} ({status})"
        if state.get("input") is not None:
            text += f"\ninput: {_short_json(state.get('input'), 500)}"
        if state.get("output") is not None:
            text += f"\noutput: {_short_json(state.get('output'), 700)}"
        if state.get("error") is not None:
            text += f"\nerror: {_short_json(state.get('error'), 700)}"
        return {"type": "tool_use", "name": tool, "input": {"summary": text}}
