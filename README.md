# URL Shortener — FastAPI + OAuth2 Authorization Code Flow + PKCE

Educational URL shortener. Async FastAPI, PostgreSQL, SQLAlchemy, Alembic, Pydantic, OAuth2 Authorization Code with S256 PKCE, JWT, Argon2id, pytest.

## Windows / PowerShell start

1. Install **Python 3.11+**, **Docker Desktop** and **VS Code**. Run Docker Desktop.
2. Open the folder containing `docker-compose.yml` in VS Code.
3. In PowerShell terminal:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

Paste the last command's random result into `.env` as `SECRET_KEY=`. Never commit `.env`.

```powershell
docker compose up -d
alembic upgrade head
uvicorn app.main:app --reload
```

**Open `http://127.0.0.1:8000/docs` (use 127.0.0.1, not another hostname).**

### How to sign in using Authorization Code Flow

1. In `/docs`, execute **POST /auth/register** with `{"email":"student@example.com","password":"password123"}`.
2. Click **Authorize** in Swagger. It is configured for **Authorization Code + PKCE (S256)** with `client_id=swagger-ui` and no client secret.
3. Swagger redirects to the app's **login page**. Enter the registered email/password and submit.
4. Server creates a short-lived **one-time code**, sends it to Swagger's exact allowed redirect URL; Swagger exchanges it with PKCE `code_verifier` at `/oauth/token` for a **JWT**.
5. Click **Close** in Swagger and run `POST /links` with `{"original_url":"https://example.com","max_clicks":2}`. A 201 response gives you a UUID4 `code`.
6. Open `http://127.0.0.1:8000/<code>` in browser: redirect 302; after 2 successful opens it returns 419.
7. `GET /links` lists your non-deleted links; `DELETE /links/{id}` soft-deletes yours only.

**Role:** registration always creates `user` (limit 3). For a controlled demo of `premium` (limit 5), use:

```powershell
docker compose exec postgres psql -U shortener -d shortener -c "UPDATE users SET role='premium' WHERE email='student@example.com';"
```

### Rules

- Link is **active** if `deleted_at IS NULL`, not expired, and `clicks < max_clicks` if click limit exists.
- Redirect: active -> 302 plus atomic click increment; expired or exhausted -> 419; missing or soft-deleted -> 404.
- Same user + same original URL + active -> returns existing code (200), regardless of new limits.
- `user` max 3 active links, `premium` max 5; over limit -> 409.
- Per-user DB row lock prevents concurrent create races; atomic conditional UPDATE protects `max_clicks`.
- `GET /links` returns all user's **not deleted** links, including expired; it's a history view.
- No auth required to follow a short link, auth required for create/list/delete.

### Tests

Unit tests (no database needed):

```powershell
pytest -v tests/test_unit.py
```

Integration tests use a **separate** test database, and will be skipped until `TEST_DATABASE_URL` is provided:

```powershell
docker compose exec postgres psql -U shortener -d postgres -c "CREATE DATABASE shortener_test;"
$env:TEST_DATABASE_URL="postgresql+asyncpg://shortener:shortener@localhost:5432/shortener_test"
pytest -v
```

Integration tests **drop/recreate all test tables**. NEVER point `TEST_DATABASE_URL` at the main database.

### API table

| Method | Path | Description |
|---|---|---|
| POST | `/auth/register` | Register user |
| GET | `/auth/me` | Current user (JWT) |
| GET | `/oauth/authorize` | PKCE auth login HTML |
| POST | `/oauth/authorize` | Validate login, issue single-use code |
| POST | `/oauth/token` | Redeem authorization code + PKCE |
| POST | `/links` | Create / deduplicate / limit |
| GET | `/links` | List own non-deleted links |
| DELETE | `/links/{id}` | Soft delete own link |
| GET | `/{code}` | Redirect or 404 / 419 |

### Notes

This is a **local educational** OAuth2 implementation, not a production-grade identity provider. It permits one fixed public Swagger client and local callback addresses; use TLS and a mature authorization server for public deployment. A credential-entry form could also use anti-CSRF protection and login rate limiting in production. Do not expose the demo server directly to the Internet. Authorization Code + PKCE does **not** require Google accounts or Keycloak for this lab.
