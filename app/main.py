from datetime import datetime, timezone
from uuid import UUID
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.logic import LIMITS, active_condition
from app.models import Link, User
from app.oauth import router as oauth_router
from app.schemas import LinkCreate, LinkOut, Register, UserOut
from app.security import current_user, hash_password

app = FastAPI(title="URL Shortener — OAuth2 Authorization Code + PKCE",
              swagger_ui_init_oauth={"clientId": "swagger-ui", "usePkceWithAuthorizationCodeGrant": True})
app.include_router(oauth_router)


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}


@app.post("/auth/register", response_model=UserOut, status_code=201, tags=["Users"])
async def register(data: Register, db: AsyncSession = Depends(get_db)):
    user = User(email=data.email.lower(), password_hash=hash_password(data.password), role="user")
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Email already registered")
    await db.refresh(user)
    return user


@app.get("/auth/me", response_model=UserOut, tags=["Users"])
async def me(user: User = Depends(current_user)):
    return user


@app.post("/links", response_model=LinkOut, status_code=201, tags=["Links"])
async def create_link(data: LinkCreate, response: Response, user: User = Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    # Lock the owner's row: serializes concurrent creates for one user.
    await db.execute(select(User).where(User.id == user.id).with_for_update())
    now = datetime.now(timezone.utc)
    original = str(data.original_url)
    existing = (await db.execute(select(Link).where(Link.user_id == user.id,
                    Link.original_url == original, active_condition(now)).order_by(Link.id).limit(1))).scalar_one_or_none()
    if existing:
        response.status_code = 200
        await db.commit()
        return existing
    active_count = (await db.execute(select(func.count(Link.id)).where(
        Link.user_id == user.id, active_condition(now)))).scalar_one()
    if active_count >= LIMITS.get(user.role, 3):
        await db.rollback()
        raise HTTPException(409, "Active links limit reached")
    if data.expires_at is not None and data.expires_at <= now:
        await db.rollback()
        raise HTTPException(422, "expires_at must be in the future")
    link = Link(user_id=user.id, original_url=original, expires_at=data.expires_at,
                max_clicks=data.max_clicks)
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


@app.get("/links", response_model=list[LinkOut], tags=["Links"])
async def list_links(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(Link).where(Link.user_id == user.id,
                                           Link.deleted_at.is_(None)).order_by(Link.id))).scalars().all()


@app.delete("/links/{link_id}", status_code=204, tags=["Links"])
async def delete_link(link_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(update(Link).where(Link.id == link_id, Link.user_id == user.id,
                                               Link.deleted_at.is_(None))
                              .values(deleted_at=datetime.now(timezone.utc)).returning(Link.id))
    if result.scalar_one_or_none() is None:
        await db.rollback()
        raise HTTPException(404, "Link not found")
    await db.commit()
    return Response(status_code=204)


@app.get("/{code}", tags=["Redirects"], responses={302: {"description": "Redirect"},
                                                   419: {"description": "Expired or max clicks reached"}})
async def redirect(code: str, db: AsyncSession = Depends(get_db)):
    try:
        link_code = UUID(code)
    except ValueError:
        raise HTTPException(404, "Link not found")
    now = datetime.now(timezone.utc)
    # Atomic conditional increment: never exceeds max_clicks under concurrency.
    result = await db.execute(update(Link).where(Link.code == link_code, active_condition(now))
                              .values(clicks=Link.clicks + 1).returning(Link.original_url))
    url = result.scalar_one_or_none()
    if url:
        await db.commit()
        return RedirectResponse(url=url, status_code=302)
    await db.rollback()
    link = (await db.execute(select(Link).where(Link.code == link_code))).scalar_one_or_none()
    if link is None or link.deleted_at is not None:
        raise HTTPException(404, "Link not found")
    raise HTTPException(419, "Link expired or click limit reached")
