# Space Apps 2026 Project Explorer

Independent searchable catalog of publicly available NASA Space Apps Challenge 2026 projects. **Not affiliated with or endorsed by NASA.**

## Repository layout

- `app/`: Cloudflare Worker + D1 search application, static frontend, and D1 export script
- `pipeline/collection/`: GraphQL team collection, public-page membership collection, and SQLite catalog construction
- `pipeline/enrichment/`: local Qwen/Ollama enrichment, cleanup, consolidation and tags
- `pipeline/validation/`: audits and review utilities
- `pipeline/search/`: original SQLite search prototype
- `pipeline/experiments/`: exploratory and superseded approaches, **not maintained production commands**
- `docs/`: technical case study and repository notes

## Data flow

1. `pipeline/collection/collect_teams.py` reads `teams.graphql` and downloads paginated public team data.
2. `pipeline/collection/collect_memberships.py` gathers public membership information from team pages.
3. `pipeline/collection/build_catalog.py` creates the source SQLite catalog.
4. Enrichment scripts process descriptions with a locally run language model; validation scripts inspect the results.
5. `app/scripts/export_d1.py` prepares D1 SQL imports.
6. `app/` serves search via a Cloudflare Worker and D1.

**Important:** This is a historical code collection assembled from the development project, not a turnkey reproducible build. Several scripts retain original relative paths, dependencies, and assumptions; the enrichment scripts may require Ollama, a local model and original data. Public API structures may change. Review scripts before running network collection. No original full database or generated AI data is distributed here.

The app files combine the Cloudflare starter configuration with the latest available study-area-search patch. **Test and reconcile against your actual working deployment before publishing.** The D1 export script may need study-area schema/data added separately.

See `app/README.md` and `pipeline/README.md` for details.
