# Deploying the doctor study link (Vercel + Railway)

The study is used like this: you send a doctor a link and an invite code. The doctor enters the code, accepts the consent, fills in their details, then works through the cases. The app is deployed as three pieces:

| Piece | Where | Notes |
|---|---|---|
| Web app (`web/`) | Vercel | Static Vite build; `web/vercel.json` sends every route to `index.html` |
| API (repo root `Dockerfile`) | Railway service `api` | `railway.json` runs the migrations, then starts uvicorn on `$PORT` |
| Postgres | Railway Postgres plugin | Holds study events, invites, consents and participants |
| FalkorDB | Railway service `falkordb` (image `falkordb/falkordb:latest`, volume on `/data`) | The evidence graph the Athena arm's chatbot uses |

Expect about $5–20 a month on Railway. The API image includes torch, which takes about 2 GB, so give the service at least 2 GB of RAM. Vercel's free tier is enough.

## 1. Railway (backend)

Nothing here has been run against a real Railway project yet.

1. Install the CLI with `npm i -g @railway/cli`, then run `railway login`. **You run this yourself.**
2. From `athena/Athena`, create the project and services:
   ```bash
   railway init
   railway add --database postgres
   railway add --image falkordb/falkordb:latest --service falkordb
   railway add --service api
   ```
   In the dashboard, attach a volume to `falkordb` and confirm the mount path against the image's data directory. Do not give `falkordb` or Postgres a public domain: FalkorDB has no password here.
3. Set the `api` variables from [`study.env.example`](study.env.example). Paste the LLM key into the dashboard, and set a spending limit on it with the provider.
4. Deploy with `railway up --service api`, then generate a public domain for `api` only. Run a single replica: chat sessions, the chat cap and the wrong-code limit live in memory.
5. Load the evidence graph. `railway run` executes on your own machine and cannot reach the private network, so use `railway ssh`:
   ```bash
   railway ssh --service api -- python -m secondlook.tier1.civic_loader
   ```
   The chat reads CIViC evidence only. It has no trial matching or access-pathway lookup.
6. Check the lock: `curl -i https://<api>/api/chat/sessions` must return 401, and `/docs` must return 404.

### Client IPs

By default the wrong-code limit sees the proxy's address, so all doctors share 10 failed attempts an hour. Railway documents `X-Real-IP` but does not say it overwrites a client-sent value. Before setting `STUDY_TRUSTED_IP_HEADER=x-real-ip`, send a request with a fake `X-Real-IP` and confirm the stored consent IP is not the fake one.

## 2. Vercel (frontend)

```bash
npm i -g vercel && vercel login          # you
cd athena/Athena/web
vercel link                              # new project, root = web/
vercel env add VITE_API_BASE production        # https://<api>.up.railway.app
vercel env add VITE_CHAT_API_BASE production   # same URL
vercel env add VITE_STUDY_API_BASE production  # same URL
vercel --prod
```

Then set `ATHENA_CORS_ORIGINS` on Railway to the exact Vercel production URL and redeploy the API.

## 3. Create invite codes

```bash
railway ssh --service api -- python -m secondlook.study.invites create --n 12 --expires-days 30
```

The codes are printed **once** and only their hashes are stored, so keep the output somewhere safe. Give each doctor one code and the link `https://<project>.vercel.app/join`.

Create codes in even numbers: doctors are paired (1 with 2, 3 with 4, ...), and arms balance only if both finish. The case pool may be 8 to 16.

To revoke a code, run `railway ssh --service api -- python -m secondlook.study.invites revoke --index K`.

## 4. Export data (admin)

```bash
curl -H "X-Athena-Api-Key: $ATHENA_API_KEY" https://<api>/api/study/admin/events.csv -o events.csv
curl -H "X-Athena-Api-Key: $ATHENA_API_KEY" https://<api>/api/study/admin/participants.csv -o participants.csv
```

`events.csv` is pseudonymous. `participants.csv` contains identifying details, so store it separately and restrict who can see it.

## Before sending to real doctors

- [ ] The consent text (`docs/research/athena-vs-usual-care-consent-v0.1.md`) has been reviewed, its placeholders filled in, and ethics or institutional approval obtained. After editing, copy it to `src/secondlook/study/consent/`; a test checks the two copies match.
- [ ] The case set has been reviewed by a clinician (`review_status: clinician_reviewed`, citations verified), and `ATHENA_STUDY_ALLOW_UNREVIEWED` has been removed.
- [ ] Migrations have run on Postgres and one full case per arm has been completed on the deployed site, with real chat messages.
- [ ] The chatbot model is pinned (`ATHENA_STUDY_CHAT_MODEL`, plus `ATHENA_LLM_MODEL` if used), and the model ID is recorded in the protocol.
- [ ] A dry run with a test code worked end to end. Afterwards, revoke the test code and delete its rows.
