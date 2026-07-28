from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Annotated

from fastembed import TextEmbedding
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field
from qdrant_client import QdrantClient, models


ROOT = Path(__file__).resolve().parent
RAG_HOME = Path(os.environ.get("LOCAL_RAG_HOME", Path.home() / "local-rag-data"))
DATA_DIR = Path(os.environ.get("LOCAL_RAG_DATA_DIR", RAG_HOME / "qdrant"))
MODEL_DIR = Path(os.environ.get("LOCAL_RAG_MODEL_DIR", RAG_HOME / "models"))
COLLECTION = os.environ.get("LOCAL_RAG_COLLECTION", "documents")
MODEL_NAME = os.environ.get("LOCAL_RAG_MODEL", "BAAI/bge-small-en-v1.5")
VECTOR_SIZE = 384
SUPPORTED_SUFFIXES = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".jsonl", ".xml",
    ".html", ".htm", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c",
    ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".sql",
    ".toml", ".yaml", ".yml", ".ini", ".cfg", ".ps1", ".sh",
}

mcp = FastMCP(
    "Local RAG",
    instructions=(
        "Search the user's private, local semantic document index. Use rag_search "
        "before answering questions that may be covered by indexed material."
    ),
)
_client: QdrantClient | None = None
_embedder: TextEmbedding | None = None


def client() -> QdrantClient:
    global _client
    if _client is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _client = QdrantClient(path=str(DATA_DIR))
        if not _client.collection_exists(COLLECTION):
            _client.create_collection(
                collection_name=COLLECTION,
                vectors_config=models.VectorParams(
                    size=VECTOR_SIZE, distance=models.Distance.COSINE
                ),
            )
    return _client


def embedder() -> TextEmbedding:
    global _embedder
    if _embedder is None:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        _embedder = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(MODEL_DIR))
    return _embedder


def chunks(text: str, size: int = 1200, overlap: int = 200):
    text = re.sub(r"\r\n?", "\n", text).strip()
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = max(text.rfind("\n", start + size // 2, end),
                           text.rfind(" ", start + size // 2, end))
            if boundary > start:
                end = boundary
        value = text[start:end].strip()
        if value:
            yield value
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)


def stable_id(source: str, index: int, text: str) -> int:
    digest = hashlib.blake2b(
        f"{source}\0{index}\0{text}".encode("utf-8"), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big") & ((1 << 63) - 1)


def index_document(source: str, text: str) -> int:
    pieces = list(chunks(text))
    if not pieces:
        return 0
    vectors = list(embedder().embed(pieces))
    points = [
        models.PointStruct(
            id=stable_id(source, i, piece),
            vector=vector.tolist(),
            payload={"source": source, "chunk": i, "text": piece},
        )
        for i, (piece, vector) in enumerate(zip(pieces, vectors))
    ]
    client().upsert(collection_name=COLLECTION, points=points, wait=True)
    return len(points)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def rag_status() -> dict:
    """Return the local RAG database location, model, and indexed chunk count."""
    info = client().get_collection(COLLECTION)
    return {
        "ready": True,
        "collection": COLLECTION,
        "chunks": info.points_count,
        "embedding_model": MODEL_NAME,
        "data_directory": str(DATA_DIR),
    }


@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
))
def rag_add_text(
    text: Annotated[str, Field(description="Text to add to the semantic index")],
    source: Annotated[str, Field(description="A stable source name or URI")],
) -> dict:
    """Add supplied text to the private local semantic index."""
    count = index_document(source, text)
    return {"source": source, "chunks_indexed": count}


@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
))
def rag_index_folder(
    folder: Annotated[str, Field(description="Absolute path of the folder to index")],
    recursive: Annotated[bool, Field(description="Include subfolders")] = True,
) -> dict:
    """Index readable text, Markdown, data, and source-code files in a folder."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")
    pattern = "**/*" if recursive else "*"
    files = [p for p in root.glob(pattern) if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES]
    indexed_files = 0
    indexed_chunks = 0
    skipped: list[str] = []
    for path in files:
        try:
            if path.stat().st_size > 20 * 1024 * 1024:
                skipped.append(f"{path} (over 20 MB)")
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            count = index_document(str(path), text)
            indexed_files += 1
            indexed_chunks += count
        except Exception as exc:
            skipped.append(f"{path} ({exc})")
    return {
        "folder": str(root),
        "files_indexed": indexed_files,
        "chunks_indexed": indexed_chunks,
        "skipped": skipped[:50],
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def rag_search(
    query: Annotated[str, Field(description="Natural-language semantic search query")],
    limit: Annotated[int, Field(ge=1, le=20, description="Maximum results")] = 6,
) -> list[dict]:
    """Semantically search indexed local material and return sourced excerpts."""
    vector = next(iter(embedder().query_embed(query))).tolist()
    response = client().query_points(
        collection_name=COLLECTION,
        query=vector,
        limit=limit,
        with_payload=True,
    )
    return [
        {
            "score": round(float(point.score), 4),
            "source": point.payload.get("source"),
            "chunk": point.payload.get("chunk"),
            "text": point.payload.get("text"),
        }
        for point in response.points
    ]


if __name__ == "__main__":
    mcp.run(transport="stdio")
