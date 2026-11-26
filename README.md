# Space Apps 2026 Project Explorer

Independent searchable catalog of publicly available NASA Space Apps Challenge 2026 projects. **Not affiliated with or endorsed by NASA.**

The catalog contains **22,096 projects** from the 2026 challenge, with searchable project descriptions, automatically generated keywords, and geographic study-area references.

## Repository layout

- `app/`: Cloudflare Worker + D1 search application, static frontend, and D1 export script
- `pipeline/collection/`: GraphQL team collection, public-page membership collection, and SQLite catalog construction
- `pipeline/enrichment/`: local Qwen/Ollama enrichment, cleanup, consolidation, and tags
- `pipeline/validation/`: audits and review utilities
- `pipeline/search/`: original SQLite search prototype
- `pipeline/experiments/`: exploratory and superseded approaches, **not maintained production commands**
- `docs/`: technical case study and repository notes

## Data flow

1. `pipeline/collection/collect_teams.py` reads `teams.graphql` and downloads paginated public team data.
2. `pipeline/collection/collect_memberships.py` gathers public membership information from team pages.
3. `pipeline/collection/build_catalog.py` creates the source SQLite catalog.
4. Enrichment scripts process descriptions with a locally run Qwen language model through Ollama; validation scripts inspect the results.
5. `app/scripts/export_d1.py` prepares D1 SQL imports.
6. `app/` serves search via a Cloudflare Worker and D1.

## Downloadable datasets

The November 25, 2026 dataset release contains two SQLite database snapshots:

| File | Contents |
|---|---|
| `spaceapps_2026_catalog.sqlite.gz` | Source catalog containing 22,096 projects, teams, publicly listed membership information, and local search indexes |
| `spaceapps_2026_enriched.sqlite.gz` | Search-ready database containing 22,096 projects, 76,234 project–tag assignments, 1,619 study areas, and 2,901 project–study-area relationships |

Both archives are gzip-compressed SQLite databases. The release also includes `SHA256SUMS.txt` for integrity verification.

To extract a database:

```bash
gunzip -k spaceapps_2026_enriched.sqlite.gz
```

To verify the downloaded archives:

```bash
sha256sum -c SHA256SUMS.txt
```

### Data provenance and limitations

Project and team information was collected from publicly accessible NASA Space Apps Challenge pages and APIs.

Keyword assignments and geographic study-area references were generated through local language-model processing and subsequent cleanup. These enrichments are **not official NASA classifications** and may contain errors.

Geographic study areas represent places referenced or studied by projects, not necessarily the locations of participating teams. The current search application uses text-based geographic references rather than geocoded coordinates.

These datasets are historical snapshots and are not automatically synchronized with NASA's website. Original project descriptions and links remain attributable to their respective sources.

## Reproducibility and deployment

**Important:** This is a historical code collection assembled from the development project, not a turnkey reproducible build. Several scripts retain original relative paths, dependencies, and assumptions; the enrichment scripts may require Ollama, a local model, and original data. Public API structures may change. Review scripts before running network collection.

The app files combine the Cloudflare starter configuration with the latest available study-area-search patch. **Test and reconcile against the actual working deployment before publishing.** The D1 export script may need study-area schema/data added separately.

The downloadable SQLite snapshots provide access to the collected and enriched data without requiring users to rerun the collection or language-model pipeline.

See `app/README.md` and `pipeline/README.md` for details.