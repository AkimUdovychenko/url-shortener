from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator


class Register(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: int
    email: EmailStr
    role: str
    model_config = ConfigDict(from_attributes=True)


class LinkCreate(BaseModel):
    original_url: HttpUrl
    expires_at: datetime | None = None
    max_clicks: int | None = Field(default=None, ge=1)

    @field_validator("expires_at")
    @classmethod
    def timezone_required(cls, value: datetime | None):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("expires_at must include a timezone, e.g. Z")
        return value


class LinkOut(BaseModel):
    id: int
    original_url: str
    code: UUID
    expires_at: datetime | None
    clicks: int
    max_clicks: int | None
    deleted_at: datetime | None
    model_config = ConfigDict(from_attributes=True)
