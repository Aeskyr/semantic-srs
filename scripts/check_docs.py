from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server.py"
PROJECT = ROOT / "PROJECT.md"
REQUIRED_SECTIONS = {
    "Purpose and user experience",
    "Architecture and data flow",
    "Component responsibilities",
    "Database entities and invariants",
    "MCP tools and grading thresholds",
    "Dashboard design and API",
    "Testing, installation, and development",
    "Current implementation status",
    "Known limitations and deferred features",
    "Decision log",
    "Completed milestone log",
}


def registered_tools(source: str) -> set[str]:
    tree = ast.parse(source)
    result = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            call = decorator if isinstance(decorator, ast.Call) else None
            target = call.func if call else decorator
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "mcp"
                and target.attr == "tool"
            ):
                result.add(node.name)
    return result


def sqlite_tables(source: str) -> set[str]:
    return set(
        re.findall(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([a-z_]+)", source, re.I)
    )


def main() -> None:
    server = SERVER.read_text(encoding="utf-8")
    project = PROJECT.read_text(encoding="utf-8")
    headings = set(re.findall(r"^## (.+)$", project, re.M))
    missing_sections = REQUIRED_SECTIONS - headings
    missing_tools = {name for name in registered_tools(server) if f"`{name}`" not in project}
    missing_tables = {name for name in sqlite_tables(server) if f"`{name}`" not in project}
    errors = []
    if missing_sections:
        errors.append("missing sections: " + ", ".join(sorted(missing_sections)))
    if missing_tools:
        errors.append("missing MCP tools: " + ", ".join(sorted(missing_tools)))
    if missing_tables:
        errors.append("missing SQLite tables: " + ", ".join(sorted(missing_tables)))
    if errors:
        raise SystemExit("PROJECT.md consistency failed: " + "; ".join(errors))
    print(
        f"PROJECT.md consistent: {len(REQUIRED_SECTIONS)} sections, "
        f"{len(registered_tools(server))} MCP tools, {len(sqlite_tables(server))} tables"
    )


if __name__ == "__main__":
    main()
