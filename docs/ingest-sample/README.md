# Sample capability — hockey-pool

A full, ingestable capability spec used to exercise `bnc-kb` ingestion end to end.
Content is derived from the SQ2 hockey-pool backlog (`sq2/TODO.md`): a team hockey
pool where participants pick one player per "box", boxes are seeded from the NHL
top-25 scorers, and a leaderboard tracks points (goals + assists).

## Story → business-function mapping

The backlog's nine ordered stories are consolidated into **two business functions**:

| Business function | Stories | Theme |
|---|---|---|
| `business-fct-1` | 1–5 | Création de la sélection (participant: view, seed, select, validate, submit) |
| `business-fct-2` | 6–9 | Suivi, classement et administration (leaderboard, detail, box config, scoring) |

Each business function carries the three requirement dimensions the parser
recognizes: `solution-requirements.md`, `data-requirements.md`, `business-rules.md`.

## Layout

```
kb-manifest.yaml                         capability_slug / category / domain / source_commit
requirements/
  business-fct-1/                        → business_function node (stories 1–5)
  business-fct-2/                        → business_function node (stories 6–9)
architecture/documents/
  01-context-and-requirements/           → dimension: context-and-requirements
  02-quality-attributes/                 → dimension: quality-attributes
  03-constraints/                        → dimension: constraints
  04-architecture-diagrams/              → dimension: architecture-diagrams
  05-infrastructure-costs/               → dimension: infrastructure-costs
  06-architectural-decisions/            → ADR-* files become decision_record nodes
  07-risks-and-technical-debts/          → RISK-* files become risk nodes
  processes/                             → dimension: processes
```

Architecture documents are capability-level (not assigned to a business function);
only `requirements/business-fct-*/` files attach to a business function.

## Ingest

```bash
cd docs/ingest-sample
zip -r /tmp/hockey-pool.zip . -x '*README.md'
curl -s -H "X-API-Key: write-key" -F "file=@/tmp/hockey-pool.zip" \
  http://localhost:8000/ingest
```
