# bnc-kb

A proof of concept for a **spec knowledge base API**: a service that stores software specifications as governed, dimension-queryable data and lets agents retrieve them by dimension, by hierarchy, and by semantic search — without writing SQL.

The POC validates one central idea from the design: **specs as governed data, built on a unified "everything is a node" model**, where a spec is a recursive traversal of a node subtree rather than a stored row.

## What it does

- **Ingest**: drive the vendored bnc-sdlc-code engine over a shaper spec corpus (markdown with frontmatter). It parses, validates, projects to a type graph (nodes + typed edges) with semantic tier chunks, and reconciles incrementally into the store. Two granularities: whole-corpus (`POST /ingest`, reconciles the full set) or partial (`POST /ingest/specs`, upserts one or several specs without touching the rest, resolving cross-references to already-stored specs). Accepts a corpus directory (CLI) or uploads (HTTP).
- **Search** — hybrid retrieval (vector similarity + dimension/status filter) plus hierarchy traversal (`get_spec`) and link traversal, each returning an explicit coverage envelope (no silent truncation).
- **Admin**: govern the dimension and link-type whitelists, and check health/stats.

## Roles

Three roles, enforced at the API layer:

- **read** — search and retrieve specs.
- **write** — ingest capability archives.
- **admin** — full access, including whitelist governance and maintenance.

The schema also ships RLS policies, written but left disabled, so per-capability cloisonnement can be turned on later. (Scoped DB roles and grants are deferred — the policies stay inert until both RLS and roles are added.)

## Stack

- **Postgres 18** + **pgvector**
- **Python 3.12 + FastAPI** REST API (three routers: add / search / admin)
- **psycopg 3** with raw SQL; **Pydantic v2** at the HTTP and file boundaries
- Vendored ingestion engine `spec_ingestion` (from bnc-sdlc-code); embedder selected by `EMBEDDING_MODEL` (default `fake-v1`, deterministic; real `BAAI/bge-m3` via the `embed` extra)
- Plain ordered `.sql` migrations
- `docker compose` for local Postgres; `pytest` for tests

## Data model

A single `node` table unifies the hierarchy (`capability` → `business_function` → `document` / `decision_record` / `risk`) via a `parent_id` self-reference. Documents carry a dimension and are versioned; containers are not. Typed edges live in `spec_link`, derived embeddings in `node_chunk_embedding`. Dimensions and link types are governed whitelists.

## Scope

Deliberately bounded. **In scope:** the full node schema, ingestion of shaper spec corpora via the vendored bnc-sdlc-code engine, hybrid search with a pluggable embedder, and the three-role REST API. **Deferred:** Git webhooks/CI triggers, multi-database-per-domain federation, component/Builder repos, an MCP surface, active RLS, and a committed embedding model.

## Running locally

```bash
docker compose up -d                       # Postgres 18 + pgvector on :5433
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                       # adjust keys/URL if needed
python -c "from bnc_kb.db.migrate import apply_migrations; from bnc_kb.config import load_settings; print(apply_migrations(load_settings().database_url))"
uvicorn bnc_kb.api.app:app --reload
```

Interactive API docs: http://localhost:8000/docs

Ingest a shaper spec corpus (write role). Two equivalent entry points, both driving
the vendored engine and writing the converged `node` / `node_chunk_embedding` /
`spec_link` store. The corpus is the WHOLE set of specs (the engine reconciles to it):

```bash
# CLI (DSN defaults to DATABASE_URL)
bnc-kb-ingest path/to/corpus --incremental
# or: make ingest CORPUS=path/to/corpus INCREMENTAL=1

# HTTP: zip the corpus of .md specs and upload
( cd path/to/corpus && zip -r /tmp/corpus.zip . )
curl -s -H "X-API-Key: write-key" -F "file=@/tmp/corpus.zip" http://localhost:8000/ingest
```

Partial ingest of one or several specs (upsert only these, leave the rest intact):

```bash
# CLI
bnc-kb-ingest path/to/one-or-more-specs --merge

# HTTP: one or several .md files (repeat -F "files=@...")
curl -s -H "X-API-Key: write-key" \
  -F "files=@FEAT-CARTE-001.md" -F "files=@REQ-CARTE-001.md" \
  http://localhost:8000/ingest/specs
```

Search (read role):

```bash
curl -s -H "X-API-Key: read-key" -H "Content-Type: application/json" \
  -d '{"query":"overtime rules","k":5}' http://localhost:8000/search
```

## Ingestion engine (vendored)

Ingestion is the bnc-sdlc-code pipeline, vendored as the top-level `spec_ingestion`
package plus the metamodel manifest at `metamodel/bnc.metamodel.yaml`. bnc-kb's own
parser and persistence were removed; the engine writes through `BncKbSink` into the
same `node` / `node_chunk_embedding` / `spec_link` tables, so search / spec / links
serve shaper specs unchanged. The `0006_shaper_convergence.sql` migration relaxed the
schema for this: open `kind`, tier chunks, `content_hash`, and `dst_ref` + `pending`.

Two local edits to the vendored copy: the manifest path in `spec_ingestion/metamodel.py`
and the default embedder (`fake-v1`) in `spec_ingestion/config.py`. Refresh the manifest
from a bnc-shaper checkout with `make sync-metamodel` (override `SHAPER=...`).

Query-time embedding (`/search`) uses the SAME embedder as ingestion (shared
`EMBEDDING_MODEL`), so the query vector and the stored vectors live in one space.

The `link_type` whitelist (the `spec_link.rel` FK target) is seeded from the manifest's
edge kinds at ingest time, so any corpus edge kind has its FK target regardless of which
metamodel is active (0006 only seeds a fixed subset).

## Tests

```bash
docker compose up -d
pytest                        # unit + integration
pytest -m "not integration"   # unit only, no database required
```

## Design

Full design: [`docs/superpowers/specs/2026-06-09-bnc-kb-poc-design.md`](docs/superpowers/specs/2026-06-09-bnc-kb-poc-design.md).
Implementation plan: [`docs/superpowers/plans/2026-06-09-bnc-kb-poc.md`](docs/superpowers/plans/2026-06-09-bnc-kb-poc.md).
