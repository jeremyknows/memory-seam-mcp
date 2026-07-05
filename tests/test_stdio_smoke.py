from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

anyio = pytest.importorskip("anyio")
mcp_stdio = pytest.importorskip("mcp.client.stdio")
mcp_session = pytest.importorskip("mcp.client.session")


def test_stdio_smoke_recall_envelope(tmp_path: Path) -> None:
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "runtime.md").write_text(
        "# Runtime Boundary\n\nMemory Seam recall should return receipts and safe posture.",
        encoding="utf-8",
    )

    async def run(session: Any) -> dict[str, Any]:
        tools = await session.list_tools()
        tool_names = {tool.name for tool in tools.tools}
        assert {"memory_seam_health", "memory_seam_context", "memory_seam_recall"} <= tool_names

        health = await session.call_tool("memory_seam_health", {})
        assert not health.isError, health
        health_env = json.loads(health.content[0].text)
        assert health_env["status_code"] == 200
        assert health_env["bridge"]["transport"] == "stdio"

        context = await session.call_tool("memory_seam_context", {})
        assert not context.isError, context
        context_env = json.loads(context.content[0].text)
        assert context_env["status_code"] == 200
        assert context_env["body"]["endpoint"] == "context"

        result = await session.call_tool(
            "memory_seam_recall",
            {
                "query": "runtime boundary",
                "n": 1,
            },
        )
        assert not result.isError, result
        return json.loads(result.content[0].text)

    envelope = anyio.run(_connect_and, notes, run)
    assert envelope["status_code"] == 200
    assert envelope["body"]["endpoint"] == "recall"
    assert envelope["body"]["read_receipt"]["receipt_version"] == "memory_seam_read_receipt_v0"
    assert envelope["bridge"]["status"] == "user_started_stdio_bridge"
    assert envelope["bridge"]["transport"] == "stdio"
    assert envelope["safe_posture"] == {
        "read_backend_called": False,
        "service_started": False,
        "runtime_registry_consumed": False,
        "raw_fallback_used": False,
        "write_custody_or_reindex": False,
    }


async def _connect_and(notes: Path, callback: Any) -> Any:
    from mcp import StdioServerParameters

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "memory_seam_mcp.server", "--root", str(notes)],
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    async with mcp_stdio.stdio_client(params) as (read, write):
        async with mcp_session.ClientSession(read, write) as session:
            await session.initialize()
            return await callback(session)

