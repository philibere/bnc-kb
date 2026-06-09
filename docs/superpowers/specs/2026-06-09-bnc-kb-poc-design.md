# bnc-kb POC — Spec Knowledge Base API: Design

> Status: approved design, ready for implementation planning. Captured 2026-06-09.
> Sources: `README.md` (POC scope) + `bnc-sdlc-specs/artefacts/ideation/api-stockage-specs-postgresql-2026-06-03.md` (data model and domain depth, non-authoritative ideation).

## 1. Scope and boundary

A single-database proof of concept that validates the spec's central thesis: **specs as governed, dimension-queryable data**, built on the unified "everything is a node" model. The POC delivers the full node schema, a ZIP-driven architecture-repo parser, hybrid (vector + filter) search with pluggable embeddings, and a three-role REST API.

The README sets the POC boundary; the ideation spec supplies the data model and domain depth. The ideation document is explicitly non-authoritative, so we borrow its schema and concepts without building the entire vision.

### In scope

- Full node schema: `node` (unified), `spec_dimension`, `link_type`, `spec_link`, `node_chunk_embedding`.
- ZIP-archive ingestion of **architecture** capability repos (no Git access, no webhook).
- AsciiDoc handling: store raw `.adoc`/`.md` body, extract structured `attrs` via regex.
- Hybrid search: pgvector cosine + dimension/status filter, with a pluggable embedding generator.
- Three REST modules — add, search, admin — mapped to three roles (read / write / admin).
- App-level role enforcement; RLS policies and scoped DB roles written into migrations but left disabled.

### Out of scope (explicitly deferred)

- Git webhooks / CI triggers (ingestion is ZIP upload only).
- Multi-database-per-domain federation (single database).
- Component / Builder repos (architecture repos only).
- MCP query surface (plain REST only).
- Real AsciiDoc-to-HTML/DocBook conversion (raw text is stored).
- Active RLS (policies written, never enabled).
- A committed embedding model (stub embedder by default).

## 2. Architecture and stack

- **Python 3.12 + FastAPI** — REST API, async, automatic OpenAPI docs. The three modules map to three routers: `add`, `search`, `admin`.
- **psycopg 3** + **pgvector** extension on **Postgres 18**.
- **Pydantic v2** — request/response schemas, the coverage envelope, and the manifest model. Guards the HTTP and file boundaries only; it is not an ORM and does not touch the database. All database access is raw SQL via psycopg.
- **Migrations** — plain ordered `.sql` files applied by a small runner. The ideation spec hands us hand-written DDL (custom enum, CHECK constraints, pgvector, RLS); raw SQL stays readable and faithful, whereas Alembic autogeneration would fight all of those. Alembic is the noted alternative if the team prefers it.
- **Dev / test** — `docker compose` Postgres 18 + pgvector image; `pytest` against an ephemeral test database.
- **Auth** — API-key header (`X-API-Key`) mapped to one of three roles. Designed to swap for OIDC later without touching business logic.

## 3. Data model

Adopt the ideation spec's DDL essentially verbatim:

- `spec_dimension` — governed whitelist of dimensions.
- `link_type` — governed whitelist of relation types.
- `node_kind` enum — `capability`, `business_function`, `document`, `decision_record`, `risk`.
- `node` — unified table; `parent_id` self-FK for the `belongs_to` hierarchy; the `container_vs_document` and `capability_is_root` CHECK constraints enforce that containers carry no body/versioning and documents carry both a body and a dimension.
- `node_chunk_embedding` — derived, non-versioned retrieval units; `vector(1024)` placeholder.
- `spec_link` — typed edges; real FKs to `node(id)` for internal targets, `dst_urn` for external targets, with the `dst_internal_xor_external`, `no_self_loop`, and `uq_edge` constraints.

`get_spec(head_id, dimension?, status?)` is implemented as the parameterized recursive CTE from the spec, not a `CREATE VIEW`.

### POC adjustments

- Single database. Capability `category` and `domain` are carried on `capability` nodes (a `domain` value kept for routing-readiness even though only one database exists in the POC); other family-specific structure lives in `attrs` (JSONB).
- `node_chunk_embedding.embedding` stays `vector(1024)` (placeholder per the spec; aligned with Vooban/BNC later).
- RLS policies and scoped DB roles are written into a migration but **not enabled** — the schema is RLS-ready with no further migration needed to turn it on.
- Seed `spec_dimension` with the 11 architecture dimensions: `context-and-requirements`, `quality-attributes`, `constraints`, `architecture-diagrams`, `infrastructure-costs`, `architectural-decisions`, `risks-and-technical-debts`, `processes`, `solution-requirements`, `data-requirements`, `business-rules`.
- Seed `link_type` with `belongs_to`, `derives_from`, `supersedes`, `realizes`, `traces_to`, `depends_on`.

## 4. The three modules

### Add (write role) — `POST /ingest`

Accepts a ZIP upload of an architecture capability repo tree.

1. Read `kb-manifest.yaml` at the archive root, yielding `{capability_slug, category, domain, source_commit}`. Reject with 4xx if the manifest is missing or fails validation.
2. **Idempotency:** if `(capability_slug, source_commit)` was already ingested, return the prior result without duplicating nodes.
3. Walk the architecture arborescence; map each file/folder to its `dimension_code` via a declarative mapping table derived from the spec's provenance table.
4. Build the node tree: `capability` root → `business_function` containers (`requirements/business-fct-n/`) → `document` / `decision_record` / `risk` leaves. Each ADR and each RISK becomes one node.
5. Store `.adoc`/`.md` body raw; regex-extract family-specific `attrs` (for example, ADR `status` / `deciders` / `date`).
6. **Append-only versioning:** a leaf whose body changed gets a new node row; `supersedes_id` points at the prior node, and the prior node's `status` flips to `superseded`.
7. Generate chunk embeddings via the `Embedder` interface and persist them to `node_chunk_embedding`.

Returns an ingestion summary: nodes created / versioned / skipped, dimensions seen, and any files recorded as unreachable.

### Search (read role)

- `POST /search` — hybrid retrieval. Embed the query via `Embedder`, run pgvector cosine over `node_chunk_embedding`, join back to nodes, filter by optional `dimension` and `status` (default `approved`), default `k=12`. Returns ranked nodes wrapped in a coverage envelope `{rows, partial, denied_scopes, sources_unreached}` — no silent truncation.
- `GET /spec/{head_id}` — the recursive-CTE `get_spec`, with optional `dimension` / `status` filters, wrapped in a coverage envelope.
- `GET /spec/{node_id}/links?rel=` — `spec_link` traversal, 1–2 hops.

### Admin (admin role)

- `GET | POST | DELETE /admin/dimensions` and `/admin/link-types` — govern the whitelists. This is the only path to add a dimension or link type; ingestion cannot free-INSERT new ones.
- `POST /admin/reembed` — recompute embeddings (for example, after swapping the embedder).
- `GET /admin/health` and `GET /admin/stats` — database connectivity, node / dimension counts.

## 5. Embeddings (pluggable)

An `Embedder` protocol exposes `embed(texts: list[str]) -> list[Vector1024]`.

- POC default: `StubEmbedder` — deterministic, hash-seeded 1024-dimension vectors. Search is reproducible and runs with zero external dependency.
- `RealEmbedder` — a documented slot where a Vooban/BNC model wires in.
- Chunking: fixed-size token windows over `body` with small overlap (configurable). The open question of optimal chunk size is recorded, not resolved, in this POC.

## 6. Error handling and coverage

- The coverage envelope is a first-class Pydantic wrapper on every read response.
- Ingestion is per-file tolerant: a malformed file is recorded in the summary as `sources_unreached` rather than failing the whole request, so one bad `.adoc` does not sink an entire capability ingest.
- A missing manifest or a dimension not in the whitelist are hard 4xx errors.

## 7. Project layout

```
bnc_kb/
  api/        # FastAPI app, routers: add, search, admin; auth dependency
  db/         # connection, migration runner, sql/NNNN_*.sql
  parser/     # zip walker, tree->node mapper, adoc attrs extractor, manifest
  embeddings/ # Embedder protocol, StubEmbedder, chunker
  models/     # pydantic schemas, coverage envelope
  queries/    # get_spec CTE, hybrid search, link traversal
tests/        # pytest, fixtures, sample-capability.zip
docker-compose.yml
```

## 8. Testing strategy

Test-driven throughout.

- **Unit:** parser (tree → nodes, attrs extraction, idempotency), chunker, coverage envelope.
- **Integration** (against docker Postgres): migrations apply clean; ingest a fixture ZIP; `get_spec` returns the expected subtree; hybrid search ranks deterministically with the stub; role enforcement (read cannot write, and so on); versioning produces the expected supersede chain.

## 9. Success criteria (scoped to the POC)

- A `write` client uploads a capability ZIP and nodes plus embeddings land in the database.
- A `read` client runs `get_spec(head, dimension)` and hybrid search in ≤ 1 s, each with an explicit coverage envelope.
- Dimensions are whitelist-governed through the admin module; ingestion cannot invent dimensions.
- Versioning produces a traceable supersede chain (slug + version + supersedes_id + source_commit).
- The schema is RLS-ready: no migration is needed to enable cloisonnement later.

## 10. Milestones

1. Schema, migration runner, seeds, and disabled RLS.
2. ZIP parser → node tree (manifest, attrs, idempotency).
3. Embeddings interface, stub, and chunker.
4. Add module wired end to end.
5. Search module (`get_spec`, hybrid, links) with coverage envelope.
6. Admin module and auth / roles.
7. Integration tests, sample fixture, and README usage.
