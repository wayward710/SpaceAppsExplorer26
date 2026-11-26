# Data pipeline

`collection/` contains the original data acquisition and SQLite build tools. `collect_teams.py` is a renamed and minimally adapted copy of `test_scrape_complete.py`; it loads the adjacent `teams.graphql` rather than a browser-captured JSON file. The original is preserved in `experiments/api/`. The event ID and output paths are still hardcoded to the historical 2026 run.

`enrichment/` contains local Qwen processing and consolidation. `validation/` contains auditing utilities. `search/` preserves the earlier local SQLite search. `experiments/` documents investigations (GraphQL, ontology, keywords, geography and superseded scripts).

**Cautions:** Some scripts were one-off experiments, may have hardcoded local paths, and may depend on files omitted from the repository. In particular, inspect `collect_memberships.py` for disabled TLS verification (`verify=False`) before reuse. Avoid publishing scraped participant details or raw member datasets.
