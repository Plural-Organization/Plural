"""A tiny stdio MCP server for tests: echoes and adds."""

from mcp.server import MCPServer

server = MCPServer("echo")


@server.tool()
def echo(text: str) -> str:
    """Repeat the text back."""
    return f"echo: {text}"


@server.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


if __name__ == "__main__":
    server.run()
