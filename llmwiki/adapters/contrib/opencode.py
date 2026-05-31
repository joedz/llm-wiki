"""Compatibility shim for the promoted OpenCode adapter.

OpenCode used to live under ``llmwiki.adapters.contrib`` when it was modeled
as a JSONL session-store adapter. The current adapter is API-backed and core.
"""

from llmwiki.adapters.opencode import OpenCodeAdapter

__all__ = ["OpenCodeAdapter"]
