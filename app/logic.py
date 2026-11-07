from datetime import datetime, timezone
from sqlalchemy import and_, or_
from app.models import Link

LIMITS = {"user": 3, "premium": 5}


def active_condition(now: datetime | None = None):
    """One SQL condition used by redirect, duplicate checking and active-link limits."""
    now = now or datetime.now(timezone.utc)
    return and_(
        Link.deleted_at.is_(None),
        or_(Link.expires_at.is_(None), Link.expires_at > now),
        or_(Link.max_clicks.is_(None), Link.clicks < Link.max_clicks),
    )
