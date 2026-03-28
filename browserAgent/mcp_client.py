"""
Playwright MCP Client
=====================
Async wrapper around the Python MCP SDK to manage a @playwright/mcp server
subprocess. Provides start/list_tools/call_tool/close for the agentic loop.
"""

import json
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ALLOWED_TOOLS = frozenset({
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_press_key",
    "browser_wait_for",
    "browser_tabs",
    "browser_close",
})


class PlaywrightMCPClient:
    """Manages a headless @playwright/mcp server over stdio."""

    def __init__(self) -> None:
        self._exit_stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def start(self) -> None:
        """Spawn the Playwright MCP server and perform handshake."""
        server_params = StdioServerParameters(
            command="npx",
            args=["@playwright/mcp@latest", "--headless"],
        )
        transport = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        read_stream, write_stream = transport
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return filtered MCP tool schemas as plain dicts."""
        if not self._session:
            raise RuntimeError("MCP client not started — call start() first")
        response = await self._session.list_tools()
        tools: list[dict[str, Any]] = []
        for tool in response.tools:
            if tool.name not in ALLOWED_TOOLS:
                continue
            tools.append({
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            })
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        """Execute a tool call and return the result as text."""
        if not self._session:
            raise RuntimeError("MCP client not started — call start() first")
        result = await self._session.call_tool(name, arguments or {})
        parts: list[str] = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(json.dumps(block.model_dump(), default=str))
        return "\n".join(parts)

    async def close(self) -> None:
        """Shut down the MCP server subprocess."""
        await self._exit_stack.aclose()
        self._session = None
