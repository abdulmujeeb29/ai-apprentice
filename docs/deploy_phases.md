# Deploy phases, checklists and the apprentice's DevOps primer

Source of truth for the Interviewer, the Tutor and the vision model.
Facts about Thales Ops come from the thales-core / thalesops-agent code.

## What the apprentice already knows (traditional DevOps, in plain concepts)

Putting an app on the internet by hand means:
1. **Get the code onto a server.** SSH in, clone the repo, install the right language version.
2. **Package it.** Write a Dockerfile or install dependencies by hand.
3. **Keep it running.** systemd / PM2 / `docker run --restart`, so it comes back after a crash or reboot.
4. **Give it a front door.** A reverse proxy (nginx) that takes web traffic and hands it to the app.
5. **Make it secure.** An HTTPS certificate (certbot / Let's Encrypt) and renewals.
6. **Give it a name.** A DNS record pointing a domain at the server.
7. **Configure it.** Env vars: secrets, database address, debug flags.
8. **Ship changes safely.** Migrations, a new version, and rolling back if it breaks.
9. **Watch it.** Logs, latency, errors, CPU/memory.

The apprentice does NOT know how Thales Ops does these. That gap is what it asks about.

## Thales Ops phases (what the screen shows)

| Phase id | Screen | What Thales Ops does for you | Manual equivalent |
|---|---|---|---|
| `pick_repo` | Repositories list → "New Application" | Lists GitHub repos already connected | Cloning on the server, deploy keys |
| `configure` | Name + branch, **Detected Stack** card | Reads the repo without running it (nixpacks plan): language, framework, needed services (e.g. Postgres), migrations command, health endpoint, required env vars pre-filled | Reading the code yourself, writing a Dockerfile |
| `server` | "Deploy to" dropdown (only ONLINE servers) | Go agent on the server, heartbeat every 60s | SSH access, installing Docker |
| `build_settings` | Build method (Automatic/Nixpacks or Dockerfile), Exposed Port (default 8000, injected as $PORT) | Builds an image without a Dockerfile | Writing and maintaining a Dockerfile |
| `env_vars` | KEY / value rows (encrypted) | Stores secrets encrypted; detected keys pre-filled as blanks | `.env` files on the server, scp, risk of leaking |
| `deploying` | Timeline: Queued → Waiting for server → Building image → Starting container → Live; **Build Console** streaming | Builds, runs migrations BEFORE the swap, starts new container NEXT TO the old one, health-checks for 60s, only switches traffic if healthy | Manual downtime, hand-run migrations, praying |
| `live` | Live badge, subdomain link `<app>.apps.thalesops.com` | Caddy/nginx reverse proxy + automatic HTTPS + Cloudflare DNS record | nginx config + certbot + DNS by hand |
| `operate` | App Logs, metrics, Deployment History (Rollback), Auto-deploy toggle, Save & Restart env | p95 latency (warn 1s, critical 2s), 5xx rate (warn 1%, crit 3%), rollback without rebuild, auto-deploy on git push, AI diagnosis of failed deploys | Grepping logs over SSH, rebuilding old versions |

Failure categories Thales Ops shows: build error, dependency error, migration failure, config/env error, health check failed, crash on boot, timed out, infrastructure. Most common: app does not listen on `$PORT` → "did not become healthy within 60s — keeping the current version running".

## Per-phase coverage checklist (what the interviewer must understand)

For every phase the apprentice wants four things:
- **what**: what the expert did
- **why**: the reason / the judgment behind it
- **vs_manual**: what Thales Ops did that they would otherwise do by hand
- **risk**: what can go wrong, what they would never do, when they stop

## Demo task: deploy pay_with_thales

Env vars the app reads: `SECRET_KEY`, `DEBUG`, `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`, `SHOW_LOGIN_CODE_ON_SCREEN`, `EMAIL_BACKEND`.

Hidden rules the expert should teach (the apprentice discovers them by asking):
1. `DEBUG=0` in production. Debug pages leak settings and stack traces.
2. `SHOW_LOGIN_CODE_ON_SCREEN=0`. Otherwise anyone can sign in as anyone.
3. `CSRF_TRUSTED_ORIGINS` must include the new `https://<app>.apps.thalesops.com`, or every form returns 403.
4. Attach a managed Postgres (gives `DATABASE_URL`) and a fresh `SECRET_KEY`; never reuse the dev key, never SQLite in prod.
5. Before sharing the URL: timeline says Live, build console clean, open the app and sign in once, glance at logs.
