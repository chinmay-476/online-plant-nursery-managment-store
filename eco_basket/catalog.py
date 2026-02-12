from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func

from plants import RUPEE, plants

from .database import db
from .models import CatalogOverride, ProductReview, ReviewModeration


CATEGORY_ICON_MAP = {
    "Indoor": "fas fa-couch",
    "Outdoor": "fas fa-tree",
    "Herbs": "fas fa-mortar-pestle",
    "Flowering": "fas fa-spa",
    "Succulents": "fas fa-seedling",
    "Fruit Plants": "fas fa-apple-alt",
    "Bonsai": "fas fa-leaf",
    "Seeds & Kits": "fas fa-box-open",
    "Pots & Planters": "fas fa-cube",
    "Air Purifying": "fas fa-wind",
    "Climbers": "fas fa-arrows-alt-v",
}

CATEGORY_DISPLAY_ORDER = [
    "Indoor",
    "Outdoor",
    "Herbs",
    "Flowering",
    "Succulents",
    "Air Purifying",
    "Fruit Plants",
    "Bonsai",
    "Seeds & Kits",
    "Pots & Planters",
    "Climbers",
]

SUNLIGHT_LABELS = {
    "low": "Low Light",
    "medium": "Partial Sun",
    "bright": "Bright Light",
    "full_sun": "Full Sun",
}

WATERING_LABELS = {
    "low": "Water Weekly",
    "medium": "Water 2-3x Weekly",
    "high": "Keep Moist",
}

DIFFICULTY_LABELS = {
    "easy": "Easy",
    "moderate": "Moderate",
    "advanced": "Advanced",
}

COUPON_RULES = {
    "GREEN10": {"type": "percent", "value": 10, "max_discount": 300, "min_subtotal": 399, "description": "10% off up to ₹300"},
    "PLANT75": {"type": "flat", "value": 75, "min_subtotal": 499, "description": "Flat ₹75 off on ₹499+"},
    "FREESHIP": {"type": "freeship", "value": 0, "min_subtotal": 299, "description": "Free delivery on ₹299+"},
}


def parse_price(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "")
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def normalize_coupon_code(raw_code: str | None) -> str:
    return str(raw_code or "").strip().upper()


def normalize_variant_code(raw_value: str | None) -> str:
    value = str(raw_value or "").strip().lower()
    if not value or value in {"default", "base"}:
        return ""
    return value


def split_catalog_plant_key(raw_plant_id: Any) -> tuple[str, str]:
    raw = str(raw_plant_id or "").strip()
    if "::" not in raw:
        return raw, ""
    base, variant = raw.split("::", 1)
    return base.strip(), normalize_variant_code(variant)


def build_catalog_plant_key(base_plant_id: str, variant_code: str | None = None) -> str:
    variant = normalize_variant_code(variant_code)
    if not variant:
        return base_plant_id
    return f"{base_plant_id}::{variant}"


def _stable_hash(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def _default_stock(plant_id: str) -> int:
    return 2 + (_stable_hash(f"stock:{plant_id}") % 18)


def _default_sunlight(plant_id: str) -> str:
    keys = list(SUNLIGHT_LABELS.keys())
    return keys[_stable_hash(f"sun:{plant_id}") % len(keys)]


def _default_watering(plant_id: str) -> str:
    keys = list(WATERING_LABELS.keys())
    return keys[_stable_hash(f"water:{plant_id}") % len(keys)]


def _default_difficulty(plant_id: str) -> str:
    keys = list(DIFFICULTY_LABELS.keys())
    return keys[_stable_hash(f"difficulty:{plant_id}") % len(keys)]


def _default_delivery_days(plant_id: str) -> int:
    return 1 + (_stable_hash(f"delivery:{plant_id}") % 4)


def get_catalog_with_marketplace_data(include_inactive: bool = False) -> dict[str, dict]:
    catalog: dict[str, dict] = {key: dict(value) for key, value in plants.items()}
    override_rows = CatalogOverride.query.all()
    for row in override_rows:
        if row.plant_id not in catalog:
            continue
        item = catalog[row.plant_id]
        if row.price_override is not None:
            item["price"] = f"{RUPEE}{int(row.price_override)}"
        if row.stock_override is not None:
            item["stock"] = int(row.stock_override)
        if row.offer_override is not None:
            item["offer"] = bool(row.offer_override)
        if row.new_override is not None:
            item["new"] = bool(row.new_override)
        item["active"] = bool(row.is_active)

    for item in catalog.values():
        item.setdefault("active", True)

    if include_inactive:
        return catalog
    return {key: value for key, value in catalog.items() if bool(value.get("active", True))}


def get_review_stats(plant_ids: list[str] | None = None) -> dict[str, dict]:
    query = db.session.query(
        ProductReview.plant_id,
        func.count(ProductReview.id).label("rating_count"),
        func.avg(ProductReview.rating).label("rating_avg"),
    ).outerjoin(
        ReviewModeration,
        ReviewModeration.review_id == ProductReview.id,
    ).filter(
        (ReviewModeration.status.is_(None)) | (ReviewModeration.status == "approved")
    )
    if plant_ids:
        query = query.filter(ProductReview.plant_id.in_(plant_ids))
    rows = query.group_by(ProductReview.plant_id).all()
    output: dict[str, dict] = {}
    for plant_id, rating_count, rating_avg in rows:
        output[str(plant_id)] = {
            "rating_count": int(rating_count or 0),
            "rating": round(float(rating_avg or 0), 1),
        }
    return output


def apply_review_stats_to_catalog(catalog: dict[str, dict]) -> None:
    stats = get_review_stats(list(catalog.keys()))
    for plant_id, item in catalog.items():
        row = stats.get(plant_id, {})
        if row:
            item["rating"] = float(row.get("rating", 0))
            item["rating_count"] = int(row.get("rating_count", 0))


def build_variant_options(plant_id: str, plant_data: dict) -> list[dict]:
    base_price = int(plant_data.get("price_value", parse_price(plant_data.get("price"))))
    base_stock = int(plant_data.get("stock", _default_stock(plant_id)))
    raw_variants = [
        ("standard", "Standard Pot", 0, 0),
        ("premium", "Premium Pot", int(base_price * 0.2), -1),
        ("jumbo", "Jumbo Pot", int(base_price * 0.45), -2),
    ]
    variants = []
    for code, label, delta, stock_delta in raw_variants:
        price_value = max(base_price + delta, 1)
        mrp_value = int(price_value * 1.18)
        stock = max(base_stock + stock_delta, 0)
        discount_percent = int(round(((mrp_value - price_value) / mrp_value) * 100)) if mrp_value > 0 else 0
        variants.append(
            {
                "code": code,
                "label": label,
                "price_delta": delta,
                "stock_delta": stock_delta,
                "price_value": price_value,
                "mrp_value": mrp_value,
                "stock": stock,
                "in_stock": stock > 0,
                "discount_percent": max(discount_percent, 0),
            }
        )
    return variants


def resolve_variant_option(plant_data: dict | None, variant_code: str | None = None) -> dict:
    if not plant_data:
        return {}
    variants = list(plant_data.get("variants") or [])
    if not variants:
        variants = build_variant_options(str(plant_data.get("id", "")), plant_data)
        plant_data["variants"] = variants
    wanted = normalize_variant_code(variant_code)
    if wanted:
        for item in variants:
            if item.get("code") == wanted:
                return item
    return variants[0] if variants else {}


def enrich_plant(plant_id: str, plant_data: dict) -> dict:
    item = dict(plant_data)
    item["id"] = plant_id
    item.setdefault("category", "Other")

    price_value = parse_price(item.get("price"))
    item["price_value"] = price_value
    mrp_value = int(item.get("mrp_value") or max(int(price_value * 1.2), price_value))
    item["mrp_value"] = mrp_value
    item["discount_percent"] = int(round(((mrp_value - price_value) / mrp_value) * 100)) if mrp_value > 0 else 0
    item["price"] = f"{RUPEE}{price_value}"

    item["rating"] = float(item.get("rating", 3.8))
    item["rating_count"] = int(item.get("rating_count", (_stable_hash(f"rc:{plant_id}") % 600) + 20))
    item["bestseller"] = bool(item.get("bestseller", item["rating_count"] > 250))

    stock = int(item.get("stock", _default_stock(plant_id)))
    item["stock"] = stock
    item["in_stock"] = stock > 0
    item["low_stock"] = 0 < stock <= 4

    delivery_min_days = int(item.get("delivery_min_days", _default_delivery_days(plant_id)))
    item["delivery_min_days"] = delivery_min_days
    item["delivery_text"] = "Delivery in 1-2 days" if delivery_min_days <= 2 else f"Delivery in {delivery_min_days}-{delivery_min_days + 1} days"
    item["fast_delivery"] = delivery_min_days <= 2
    item["assured"] = bool(item.get("assured", item["rating_count"] > 100))

    sunlight = str(item.get("sunlight", _default_sunlight(plant_id)))
    watering = str(item.get("watering", _default_watering(plant_id)))
    difficulty = str(item.get("difficulty", _default_difficulty(plant_id)))
    item["sunlight"] = sunlight
    item["watering"] = watering
    item["difficulty"] = difficulty
    item["sunlight_label"] = SUNLIGHT_LABELS.get(sunlight, "Partial Sun")
    item["watering_label"] = WATERING_LABELS.get(watering, "Water Weekly")
    item["difficulty_label"] = DIFFICULTY_LABELS.get(difficulty, "Moderate")
    item["pet_safe"] = bool(item.get("pet_safe", _stable_hash(f"pet:{plant_id}") % 3 != 0))
    item["air_purifying"] = bool(item.get("air_purifying", _stable_hash(f"air:{plant_id}") % 2 == 0))
    item.setdefault("active", True)
    item["variants"] = build_variant_options(plant_id, item)
    return item


def get_delivery_fee(subtotal: int) -> int:
    if subtotal >= 499:
        return 0
    return 49


def evaluate_coupon(subtotal: int, delivery_fee: int, raw_code: str | None) -> dict:
    code = normalize_coupon_code(raw_code)
    coupon = {
        "requested_code": code,
        "code": "",
        "applied": False,
        "discount": 0,
        "delivery_fee": int(delivery_fee),
        "description": "",
        "message": "",
    }
    if not code:
        return coupon

    rule = COUPON_RULES.get(code)
    if not rule:
        coupon["message"] = "Invalid coupon code."
        return coupon

    min_subtotal = int(rule.get("min_subtotal", 0))
    if subtotal < min_subtotal:
        coupon["message"] = f"Coupon valid on minimum order of ₹{min_subtotal}."
        return coupon

    coupon["code"] = code
    coupon["applied"] = True
    coupon["description"] = str(rule.get("description") or "")

    if rule["type"] == "percent":
        discount = int(subtotal * (int(rule["value"]) / 100))
        discount = min(discount, int(rule.get("max_discount", discount)))
    elif rule["type"] == "flat":
        discount = int(rule["value"])
    elif rule["type"] == "freeship":
        discount = 0
        coupon["delivery_fee"] = 0
    else:
        discount = 0

    coupon["discount"] = max(discount, 0)
    coupon["message"] = f"{code} applied successfully."
    return coupon


def cart_summary_for_user(user_id: int, coupon_code: str | None = None) -> dict:
    from .models import CartItem

    rows = CartItem.query.filter_by(user_id=user_id).order_by(CartItem.created_at.desc(), CartItem.id.desc()).all()
    catalog = get_catalog_with_marketplace_data()
    apply_review_stats_to_catalog(catalog)

    items = []
    subtotal = 0
    mrp_total = 0
    for row in rows:
        base_plant_id, variant_code = split_catalog_plant_key(row.plant_id)
        plant_data = catalog.get(base_plant_id)
        if not plant_data:
            continue
        plant = enrich_plant(base_plant_id, plant_data)
        variant = resolve_variant_option(plant, variant_code)
        unit_price = int(variant.get("price_value") or row.unit_price or plant["price_value"])
        mrp_unit_price = int(variant.get("mrp_value") or plant["mrp_value"])
        line_total = unit_price * int(row.quantity)
        mrp_line_total = mrp_unit_price * int(row.quantity)
        subtotal += line_total
        mrp_total += mrp_line_total
        items.append(
            {
                "id": row.id,
                "plant_id": base_plant_id,
                "plant_name": plant["name"],
                "plant_image": plant["image"],
                "category": plant.get("category", "Other"),
                "quantity": int(row.quantity),
                "unit_price": unit_price,
                "mrp_unit_price": mrp_unit_price,
                "line_total": line_total,
                "mrp_line_total": mrp_line_total,
                "variant_code": variant.get("code", ""),
                "variant_label": variant.get("label", ""),
                "delivery_text": plant.get("delivery_text", "Delivery in 2-4 days"),
            }
        )

    deal_discount = max(mrp_total - subtotal, 0)
    delivery_fee = get_delivery_fee(subtotal)
    coupon = evaluate_coupon(subtotal, delivery_fee, coupon_code)
    grand_total = max(subtotal - int(coupon["discount"]), 0) + int(coupon["delivery_fee"])
    total_savings = deal_discount + int(coupon["discount"])

    return {
        "items": items,
        "subtotal": subtotal,
        "mrp_total": mrp_total,
        "deal_discount": deal_discount,
        "delivery_fee": int(coupon["delivery_fee"]),
        "coupon": coupon,
        "grand_total": grand_total,
        "total_savings": total_savings,
    }


def wishlist_ids_for_user(user_id: int) -> list[str]:
    from .models import WishlistItem

    rows = WishlistItem.query.filter_by(user_id=user_id).order_by(WishlistItem.created_at.desc()).all()
    return [split_catalog_plant_key(row.plant_id)[0] for row in rows]


def normalize_wishlist_ids(values: list[str] | None) -> list[str]:
    output = []
    seen = set()
    for value in values or []:
        base, _ = split_catalog_plant_key(value)
        if base and base not in seen and base in plants:
            seen.add(base)
            output.append(base)
    return output


def support_chatbot_reply(message: str, history: list[dict] | None = None) -> str:
    text = (message or "").strip().lower()
    context = " ".join(str(item.get("text") or item.get("message") or "").lower() for item in (history or [])[-5:])
    merged = f"{context} {text}".strip()

    if any(word in merged for word in ["refund", "return", "replace", "damaged", "broken"]):
        return "I can help with returns/refunds. Share order ID, reason, and short details. You can also raise a support ticket for agent handling."
    if any(word in merged for word in ["delay", "late", "tracking", "where is my order"]):
        return "Please open Order History and click Track Order for latest status. If delayed by 48+ hours, raise a ticket and we will escalate."
    if any(word in merged for word in ["payment", "upi", "debited", "charged", "failed"]):
        return "For payment issues, share transaction reference, amount, and time. Reconciliation usually completes in 24-48 hours."
    if any(word in merged for word in ["cancel", "stop order"]):
        return "Cancellation is usually possible before shipment. Share your order ID and I will guide the next step."
    if any(word in merged for word in ["hello", "hi", "hey"]):
        return "Hello. Share your issue in one line and include order ID if available."
    return "Please share order ID and your issue category (delivery/payment/return/product quality)."


def delivery_date_text(order_date: datetime | None, status: str) -> str:
    if not order_date:
        return "TBD"
    key = str(status or "").lower()
    if key in {"delivered", "cancelled", "returned", "refunded"}:
        return "Completed"
    eta = order_date + timedelta(days=4)
    return eta.strftime("%d %b %Y")
