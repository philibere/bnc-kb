# bnc-kb

A proof of concept for a **spec knowledge base API**: a service that stores software specifications as governed, dimension-queryable data and lets agents retrieve them by dimension, by hierarchy, and by semantic search — without writing SQL.

The POC validates one central idea from the design: **specs as governed data, built on a unified "everything is a node" model**, where a spec is a recursive traversal of a node subtree rather than a stored row.

## What it does

- **Add** — ingest an architecture capability repo, uploaded as a ZIP archive. A parser walks the artifact tree, maps each file to its dimension, and stores it as versioned nodes.
- **Search** — hybrid retrieval (vector similarity + dimension/status filter) plus hierarchy traversal (`get_spec`) and link traversal, each returning an explicit coverage envelope (no silent truncation).
- **Admin** — govern the dimension and link-type whitelists, recompute embeddings, and check health/stats.

## Roles

Three roles, enforced at the API layer:

- **read** — search and retrieve specs.
- **write** — ingest capability archives.
- **admin** — full access, including whitelist governance and maintenance.

The schema also ships RLS policies and scoped DB roles, written but left disabled, so per-capability cloisonnement can be enabled later without a migration.

## Stack

- **Postgres 18** + **pgvector**
- **Python 3.12 + FastAPI** REST API (three routers: add / search / admin)
- **psycopg 3** with raw SQL; **Pydantic v2** at the HTTP and file boundaries
- Plain ordered `.sql` migrations
- `docker compose` for local Postgres; `pytest` for tests

## Data model

A single `node` table unifies the hierarchy (`capability` → `business_function` → `document` / `decision_record` / `risk`) via a `parent_id` self-reference. Documents carry a dimension and are versioned; containers are not. Typed edges live in `spec_link`, derived embeddings in `node_chunk_embedding`. Dimensions and link types are governed whitelists.

## Scope

Deliberately bounded. **In scope:** the full node schema, ZIP ingestion of architecture repos, hybrid search with a pluggable embedder, and the three-role REST API. **Deferred:** Git webhooks/CI triggers, multi-database-per-domain federation, component/Builder repos, an MCP surface, real AsciiDoc conversion, active RLS, and a committed embedding model.

## Design

Full design and implementation plan: [`docs/superpowers/specs/2026-06-09-bnc-kb-poc-design.md`](docs/superpowers/specs/2026-06-09-bnc-kb-poc-design.md).
