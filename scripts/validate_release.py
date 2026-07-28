from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.0"


def fail(message: str) -> None:
    raise SystemExit(message)


def validate_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"{path}: invalid JSON: {exc}")


def validate_tool_annotations(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        tool = False
        annotated = False
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                if getattr(decorator.func.value, "id", None) == "mcp" and decorator.func.attr == "tool":
                    tool = True
                    annotated = any(keyword.arg == "annotations" for keyword in decorator.keywords)
        if tool and not annotated:
            fail(f"{path}: MCP tool {node.name} lacks ToolAnnotations")


for plugin in ("semantic-srs", "local-rag"):
    base = ROOT / "plugins" / plugin
    for host in (".claude-plugin", ".codex-plugin"):
        manifest = validate_json(base / host / "plugin.json")
        if manifest.get("name") != plugin or manifest.get("version") != VERSION:
            fail(f"{host} manifest identity/version mismatch for {plugin}")
    mcp = validate_json(base / ".mcp.json")
    entry = mcp.get("mcpServers", {}).get(plugin, {})
    serialized = json.dumps(entry)
    if entry.get("command") != "powershell.exe" or "$env:LOCALAPPDATA" not in serialized or "CLAUDE_PLUGIN_ROOT" in serialized or "Blin Boss" in serialized:
        fail(f"{plugin}: MCP launcher is not portable")
    skills = list((base / "skills").glob("*/SKILL.md"))
    if not skills:
        fail(f"{plugin}: no portable skill found")
    for skill in skills:
        text = skill.read_text(encoding="utf-8")
        if not text.startswith("---\n") or "\nname:" not in text or "\ndescription:" not in text:
            fail(f"{skill}: invalid skill front matter")
    validate_tool_annotations(base / "server.py")

claude_market = validate_json(ROOT / ".claude-plugin/marketplace.json")
codex_market = validate_json(ROOT / ".agents/plugins/marketplace.json")
if {p["name"] for p in claude_market["plugins"]} != {"semantic-srs", "local-rag"}:
    fail("Claude marketplace plugin set mismatch")
if {p["name"] for p in codex_market["plugins"]} != {"semantic-srs", "local-rag"}:
    fail("Codex marketplace plugin set mismatch")

showcase = validate_json(ROOT / "showcase/imperial-russia-monarchs.json")
if showcase.get("format") != "semantic-srs-export":
    fail("showcase deck is not a Semantic SRS export")
if showcase.get("deck", {}).get("name") != "Imperial Russia Monarchs":
    fail("showcase deck identity mismatch")
if len(showcase.get("sources", [])) != 15 or len(showcase.get("cards", [])) != 30:
    fail("showcase deck must contain 15 sources and 30 cards")
if any(card.get("status") != "draft" or card.get("reviews") for card in showcase["cards"]):
    fail("showcase deck must contain only unreviewed drafts")

tracked = subprocess.check_output(
    ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
    cwd=ROOT,
    text=True,
).splitlines()
for relative in tracked:
    lowered = relative.lower()
    if any(part in lowered for part in (".venv/", "__pycache__/", ".sqlite3", "qdrant/", "models/")):
        fail(f"forbidden generated/live path tracked: {relative}")
    path = ROOT / relative
    if path.is_file() and path.stat().st_size < 2_000_000:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"C:\\Users\\[^\\\r\n]+", text, re.I):
            fail(f"absolute developer path in {relative}")
        token_pattern = (
            "(g" + "hp_|s" + "k-[A-Za-z0-9]{20,}|BEGIN (RSA |OPENSSH )?PRIVATE " + "KEY)"
        )
        if re.search(token_pattern, text):
            fail(f"possible secret in {relative}")

print("Release metadata, skills, annotations, portability, and repository hygiene are valid.")
