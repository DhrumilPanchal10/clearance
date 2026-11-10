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
npm run build      # typechecked production build
```

Configure `API_BASE_URL` (default `http://localhost:8080`) in `.env.local` to
point at a different backend; `/api/*` is proxied there by `next.config.mjs`.
