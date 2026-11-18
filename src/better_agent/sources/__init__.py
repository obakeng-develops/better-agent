"""Session source adapters. Each adapter exposes do_import(conn, force) -> stats dict."""


def tool_target(inp: dict) -> str:
    """What a tool call acted on, for search: a file, command, pattern or path."""
    return str(
        inp.get("file_path") or inp.get("filePath") or inp.get("command")
        or inp.get("pattern") or inp.get("path") or ""
    )[:200]
