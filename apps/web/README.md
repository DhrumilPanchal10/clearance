# Clearance — Web

Next.js 15 (App Router) + Tailwind frontend for the Clearance prior-auth
platform. Role-based views for coordinators, clinicians, and managers, with a
live case timeline streamed over SSE and an evidence-vs-criteria table where
every clinical claim is cited to a FHIR resource.

## Run the whole thing (no infrastructure)

Two terminals, from the repo root:

```bash
# 1) Backend — zero-infra demo API (no Postgres, payer, Temporal, or LLM)
make demo-api            # → http://localhost:8080  (seeds ~7 sample cases)

# 2) Frontend
make web                 # → http://localhost:3000
```

Open http://localhost:3000. Use the **role switcher** in the top-right to move
between `coordinator`, `clinician`, and `manager` and watch the queues, the
approval gate, and the escalation rules change.

## How auth works here

There is no Clerk key in dev, so the backend runs in **dev-header mode**: the
web app sends `X-Role` / `X-Tenant` headers chosen by the role switcher. In
production, set `CLERK_SECRET_KEY` on the API and the same JWT claims
(`role`, `tenant`) flow through unchanged.

## Pages

| Route           | Who          | Shows                                                        |
| --------------- | ------------ | ----------------------------------------------------------- |
| `/`             | everyone     | Pipeline KPIs, quick links, recent cases                    |
| `/cases`        | coordinator  | The working queue with stage filters                        |
| `/cases/[id]`   | everyone     | Live timeline, criteria + citations, letter, approve/reject |
| `/inbox`        | clinician    | Cases blocked on a clinical gap to confirm                  |
| `/manager`      | manager      | Escalated cases + the learned per-payer playbook            |

## Build

```bash
npm install
npm run build          # standalone build (talks to the FastAPI backend)
npm run build:static   # static export for GitHub Pages (in-browser engine)
```

Configure `API_BASE_URL` (default `http://localhost:8080`) in `.env.local` to
point at a different backend; `/api/*` is proxied there by `next.config.mjs`.

## Vercel (recommended, no backend)

The cleanest hosted demo. The same in-browser engine runs client-side, so no
backend is needed. From the repo:

```bash
npm i -g vercel
cd apps/web && vercel --prod      # deploys this folder; vercel.json enables the engine
```

Or import the repo in the Vercel dashboard and set **Root Directory → `apps/web`**.
`apps/web/vercel.json` already sets the build to engine mode, so it works with no
extra config. You get a clean `https://<project>.vercel.app` URL.

## GitHub Pages (no backend)

GitHub Pages serves static files only, so the static build swaps the FastAPI
backend for an **in-browser engine** (`lib/mockEngine.ts`) — a faithful port of
`clearance.api.demo` that loads the real checklists and drives cases through the
same state machine entirely client-side. The whole product is clickable with no
server.

- Push to `main`; the `.github/workflows/pages.yml` workflow builds the static
  export and deploys it. In the repo, enable **Settings → Pages → Source: GitHub
  Actions** once.
- It auto-detects the project base path (`/<repo>`), so links and assets resolve
  under `https://<user>.github.io/<repo>/`.
- Toggle manually with `NEXT_PUBLIC_STATIC=1` and `NEXT_PUBLIC_BASE_PATH=/<repo>`.
