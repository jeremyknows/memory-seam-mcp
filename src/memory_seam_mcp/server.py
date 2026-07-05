"""MCP stdio bridge for Memory Seam local markdown reads."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlencode

from memory_seam.adapters import AdapterMemorySeamProvider
from memory_seam.local_adapters.markdown import LocalMarkdownAdapter
from memory_seam.runtime import LocalReadOnlyRuntime, ReadOnlyRuntimeConfig, RuntimeRequest, StaticIdentityVerifier

BRIDGE_NAME = "memory-seam-mcp"
BRIDGE_STATUS = "user_started_stdio_bridge"
PROVIDER_NAME = "local-markdown-mcp"
AGENT_SUBJECT = "agent:memory-seam-mcp"
READ_RECEIPT_QUERY_VALUE = "metadata_only"

SAFE_POSTURE_KEYS = (
    "read_backend_called",
    "service_started",
    "runtime_registry_consumed",
    "raw_fallback_used",
    "write_custody_or_reindex",
)


@dataclass(frozen=True)
class BridgeConfig:
    root: Path
    adapter: str = "markdown"


def build_runtime(root: str | Path) -> LocalReadOnlyRuntime:
    """Build the in-process, read-only local markdown runtime."""

    return LocalReadOnlyRuntime(
        config=ReadOnlyRuntimeConfig(enabled=True, provider_name=PROVIDER_NAME),
        provider=AdapterMemorySeamProvider(
            LocalMarkdownAdapter(root),
            provider_name=PROVIDER_NAME,
        ),
        identity_verifier=StaticIdentityVerifier(
            subject=AGENT_SUBJECT,
            allowed_scopes=frozenset({"context", "wiki"}),
        ),
    )


def memory_seam_health_envelope(runtime: LocalReadOnlyRuntime) -> dict[str, Any]:
    """Return runtime health with bridge posture metadata."""

    return _with_bridge_posture(runtime.handle(RuntimeRequest("GET", "/health")))


def memory_seam_context_envelope(
    runtime: LocalReadOnlyRuntime,
    *,
    include: list[str] | None = None,
) -> dict[str, Any]:
    """Return the full Memory Seam context envelope."""

    include_value = ",".join(include or ["memory"])
    target = "/context?" + urlencode(
        {
            "include": include_value,
            "mode": "startup",
            "agent": AGENT_SUBJECT,
            "read_receipt": READ_RECEIPT_QUERY_VALUE,
        }
    )
    return _with_bridge_posture(runtime.handle(RuntimeRequest("GET", target)))


def memory_seam_recall_envelope(
    runtime: LocalReadOnlyRuntime,
    *,
    query: str,
    n: int = 5,
) -> dict[str, Any]:
    """Return the full Memory Seam recall envelope."""

    target = "/recall?" + urlencode(
        {
            "query": query,
            "scope": "wiki",
            "n": n,
            "agent": AGENT_SUBJECT,
            "read_receipt": READ_RECEIPT_QUERY_VALUE,
        }
    )
    return _with_bridge_posture(runtime.handle(RuntimeRequest("GET", target)))


def _with_bridge_posture(envelope: dict[str, Any]) -> dict[str, Any]:
    body = dict(envelope.get("body") or {})
    bridge = {
        "name": BRIDGE_NAME,
        "status": BRIDGE_STATUS,
        "transport": "stdio",
        "user_started": True,
        "socket_bound": False,
        "daemon": False,
        "auto_start": False,
        "credential_reads": False,
        "global_config_mutation": False,
        "read_only": True,
    }
    return {
        **envelope,
        "body": body,
        "bridge": bridge,
        "safe_posture": _safe_posture(body),
    }


def _safe_posture(body: dict[str, Any]) -> dict[str, bool]:
    return {key: bool(body.get(key)) for key in SAFE_POSTURE_KEYS}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memory-seam-mcp",
        description="User-started MCP stdio bridge for Memory Seam local markdown reads.",
    )
    parser.add_argument(
        "--root",
        default=os.environ.get("MEMORY_SEAM_ROOT"),
        help="Local notes folder to read. May also be set with MEMORY_SEAM_ROOT.",
    )
    parser.add_argument(
        "--adapter",
        choices=("markdown",),
        default=os.environ.get("MEMORY_SEAM_ADAPTER", "markdown"),
        help="Local adapter to use. Only markdown is supported.",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print report-safe bridge config and exit without starting MCP stdio.",
    )
    return parser


def parse_config(argv: Sequence[str] | None = None) -> tuple[BridgeConfig, bool]:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.root:
        parser.error("--root or MEMORY_SEAM_ROOT is required")
    return BridgeConfig(root=Path(args.root).expanduser(), adapter=args.adapter), bool(args.print_config)


def run_stdio_bridge(config: BridgeConfig) -> int:
    """Run the FastMCP stdio bridge."""

    from mcp.server.fastmcp import FastMCP  # noqa: PLC0415

    runtime = build_runtime(config.root)
    server = FastMCP(BRIDGE_NAME)

    @server.tool(name="memory_seam_health", description="Memory Seam local markdown health envelope.")
    def memory_seam_health() -> dict[str, Any]:
        return memory_seam_health_envelope(runtime)

    @server.tool(name="memory_seam_context", description="Memory Seam local markdown context envelope.")
    def memory_seam_context(include: list[str] | None = None) -> dict[str, Any]:
        return memory_seam_context_envelope(runtime, include=include)

    @server.tool(name="memory_seam_recall", description="Memory Seam local markdown recall envelope.")
    def memory_seam_recall(query: str, n: int = 5) -> dict[str, Any]:
        return memory_seam_recall_envelope(runtime, query=query, n=n)

    server.run()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    config, print_config = parse_config(argv)
    if print_config:
        payload = {
            "bridge": BRIDGE_NAME,
            "status": BRIDGE_STATUS,
            "root": str(config.root),
            "adapter": config.adapter,
            "transport": "stdio",
            "socket_bound": False,
            "daemon": False,
            "auto_start": False,
            "credential_reads": False,
            "global_config_mutation": False,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    return run_stdio_bridge(config)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
