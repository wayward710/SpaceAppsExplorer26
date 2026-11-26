# Cloudflare application

Requires Node.js, npm, Wrangler, a Cloudflare D1 database and exported SQL data.

1. `npm install`
2. `npx wrangler login`
3. `npx wrangler d1 create spaceapps-catalog`
4. Set the real D1 `database_id` in `wrangler.toml`.
5. Generate SQL with `python scripts/export_d1.py --help` and import it with `npx wrangler d1 execute ... --file=...`.
6. `npm run dev` to test locally.

**Integration note:** The frontend/Worker are from the study-area-search patch; the exporter is from the earlier Cloudflare starter. The exporter does not necessarily populate the study-area tables expected by this frontend. Reconcile with your actual latest working app and import process before deployment.

Do not commit exported D1 SQL or private configuration.
