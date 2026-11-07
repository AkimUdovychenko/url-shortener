"""Minimal educational OAuth2 Authorization Code + PKCE S256 server (one public client)."""
import base64
import hashlib
import html
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.config import settings
from app.models import AuthorizationCode, User
from app.security import create_token, sha256, verify_password

router = APIRouter(tags=["OAuth2 Authorization Code + PKCE"])
CLIENT_ID = "swagger-ui"
REDIRECT_PATH = "/docs/oauth2-redirect"


def validate_client(client_id: str, redirect_uri: str):
    # Validate origin AND exact path: no arbitrary external redirect URI allowed.
    from urllib.parse import urlsplit
    parsed = urlsplit(redirect_uri)
    if (client_id != CLIENT_ID or parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.port != 8000 or parsed.path != REDIRECT_PATH
            or parsed.query or parsed.fragment):
        raise HTTPException(400, "Invalid client or redirect_uri")


def validate_pkce(challenge: str, method: str):
    if method != "S256" or not re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge):
        raise HTTPException(400, "PKCE S256 required")


def login_page(params: dict, error: str = "") -> str:
    hidden = "".join(f'<input type="hidden" name="{html.escape(k, quote=True)}" value="{html.escape(v, quote=True)}">' for k, v in params.items())
    message = f'<p style="color:#b91c1c">{html.escape(error)}</p>' if error else ""
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>URL Shortener Login</title>
<style>body{{font-family:Arial;max-width:400px;margin:10vh auto;padding:24px}}input{{display:block;padding:10px;margin:10px 0;width:95%}}button{{padding:12px 20px;cursor:pointer}}</style></head><body>
<h2>URL Shortener — Sign in</h2><p>Enter the account created via POST /auth/register.</p>{message}
<form method="post" action="/oauth/authorize">{hidden}<input type="email" name="email" placeholder="Email" required>
<input type="password" name="password" placeholder="Password" required><button type="submit">Sign in</button></form></body></html>'''


@router.get("/oauth/authorize", response_class=HTMLResponse, include_in_schema=False)
async def authorize_form(response_type: str, client_id: str, redirect_uri: str,
                         code_challenge: str, code_challenge_method: str, state: str = "", scope: str = ""):
    validate_client(client_id, redirect_uri)
    validate_pkce(code_challenge, code_challenge_method)
    if response_type != "code":
        raise HTTPException(400, "response_type must be code")
    return login_page(dict(response_type=response_type, client_id=client_id, redirect_uri=redirect_uri,
                           code_challenge=code_challenge, code_challenge_method=code_challenge_method,
                           state=state, scope=scope))


@router.post("/oauth/authorize", include_in_schema=False)
async def authorize_submit(response_type: str = Form(...), client_id: str = Form(...),
                           redirect_uri: str = Form(...), code_challenge: str = Form(...),
                           code_challenge_method: str = Form(...), state: str = Form(""), scope: str = Form(""),
                           email: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)):
    validate_client(client_id, redirect_uri)
    validate_pkce(code_challenge, code_challenge_method)
    if response_type != "code":
        raise HTTPException(400, "response_type must be code")
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        p = dict(response_type=response_type, client_id=client_id, redirect_uri=redirect_uri,
                 code_challenge=code_challenge, code_challenge_method=code_challenge_method,
                 state=state, scope=scope)
        return HTMLResponse(login_page(p, "Incorrect email or password"), status_code=401)
    raw_code = secrets.token_urlsafe(32)
    db.add(AuthorizationCode(code_hash=sha256(raw_code), user_id=user.id, client_id=client_id,
                             redirect_uri=redirect_uri, code_challenge=code_challenge,
                             expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)))
    await db.commit()
    return RedirectResponse(redirect_uri + "?" + urlencode({"code": raw_code, "state": state}), status_code=303)


@router.post("/oauth/token")
async def exchange_code(grant_type: str = Form(...), code: str = Form(...), redirect_uri: str = Form(...),
                        client_id: str = Form(...), code_verifier: str = Form(...),
                        db: AsyncSession = Depends(get_db)):
    if grant_type != "authorization_code":
        raise HTTPException(400, "unsupported_grant_type")
    validate_client(client_id, redirect_uri)
    if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", code_verifier):
        raise HTTPException(400, "invalid_grant")
    expected = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
    now = datetime.now(timezone.utc)
    # Atomic single-use claim: concurrent requests cannot redeem one code twice.
    result = await db.execute(
        update(AuthorizationCode)
        .where(AuthorizationCode.code_hash == sha256(code), AuthorizationCode.client_id == client_id,
               AuthorizationCode.redirect_uri == redirect_uri, AuthorizationCode.code_challenge == expected,
               AuthorizationCode.used_at.is_(None), AuthorizationCode.expires_at > now)
        .values(used_at=now).returning(AuthorizationCode.user_id)
    )
    user_id = result.scalar_one_or_none()
    if user_id is None:
        await db.rollback()
        raise HTTPException(400, "invalid_grant")
    await db.commit()
    return {"access_token": create_token(user_id), "token_type": "bearer", "expires_in": settings.access_token_minutes * 60}
