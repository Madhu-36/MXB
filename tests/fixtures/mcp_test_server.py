"""Tiny stdio MCP server for MXB's tests (works with MCP SDK 1.x and 2.x)."""
try:
    from mcp.server.mcpserver import MCPServer as Server   # SDK 2.x
except ImportError:
    from mcp.server.fastmcp import FastMCP as Server        # SDK 1.x
from mcp.types import ToolAnnotations

app = Server("mxb-test")
NOTES = {"groceries": "milk, eggs"}


@app.tool(description="Repeat the text back.", annotations=ToolAnnotations(readOnlyHint=True))
def echo(text: str) -> str:
    return f"echo: {text}"


@app.tool(description="Add two integers.", annotations=ToolAnnotations(readOnlyHint=True))
def add(a: int, b: int) -> str:
    return str(a + b)


@app.tool(description="Read a saved note by name.", annotations=ToolAnnotations(readOnlyHint=True))
def read_note(name: str) -> str:
    return NOTES.get(name, f"no note called {name}")


@app.tool(description="Delete a saved note. Cannot be undone.", annotations=ToolAnnotations(destructiveHint=True))
def delete_note(name: str) -> str:
    return "deleted" if NOTES.pop(name, None) is not None else "nothing to delete"


@app.tool(description="Always fails.")
def explode() -> str:
    raise ValueError("kaboom")


if __name__ == "__main__":
    app.run()
