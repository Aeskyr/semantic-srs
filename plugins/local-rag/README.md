# Local RAG

Local RAG is Semantic SRS's optional private retrieval companion for Claude Code
and Codex. It stores embedded Qdrant data under
`%LOCALAPPDATA%\SemanticSRS\rag\qdrant` and model files under `rag\models`.

The first indexing or search request downloads `BAAI/bge-small-en-v1.5`. After
that, embeddings and retrieval run locally. Its MCP tools are `rag_status`,
`rag_add_text`, `rag_index_folder`, and `rag_search`.
