"""Public response models projected from the chatbot's validated catalog evidence."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, UUID4

from .evidence import citation, is_complete_attribute, rating_display, safe_text
from .semantic import PRICE_NOTICE


SESSION_EXAMPLE = "5151e1bc-f6b2-4d39-b781-c1d70165cabc"
DISCLAIMER = PRICE_NOTICE + " Currency is unspecified."
Marketplace = Literal["flipkart", "myntra"]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"session_id": SESSION_EXAMPLE, "message": "Find women's cotton kurtas under 1500"}],
    })
    session_id: UUID4
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1500)]


class SessionMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class SessionResponse(BaseModel):
    session_id: UUID4
    created_at: datetime
    expires_at: datetime
    busy: bool
    recent_messages: list[SessionMessage] = Field(description="Bounded message previews, up to 350 characters each.")


class Price(BaseModel):
    kind: Literal["price", "discounted_price", "retail_price"]
    amount: float
    amount_minor: int = Field(description="Exact dataset amount scaled by 100. This scale implies no currency.")
    currency: None = None


class Rating(BaseModel):
    raw: float
    display: str = Field(description="Rounded to two decimal places for display.")


class SourceCitation(BaseModel):
    source_file: str
    record_number: int
    source_record_id: str | None
    observed_at: str | None
    product_url: str | None


class Product(BaseModel):
    product_id: str = Field(description="Original marketplace product ID.")
    evidence_id: str = Field(description="Stable marketplace-qualified product reference.")
    name: str
    marketplace: Marketplace
    brand: str | None
    colour: str | None
    categories: list[str]
    prices: list[Price]
    rating: Rating | None
    overall_rating: Rating | None
    rating_count: int | None
    attributes: dict[str, list[str]]
    product_url: str | None
    citations: list[SourceCitation]
    conflicting_fields: list[str]


class Comparison(BaseModel):
    status: Literal["listed_products", "price_by_platform", "identical", "similar", "ambiguous", "no_reliable_match"]
    product_evidence_ids: list[str]
    anchor_evidence_id: str | None
    identical_match_evidence_id: str | None


class ChatResponse(BaseModel):
    session_id: UUID4
    answer: str
    action: str
    products: list[Product]
    comparison: Comparison | None
    historical_data_disclaimer: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    catalog_ready: bool
    dense_ready: bool
    warmup_enabled: bool


class ErrorResponse(BaseModel):
    detail: str


def project_product(item):
    facts = item["facts"]
    prices = [Price(kind=kind, amount=facts[kind] / 100, amount_minor=facts[kind])
              for kind in ("price", "discounted_price", "retail_price") if kind in facts]
    attributes = {}
    for key, values in facts.items():
        if not key.startswith("attribute:"):
            continue
        clean = [safe_text(value).strip() for value in values if is_complete_attribute(value)]
        if clean:
            attributes[safe_text(key.removeprefix("attribute:"))] = clean

    def rating(key):
        value = facts.get(key)
        return Rating(raw=value, display=rating_display(value)) if value is not None else None

    urls = {record["product_url"] for record in item["records"] if record["product_url"]}
    return Product(
        product_id=item["source_id"], evidence_id=item["evidence_id"], name=safe_text(item["name"]),
        marketplace=item["platform"], brand=facts.get("brand"), colour=facts.get("colour"),
        categories=facts.get("category", []), prices=prices, rating=rating("rating"),
        overall_rating=rating("overall_rating"), rating_count=facts.get("rating_count"),
        attributes=attributes, product_url=next(iter(urls)) if len(urls) == 1 else None,
        citations=[SourceCitation(source_file=item["source_file"], **record) for record in item["records"]],
        conflicting_fields=list(item["conflicts"]),
    )


def project_turn(identifier, turn):
    products = [project_product(item) for item in turn.evidence]
    comparison = None
    if turn.comparison or turn.action == "compare_results":
        comparison = Comparison(
            status=turn.comparison or "listed_products",
            product_evidence_ids=[product.evidence_id for product in products],
            anchor_evidence_id=turn.comparison_anchor,
            identical_match_evidence_id=turn.identical_match,
        )
    return ChatResponse(session_id=identifier, answer=turn.answer, action=turn.action, products=products,
                        comparison=comparison, historical_data_disclaimer=DISCLAIMER)
