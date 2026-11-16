# Running the agent on Cloudflare

The graded final run happens locally (`python -m triage run`). This folder runs the same Docker image
on Cloudflare Containers, for practice runs and the live session. Containers need the Workers Paid plan.

A Worker of about 70 lines exposes two routes and nothing else:

| Route | What it does |
|---|---|
| `GET /health` | `{"ok": true, "runs_enabled": ...}`, no secrets |
| `POST /run?dry_run=1&limit=3` | Starts one run of the agent, if none is running. Needs `Authorization: Bearer <RUN_TOKEN>`; refused with 423 while `RUN_ENABLED` is not `true` |

There is no reset route, on purpose: a reset after the final run would erase the scored run.

## Deploy (needs your approval: these steps change the Cloudflare account)

1. Create a Postgres database with pgvector that Cloudflare can reach (Neon Free, Frankfurt), and
   note its connection string.
2. `cd cloudflare`, then `npm install` and `npm run check`.
3. Write `secrets.json` (git-ignored) with `HELPDESK_BASE_URL`, `HELPDESK_API_KEY`, `CANDIDATE_EMAIL`,
   `GROQ_API_KEY`, `GEMINI_API_KEY`, `DATABASE_URL` (the Neon one) and a long random `RUN_TOKEN`;
   run `npx wrangler secret bulk secrets.json`, then delete the file.
4. `npx wrangler deploy` (Docker Desktop must be running; it builds `../Dockerfile`).

## Check it (practice window only)

```powershell
$W = "https://roosterly-triage.<subdomain>.workers.dev"
curl.exe -i "$W/health"
curl.exe -i -X POST "$W/run"                                   # expect 401
npx wrangler deploy --var RUN_ENABLED:true                      # allow practice runs
curl.exe -X POST "$W/run?dry_run=1&limit=3" -H "Authorization: Bearer $env:RUN_TOKEN"
npx wrangler tail roosterly-triage --format pretty
```

## After the final run

Run `python -m triage lock` locally, then `npx wrangler deploy` (back to `RUN_ENABLED=false`) or
`npx wrangler delete`. A live trigger must then answer 423.
