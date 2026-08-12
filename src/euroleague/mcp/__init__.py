"""The MCP query layer: a read-only view of the validated warehouse."""

from euroleague.mcp.protocol import Tool, serve

__all__ = ["Tool", "serve"]
