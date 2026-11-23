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

1. Install the CLI with `npm i -g @railway/cli`, then run `railway login`. **You run this yourself.**
2. Create the project and services:
   ```bash
   cd athena/Athena
   railway init                      # new project, e.g. "athena-study"
   railway add --database postgres
   railway add --service falkordb --image falkordb/falkordb:latest
   railway add --service api
   ```
   In the dashboard, attach a volume to `falkordb` mounted at `/data`.
3. Set the `api` service variables from [`study.env.example`](study.env.example):
   - Generate the three secrets with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
   - Paste the LLM key directly into the Railway dashboard. Don't put it in chat or in git.
4. Deploy the API with `railway up --service api`, then generate a public domain for it (Settings → Networking).
5. Load the evidence graph once. This step is needed for the Athena arm to give useful answers:
   ```bash
   railway run --service api python -m secondlook.tier1.civic_loader
   railway run --service api python -m secondlook.tier1.access_pathway_loader
   railway run --service api python -m secondlook.tier1.ctgov_loader --help   # pick the breast-cancer scope
   ```

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
railway run --service api python -m secondlook.study.invites create --n 12 --expires-days 30
```

The codes are printed **once** and only their hashes are stored, so keep the output somewhere safe. Give each doctor one code and the link `https://<project>.vercel.app/join`.

To revoke a code, run `python -m secondlook.study.invites revoke --index K`.

## 4. Export data (admin)

```bash
curl -H "X-Athena-Api-Key: $ATHENA_API_KEY" https://<api>/api/study/admin/events.csv -o events.csv
curl -H "X-Athena-Api-Key: $ATHENA_API_KEY" https://<api>/api/study/admin/participants.csv -o participants.csv
```

`events.csv` is pseudonymous. `participants.csv` contains identifying details, so store it separately and restrict who can see it.

## Before sending to real doctors

- [ ] The consent text (`docs/research/athena-vs-usual-care-consent-v0.1.md`) has been reviewed, its placeholders filled in, and ethics or institutional approval obtained. After editing, copy it to `src/secondlook/study/consent/`; a test checks the two copies match.
- [ ] The case set has been reviewed by a clinician (`review_status: clinician_reviewed`, citations verified), and `ATHENA_STUDY_ALLOW_UNREVIEWED` has been removed.
- [ ] The chatbot model is pinned (`ATHENA_STUDY_CHAT_MODEL`, plus `ATHENA_LLM_MODEL` if used), and the model ID is recorded in the protocol.
- [ ] A dry run with a test code worked end to end. Afterwards, revoke the test code and delete its rows.
