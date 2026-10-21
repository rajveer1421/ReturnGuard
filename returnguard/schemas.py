"""Structured outputs for every LLM agent. Gemini must return JSON matching these
models, so decisions never depend on searching free text for keywords."""
from typing import Literal

from pydantic import BaseModel, Field

View = Literal["front", "back", "side"]


# ── Delivery: identity fingerprint ─────────────────────────────────────────
class Identifier(BaseModel):
    kind: Literal["serial_number", "model_number", "batch_number", "barcode", "label_text", "brand_name"] = Field(
        description="What the printed text is.")
    text: str = Field(description="Exact transcription. Use '?' for any character you cannot read; never guess.")
    view: View = Field(description="Which photo it is visible in.")
    location: str = Field(description="Where on the product, e.g. 'round sticker on the base'.")


class Mark(BaseModel):
    view: View
    description: str = Field(description="A unit-specific feature: scratch, dent, rust, stain, sticker, worn paint.")


class ProductFingerprint(BaseModel):
    product_description: str = Field(description="One sentence: what the product is, its colours and materials.")
    category: Literal["electronics", "apparel", "home_kitchen", "other"]
    identifiers: list[Identifier] = Field(description="Printed text that identifies the product or this unit. Empty if none.")
    distinctive_marks: list[Mark] = Field(description="Wear, damage or unique marks on this unit. Empty if it looks new.")
    accessories: list[str] = Field(description="Removable parts visible in the photos (strap, lid, cable). Empty if none.")
    tags_attached: list[str] = Field(description="Brand tags, price tags or tamper-evident 'do not remove' return tags "
                                                 "attached to the product, with where they are. Empty if none.")


# ── Return: blind label reading ────────────────────────────────────────────
class LocationReading(BaseModel):
    location_id: int
    location_visible: bool = Field(description="Is this part of the product clearly visible in the return photos?")
    label_present: bool = Field(description="If visible: is there printed text or a label at this location?")
    transcribed_text: str = Field(description="Exact text read at this location, '' if none. Use '?' for unreadable characters.")


class ReturnReadout(BaseModel):
    readings: list[LocationReading]
    other_text_seen: list[str] = Field(description="Any other printed text visible on the returned product.")


# ── Return: visual inspection ──────────────────────────────────────────────
class ViewFinding(BaseModel):
    view: View
    verdict: Literal["same_unit", "different_unit", "inconclusive"]
    differences: list[str] = Field(description="Differences in the product itself only (not lighting, angle, background).")


class VisualInspection(BaseModel):
    findings: list[ViewFinding]
    color_consistent: bool = Field(description="Is the product's own colour consistent between delivery and return?")
    wear_change: Literal["none", "new_damage", "less_wear_than_delivered", "different_wear_pattern"] = Field(
        description="How the returned unit's wear/damage compares with the delivered unit.")
    accessories_change: str = Field(description="Accessories missing or added at return, '' if unchanged.")
    signs_of_use: list[str] = Field(description="Signs the item was used or worn after delivery: stains, sweat, makeup "
                                                "or kumkum marks, wear creases, pilling, loose threads, broken mirror-work "
                                                "or beads. Empty if it looks unused.")
    tags_status: Literal["intact", "removed_or_cut", "not_applicable"] = Field(
        description="Tags recorded at delivery: still attached, removed/cut, or there were none.")
    overall: Literal["same_unit", "different_unit", "inconclusive"]
    confidence: int = Field(ge=0, le=100, description="Confidence in the overall verdict, 0-100.")
    reason_consistency: Literal["consistent", "inconsistent", "not_applicable"] = Field(
        description="Do the photos support the customer's stated return reason?")
    evidence_summary: str = Field(description="2-4 sentences a human reviewer can check against the photos.")
