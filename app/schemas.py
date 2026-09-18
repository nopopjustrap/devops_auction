"""Pydantic-схемы запросов и ответов HTTP API."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AuthCredentials(ApiModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[\w.-]+$")
    password: str = Field(min_length=8, max_length=128)


class UserOut(ApiModel):
    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime


class AuthStatusOut(ApiModel):
    registration_open: bool


class ParticipantCreate(ApiModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    phone: str | None = Field(default=None, max_length=30)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.lower()
        local, separator, domain = email.partition("@")
        if not separator or not local or "." not in domain:
            raise ValueError("email должен иметь вид name@example.com")
        return email


class ParticipantOut(ParticipantCreate):
    id: int
    is_active: bool
    created_at: datetime


class AuctionCreate(ApiModel):
    title: str = Field(min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def validate_period(self) -> "AuctionCreate":
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("starts_at и ends_at должны содержать часовой пояс")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at должен быть позже starts_at")
        return self


class AuctionOut(AuctionCreate):
    id: int
    status: str
    created_at: datetime


class LotCreate(ApiModel):
    seller_id: int = Field(gt=0)
    title: str = Field(min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    starting_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class LotOut(LotCreate):
    id: int
    auction_id: int
    status: str
    created_at: datetime


class SaleCreate(ApiModel):
    lot_id: int = Field(gt=0)
    buyer_id: int = Field(gt=0)
    final_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class SaleOut(SaleCreate):
    id: int
    sold_at: datetime


class RevenueReportOut(ApiModel):
    auction_id: int | None
    sales_count: int
    gross_revenue: Decimal
