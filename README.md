# Lotfi Career – Form Builder

Flask app for building public application forms (WPCF7-style templates), collecting
submissions with file uploads, and managing users/approvals from an admin panel.

- **Database:** PostgreSQL (SQLAlchemy + Alembic migrations, run automatically on startup)
- **Files:** stored on a persistent volume (`UPLOAD_PATH`, default `/usr/src/app/uploads`)
- **Multi-application:** several apps can share one PostgreSQL database – each uses its own schema (`DB_SCHEMA`)

## Configuration

Copy `.env.example` to `.env` and fill it in.

| Variable | Required | Description |
| --- | --- | --- |
| `SECRET_KEY` | yes (prod) | Long random string: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | yes (prod) | `postgresql://user:pass@host:5432/dbname` (`postgres://` also accepted) |
| `DB_SCHEMA` | recommended | Schema for this app's tables, e.g. `career`. Created automatically. |
| `UPLOAD_PATH` | recommended | Mount point of the persistent disk/volume for uploads |
| `SESSION_COOKIE_SECURE` | no | `true` by default in production (HTTPS-only cookies) |
| `AUTO_MIGRATE` | no | `true` by default; runs `flask db upgrade` on startup under a Postgres advisory lock |
| `RATELIMIT_STORAGE_URI` | no | e.g. `redis://…` to share rate limits between instances (default: per-process memory) |
| `PROXY_FIX_COUNT` | no | Number of reverse proxies in front of the app (default `1`) |

Production refuses to start without `SECRET_KEY` or with a non-PostgreSQL `DATABASE_URL`,
so data can never silently end up in an ephemeral SQLite file.

## Deploying

### Liara
1. Create a PostgreSQL database and set `DATABASE_URL`, `SECRET_KEY`, `DB_SCHEMA` and `FLASK_ENV=production` in the app's environment variables.
2. Create a disk named `disk1` (already referenced in `liara.json`); it is mounted at `/usr/src/app/uploads`.
3. `liara deploy`

### Docker Compose (self-hosted / local)
```bash
cp .env.example .env      # set SECRET_KEY and POSTGRES_PASSWORD
docker compose up -d --build
```
Data lives in the named volumes `pgdata` (database) and `uploads` (files) and survives rebuilds.

### Running several apps on one database
Point every app at the same `DATABASE_URL` and give each a different `DB_SCHEMA`
(e.g. `career`, `shop`). Each app gets its own tables and its own `alembic_version`,
and migrations of different apps never block each other. Give each app its own uploads volume.

## Local development
```bash
python -m venv venv && venv\Scripts\activate   # Windows
pip install -r requirements.txt
python run.py
```
Without `DATABASE_URL`, development falls back to SQLite in `app/db/` for convenience.

## Database migrations
```bash
flask db migrate -m "describe change"   # after editing app/models.py
flask db upgrade                        # also runs automatically on startup
```

## Security notes
- CSRF protection on every form (Flask-WTF), including public forms
- Form templates are sanitized (nh3) before rendering; submitted values are always escaped
- Login/registration/submission rate limiting; safe `next` redirects; session reset on login
- Secure/HttpOnly/SameSite cookies, HSTS, `nosniff`, `X-Frame-Options`
- Uploaded files get random names, are only served to the form owner, and non-images download as attachments
- The **first registered account becomes admin** – register it immediately after a fresh deploy
