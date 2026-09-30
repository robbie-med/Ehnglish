# Deploying on the owner's PC

The stack is three containers (`db`, `api`, `worker`) from `deploy/docker-compose.yml`, reachable
only on `127.0.0.1:3305`, published as `https://english.bo-bob.com` through the shared
`diet-loggers` Cloudflare Tunnel, with Cloudflare Access in front.

## One-time setup

1. **Secrets.** `cp deploy/.env.example deploy/.env`, set a random `POSTGRES_PASSWORD`.
   `deploy/.env` is gitignored and lives only on the server.
2. **Cloudflare Access app.** `deploy/cf-access-app.sh` creates a self-hosted Access application for
   `english.bo-bob.com` with an allow policy for the two login emails, and prints the application
   audience (AUD). Put it in `deploy/.env` as `EHNGLISH_CF_ACCESS_AUD`. The script reads the API
   token from `CLOUDFLARE_API_TOKEN_FILE` (default `~/Projects/Dad/cloudflare_admin`).
3. **Tunnel ingress + DNS.** `deploy/tunnel-add-ingress.sh` inserts
   `english.bo-bob.com -> http://localhost:3305` into `~/.cloudflared/diet-loggers.yml` (backup taken),
   validates, creates the CNAME with `cloudflared tunnel route dns`, and restarts the tunnel service.
4. **Start.** `make up` (builds the image, runs migrations, starts api + worker).

## Day to day

```bash
make up        # rebuild + restart after a git pull
make logs      # follow api/worker logs
make down
```

Migrations run automatically when the api container starts (`alembic upgrade head`).

## How identity works

Cloudflare Access authenticates the browser and adds `Cf-Access-Jwt-Assertion` to every request.
`server/app/auth.py` verifies that JWT against `https://sikoraweb.cloudflareaccess.com/cdn-cgi/access/certs`
with the configured AUD, takes the `email` claim, and (belt and braces) checks it against
`EHNGLISH_ALLOWED_EMAILS`. There is no app-level login. In `dev`/`test`, `EHNGLISH_DEV_EMAIL` stands in.

## Data

- Raw recordings and keystroke logs: `data/raw/sessions/<session>/…` (bind-mounted into the containers).
  Never deleted by the app. Back up with a plain copy.
- Postgres: named volume `ehnglish_pgdata`. `docker compose exec db pg_dump -U ehnglish ehnglish > backup.sql`.

## Checks

```bash
curl -s http://127.0.0.1:3305/api/health          # {"ok":true,...}
curl -sI https://english.bo-bob.com/ | head -1     # 302 to the Access login when not signed in
```
