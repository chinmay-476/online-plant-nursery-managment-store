from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import selectinload

from forms import SupportTicketMessageForm
from plants import plants as seed_plants


ROLE_LABELS = {
    "customer": "Customer",
    "support": "Support Agent",
    "manager": "Manager",
    "admin": "Administrator",
}

RETURN_STATUS_LABELS = {
    "requested": "Requested",
    "approved": "Approved",
    "pickup_scheduled": "Pickup Scheduled",
    "received": "Received",
    "refunded": "Refunded",
    "rejected": "Rejected",
    "cancelled": "Cancelled",
}

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

CANNED_RESPONSES = [
    "Thanks for contacting us. I am checking this and will update you shortly.",
    "I have escalated your issue to the logistics team. You will receive an update within 24 hours.",
    "I understand the inconvenience. Please share a photo/video and we will process replacement support.",
    "Refund eligibility is usually confirmed within 2 business days after pickup.",
    "If payment is debited but order is not confirmed, please share the transaction reference.",
]

_BOUND_MODELS: dict[str, Any] = {}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _bind_models(db: Any, legacy: Any) -> dict[str, Any]:
    if _BOUND_MODELS:
        return _BOUND_MODELS

    Store = legacy.Store
    Order = legacy.Order
    ProductReview = legacy.ProductReview

    class UserProfile(db.Model):
        __tablename__ = "user_profile"

        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey(f"{Store.__tablename__}.id"), nullable=False, unique=True)
        role = db.Column(db.String(20), nullable=False, default="customer")
        loyalty_points = db.Column(db.Integer, nullable=False, default=0)
        referral_code = db.Column(db.String(32), nullable=True, unique=True)
        referred_by = db.Column(db.String(32), nullable=True)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(
            db.DateTime,
            nullable=False,
            default=datetime.utcnow,
            onupdate=datetime.utcnow,
        )
        user = db.relationship(Store, backref=db.backref("profile", uselist=False))

    class ReturnRequest(db.Model):
        __tablename__ = "return_request"

        id = db.Column(db.Integer, primary_key=True)
        order_id = db.Column(db.Integer, db.ForeignKey(f"{Order.__tablename__}.id"), nullable=False, index=True)
        user_id = db.Column(db.Integer, db.ForeignKey(f"{Store.__tablename__}.id"), nullable=False, index=True)
        reason = db.Column(db.String(150), nullable=False)
        details = db.Column(db.Text, nullable=False, default="")
        status = db.Column(db.String(30), nullable=False, default="requested")
        admin_note = db.Column(db.Text, nullable=True)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(
            db.DateTime,
            nullable=False,
            default=datetime.utcnow,
            onupdate=datetime.utcnow,
        )
        order = db.relationship(Order, backref=db.backref("return_request_record", uselist=False))
        user = db.relationship(Store, backref=db.backref("return_requests", lazy="dynamic"))

    class StockAlertSubscription(db.Model):
        __tablename__ = "stock_alert_subscription"

        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey(f"{Store.__tablename__}.id"), nullable=False, index=True)
        plant_id = db.Column(db.String(80), nullable=False, index=True)
        variant_code = db.Column(db.String(40), nullable=True)
        status = db.Column(db.String(20), nullable=False, default="pending")
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        user = db.relationship(Store, backref=db.backref("stock_alerts", lazy="dynamic"))
        __table_args__ = (
            db.UniqueConstraint("user_id", "plant_id", "variant_code", name="uq_stock_alert_user_plant_variant"),
        )

    class ReviewModeration(db.Model):
        __tablename__ = "review_moderation"

        id = db.Column(db.Integer, primary_key=True)
        review_id = db.Column(
            db.Integer,
            db.ForeignKey(f"{ProductReview.__tablename__}.id"),
            nullable=False,
            unique=True,
            index=True,
        )
        status = db.Column(db.String(20), nullable=False, default="pending")
        moderated_by = db.Column(db.String(120), nullable=True)
        moderated_at = db.Column(db.DateTime, nullable=True)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        review = db.relationship(ProductReview, backref=db.backref("moderation", uselist=False))

    _BOUND_MODELS.update(
        {
            "UserProfile": UserProfile,
            "ReturnRequest": ReturnRequest,
            "StockAlertSubscription": StockAlertSubscription,
            "ReviewModeration": ReviewModeration,
        }
    )
    return _BOUND_MODELS


def register_extensions(app: Any, db: Any, legacy: Any) -> None:
    if app.config.get("ECO_BASKET_EXTENSIONS_READY"):
        return

    models = _bind_models(db, legacy)
    UserProfile = models["UserProfile"]
    ReturnRequest = models["ReturnRequest"]
    StockAlertSubscription = models["StockAlertSubscription"]
    ReviewModeration = models["ReviewModeration"]

    Store = legacy.Store
    Order = legacy.Order
    WishlistItem = legacy.WishlistItem
    ProductReview = legacy.ProductReview
    SupportTicket = legacy.SupportTicket

    admin_required = getattr(legacy, "admin_required", lambda f: f)
    get_catalog_with_marketplace_data = legacy.get_catalog_with_marketplace_data
    enrich_plant = legacy.enrich_plant
    resolve_variant_option = legacy.resolve_variant_option
    build_variant_options = legacy.build_variant_options
    parse_price = legacy.parse_price
    apply_review_stats_to_catalog = getattr(legacy, "apply_review_stats_to_catalog", None)
    cart_summary_for_user = legacy.cart_summary_for_user
    support_chatbot_reply = legacy.support_chatbot_reply

    category_icon_map = getattr(legacy, "CATEGORY_ICON_MAP", {})
    category_display_order = list(getattr(legacy, "CATEGORY_DISPLAY_ORDER", []))
    support_category_labels = dict(getattr(legacy, "SUPPORT_CATEGORY_LABELS", {}))
    support_priority_labels = dict(getattr(legacy, "SUPPORT_PRIORITY_LABELS", {}))
    support_status_labels = dict(getattr(legacy, "SUPPORT_STATUS_LABELS", {}))
    coupon_rules = getattr(legacy, "COUPON_RULES", {})

    split_catalog_key_fn = getattr(legacy, "split_catalog_plant_key", None)
    build_catalog_key_fn = getattr(legacy, "build_catalog_plant_key", None)
    normalize_variant_fn = getattr(legacy, "normalize_variant_code", None)
    wishlist_ids_for_user_fn = getattr(legacy, "wishlist_ids_for_user", None)

    def split_catalog_key(raw_plant_id: Any) -> tuple[str, str]:
        if callable(split_catalog_key_fn):
            return split_catalog_key_fn(raw_plant_id)
        raw = str(raw_plant_id or "").strip()
        if "::" not in raw:
            return raw, ""
        base, variant = raw.split("::", 1)
        return base.strip(), variant.strip()

    def build_catalog_key(base_plant_id: str, variant_code: str | None = None) -> str:
        if callable(build_catalog_key_fn):
            return build_catalog_key_fn(base_plant_id, variant_code)
        variant = _normalize_variant(variant_code)
        if not variant:
            return base_plant_id
        return f"{base_plant_id}::{variant}"

    def _normalize_variant(raw_value: Any) -> str:
        if callable(normalize_variant_fn):
            return normalize_variant_fn(raw_value)
        value = str(raw_value or "").strip().lower()
        if not value or value == "base":
            return ""
        return value

    def _current_user_id() -> int | None:
        if "user_id" not in session:
            return None
        return _safe_int(session.get("user_id"), 0) or None

    def _require_user() -> int | None:
        user_id = _current_user_id()
        if user_id is None:
            flash("Please login to continue", "warning")
            return None
        return user_id

    def _is_admin_email(email: str | None) -> bool:
        admin_emails = {
            item.strip().lower()
            for item in str(app.config.get("ADMIN_EMAILS", "")).split(",")
            if item.strip()
        }
        return _lower(email) in admin_emails

    def _get_or_create_profile(user_id: int) -> Any:
        profile = UserProfile.query.filter_by(user_id=user_id).first()
        if profile is None:
            profile = UserProfile(user_id=user_id, role="customer", loyalty_points=0)
            db.session.add(profile)
            db.session.flush()
        return profile

    def _wishlist_ids(user_id: int) -> list[str]:
        if callable(wishlist_ids_for_user_fn):
            values = wishlist_ids_for_user_fn(user_id) or []
            return [split_catalog_key(item)[0] for item in values if item]
        rows = WishlistItem.query.filter_by(user_id=user_id).all()
        return [split_catalog_key(row.plant_id)[0] for row in rows]

    def _review_status_map(review_ids: list[int]) -> dict[int, str]:
        if not review_ids:
            return {}
        rows = ReviewModeration.query.filter(ReviewModeration.review_id.in_(review_ids)).all()
        status_map = {row.review_id: _lower(row.status) or "pending" for row in rows}
        for review_id in review_ids:
            status_map.setdefault(review_id, "approved")
        return status_map

    def _build_recommendations(catalog: dict[str, dict], user_id: int | None, limit: int = 6) -> list[dict]:
        enriched = [enrich_plant(pid, pdata) for pid, pdata in catalog.items()]
        if not enriched:
            return []

        preference_counter: Counter[str] = Counter()
        if user_id is not None:
            order_rows = (
                Order.query.filter_by(user_id=user_id)
                .order_by(Order.order_date.desc(), Order.id.desc())
                .limit(40)
                .all()
            )
            for row in order_rows:
                base_id, _ = split_catalog_key(row.plant_id)
                plant = catalog.get(base_id)
                if plant:
                    preference_counter[str(plant.get("category", "Other"))] += 2

            for base_id in _wishlist_ids(user_id):
                plant = catalog.get(base_id)
                if plant:
                    preference_counter[str(plant.get("category", "Other"))] += 1

        def score(item: dict) -> tuple:
            category = str(item.get("category", "Other"))
            return (
                int(item.get("in_stock", True)),
                preference_counter.get(category, 0),
                float(item.get("rating", 0)),
                int(item.get("rating_count", 0)),
                int(item.get("bestseller", False)),
            )

        ranked = sorted(enriched, key=score, reverse=True)
        return ranked[:limit]

    def _verified_purchase(user_id: int, base_plant_id: str) -> bool:
        purchases = Order.query.filter_by(user_id=user_id).all()
        for row in purchases:
            pid, _ = split_catalog_key(row.plant_id)
            if pid == base_plant_id:
                return True
        return False

    def _ensure_order_runtime_properties() -> None:
        if not hasattr(Order, "base_plant_id"):
            Order.base_plant_id = property(lambda self: split_catalog_key(getattr(self, "plant_id", ""))[0])
        if not hasattr(Order, "variant_code"):
            Order.variant_code = property(lambda self: split_catalog_key(getattr(self, "plant_id", ""))[1])
        if not hasattr(Order, "tracking_code"):
            Order.tracking_code = property(lambda self: f"TRK{getattr(self, 'id', 0):07d}")
        if not hasattr(Order, "estimated_delivery_date"):
            Order.estimated_delivery_date = property(
                lambda self: (
                    getattr(self, "order_date", None) + timedelta(days=4)
                    if getattr(self, "order_date", None)
                    else datetime.utcnow() + timedelta(days=4)
                )
            )

    def _ensure_ticket_runtime_properties(ticket: Any) -> None:
        if getattr(ticket, "created_at", None) is None:
            ticket.due_at = None
            ticket.escalated = False
            ticket.escalation_level = 0
            return
        due_map = {"urgent": 4, "high": 8, "medium": 24, "low": 48}
        hours = due_map.get(_lower(ticket.priority), 24)
        due_at = ticket.created_at + timedelta(hours=hours)
        escalated = _lower(ticket.status) not in {"resolved", "closed"} and datetime.utcnow() > due_at
        ticket.due_at = due_at
        ticket.escalated = escalated
        ticket.escalation_level = 2 if escalated else 0

    def _apply_loyalty_to_summary(summary: dict, user_id: int) -> tuple[int, int]:
        profile = _get_or_create_profile(user_id)
        available_points = max(_safe_int(profile.loyalty_points, 0), 0)

        coupon = summary.get("coupon", {}) or {}
        subtotal = _safe_int(summary.get("subtotal"), 0)
        coupon_discount = _safe_int(coupon.get("discount"), 0)
        coupon_adjusted_subtotal = max(subtotal - coupon_discount, 0)
        max_discount = min(available_points, int(coupon_adjusted_subtotal * 0.2))

        requested_discount = _safe_int(session.get("cart_loyalty_discount"), 0)
        loyalty_discount = min(max(requested_discount, 0), max_discount)

        summary["grand_total"] = max(_safe_int(summary.get("grand_total"), 0) - loyalty_discount, 0)
        summary["total_savings"] = _safe_int(summary.get("total_savings"), 0) + loyalty_discount
        return available_points, loyalty_discount

    def _prepare_catalog() -> dict[str, dict]:
        catalog = get_catalog_with_marketplace_data()
        if callable(apply_review_stats_to_catalog):
            try:
                apply_review_stats_to_catalog(catalog)
            except Exception:
                pass
        return {pid: enrich_plant(pid, pdata) for pid, pdata in catalog.items()}

    def _category_filters_from_catalog(catalog: dict[str, dict]) -> list[str]:
        category_set = {str(item.get("category", "Other")) for item in catalog.values()}
        rank_map = {name: idx for idx, name in enumerate(category_display_order)}
        return sorted(category_set, key=lambda name: (rank_map.get(name, len(rank_map) + 1), name.lower()))

    def _status_timeline(status: str) -> tuple[list[dict], str | None]:
        key = _lower(status)
        steps = [
            ("address_confirmed", "Address Confirmed"),
            ("confirmed", "Order Confirmed"),
            ("packed", "Packed"),
            ("shipped", "Shipped"),
            ("out_for_delivery", "Out For Delivery"),
            ("delivered", "Delivered"),
        ]
        order = [item[0] for item in steps]
        exceptional = {
            "cancelled": "Cancelled",
            "return_requested": "Return Requested",
            "returned": "Returned",
            "refunded": "Refunded",
        }
        exceptional_status = exceptional.get(key)
        active_index = order.index(key) if key in order else min(1, len(order) - 1)

        timeline = []
        for idx, (_, label) in enumerate(steps):
            timeline.append(
                {
                    "label": label,
                    "done": idx < active_index,
                    "active": idx == active_index,
                }
            )
        if key == "delivered":
            for step in timeline:
                step["done"] = True
                step["active"] = False
        return timeline, exceptional_status

    def _chatbot_reply(message: str, history: list[dict]) -> str:
        lower = _lower(message)
        context = " ".join(_lower(item.get("text") or item.get("message")) for item in history[-6:])
        merged = f"{context} {lower}".strip()

        if any(token in merged for token in ("refund", "return", "replace", "damaged", "broken")):
            return (
                "I can help with return/refund support. Share your order ID, reason, and a short description. "
                "You can also raise a ticket in Support Center for agent follow-up."
            )
        if any(token in merged for token in ("late", "delay", "where", "tracking", "not delivered")):
            return (
                "For delivery updates, open Order History and click Track Order. "
                "If delay is over 48 hours, raise a ticket and we will escalate to logistics."
            )
        if any(token in merged for token in ("payment", "upi", "debited", "failed", "charged")):
            return (
                "For payment issues, share transaction reference, amount, and timestamp. "
                "If debited but no confirmation, we usually reconcile within 24-48 hours."
            )
        if any(token in merged for token in ("cancel", "stop order")):
            return (
                "Cancellation depends on order stage. If not shipped, cancellation is usually immediate. "
                "Please provide your order ID."
            )
        if any(token in merged for token in ("hello", "hi", "hey")):
            return "Hello. Tell me your issue in one line with order ID for faster help."

        fallback = support_chatbot_reply(message, history if history else None)
        if fallback:
            return fallback
        return "Please share order ID and issue category (delivery/payment/return/product quality)."

    @app.context_processor
    def _inject_enhancement_defaults() -> dict[str, Any]:
        user_id = _current_user_id()
        points = 0
        if user_id:
            profile = UserProfile.query.filter_by(user_id=user_id).first()
            if profile:
                points = max(_safe_int(profile.loyalty_points), 0)
        requested = max(_safe_int(session.get("cart_loyalty_discount"), 0), 0)
        return {
            "role_labels": ROLE_LABELS,
            "return_status_labels": RETURN_STATUS_LABELS,
            "sunlight_labels": SUNLIGHT_LABELS,
            "watering_labels": WATERING_LABELS,
            "difficulty_labels": DIFFICULTY_LABELS,
            "recommended_items": [],
            "return_by_order": {},
            "canned_responses": CANNED_RESPONSES,
            "user_loyalty_points": points,
            "available_loyalty_discount": points,
            "loyalty_discount": requested,
        }

    def _showproduct_override() -> Any:
        catalog = _prepare_catalog()
        category_filters = _category_filters_from_catalog(catalog)
        user_logged_in = _current_user_id() is not None
        user_name = str(session.get("user_name", "") or "")
        recommendations = _build_recommendations(catalog, _current_user_id(), limit=8)
        return render_template(
            "showproduct.html",
            title="AVAILABLE PRODUCTS",
            plants=catalog,
            category_filters=category_filters,
            category_icons=category_icon_map,
            user_logged_in=user_logged_in,
            user_name=user_name,
            recommended_items=recommendations,
            sunlight_labels=SUNLIGHT_LABELS,
            watering_labels=WATERING_LABELS,
            difficulty_labels=DIFFICULTY_LABELS,
        )

    def _plant_detail_override(plant_id: str) -> Any:
        catalog_raw = get_catalog_with_marketplace_data()
        base_plant_id, requested_variant = split_catalog_key(plant_id)
        plant_data = catalog_raw.get(base_plant_id)
        if plant_data is None:
            flash("Plant not found.", "warning")
            return redirect(url_for("showproduct"))

        if callable(apply_review_stats_to_catalog):
            try:
                apply_review_stats_to_catalog(catalog_raw)
            except Exception:
                pass

        plant = enrich_plant(base_plant_id, catalog_raw.get(base_plant_id, plant_data))
        selected_variant_code = _normalize_variant(request.args.get("variant")) or requested_variant
        variants = build_variant_options(base_plant_id, plant)
        if variants:
            plant["variants"] = variants
        selected_variant = resolve_variant_option(plant, selected_variant_code)
        if not selected_variant and plant.get("variants"):
            selected_variant = plant["variants"][0]
        if not selected_variant:
            selected_variant = {
                "code": "",
                "label": "Default",
                "price_value": _safe_int(plant.get("price_value") or parse_price(plant.get("price"))),
                "mrp_value": _safe_int(
                    plant.get("mrp_value") or plant.get("price_value") or parse_price(plant.get("price"))
                ),
                "discount_percent": _safe_int(plant.get("discount_percent"), 0),
                "stock": _safe_int(plant.get("stock"), 0),
                "in_stock": bool(plant.get("in_stock", True)),
            }

        recommended_plants = []
        for pid, pdata in catalog_raw.items():
            if pid == base_plant_id:
                continue
            if str(pdata.get("category")) == str(plant.get("category")):
                recommended_plants.append(enrich_plant(pid, pdata))
        recommended_plants = sorted(
            recommended_plants,
            key=lambda item: (float(item.get("rating", 0)), int(item.get("rating_count", 0))),
            reverse=True,
        )[:4]

        review_query = ProductReview.query.filter_by(plant_id=base_plant_id)
        if hasattr(ProductReview, "user"):
            review_query = review_query.options(selectinload(ProductReview.user))
        if hasattr(ProductReview, "updated_at"):
            review_query = review_query.order_by(ProductReview.updated_at.desc(), ProductReview.id.desc())
        else:
            review_query = review_query.order_by(ProductReview.id.desc())
        all_reviews = review_query.all()

        review_status = _review_status_map([review.id for review in all_reviews])
        current_user_id = _current_user_id()
        current_user_review = None
        approved_reviews = []
        for review in all_reviews:
            status = review_status.get(review.id, "approved")
            if current_user_id is not None and review.user_id == current_user_id:
                current_user_review = review
            if status == "approved":
                approved_reviews.append(review)

        verified_purchase = False
        if current_user_id is not None:
            verified_purchase = _verified_purchase(current_user_id, base_plant_id)

        return render_template(
            "plant_detail.html",
            title="DETAILS",
            plant=plant,
            plant_key=base_plant_id,
            selected_variant=selected_variant,
            recommended_plants=recommended_plants,
            user_logged_in=current_user_id is not None,
            reviews=approved_reviews,
            review_count=len(approved_reviews),
            verified_purchase=verified_purchase,
            current_user_review=current_user_review,
        )

    def _cart_override() -> Any:
        user_id = _require_user()
        if user_id is None:
            return redirect(url_for("login"))

        saved_coupon = session.get("cart_coupon")
        summary = cart_summary_for_user(user_id, saved_coupon)
        if saved_coupon and not bool((summary.get("coupon") or {}).get("applied")):
            session.pop("cart_coupon", None)
            summary = cart_summary_for_user(user_id, None)

        points, loyalty_discount = _apply_loyalty_to_summary(summary, user_id)
        coupon = summary.get("coupon", {}) or {}
        subtotal = _safe_int(summary.get("subtotal"), 0)
        coupon_discount = _safe_int(coupon.get("discount"), 0)
        available_loyalty_discount = min(points, int(max(subtotal - coupon_discount, 0) * 0.2))
        if loyalty_discount > available_loyalty_discount:
            loyalty_discount = available_loyalty_discount
            session["cart_loyalty_discount"] = loyalty_discount

        return render_template(
            "cart.html",
            title="Your Cart",
            coupon_rules=coupon_rules,
            **summary,
            user_loyalty_points=points,
            loyalty_discount=loyalty_discount,
            available_loyalty_discount=available_loyalty_discount,
        )

    def _order_history_override() -> Any:
        user_id = _require_user()
        if user_id is None:
            return redirect(url_for("login"))

        orders = (
            Order.query.filter_by(user_id=user_id)
            .order_by(Order.order_date.desc(), Order.id.desc())
            .all()
        )
        order_ids = [row.id for row in orders]
        return_rows = []
        if order_ids:
            return_rows = ReturnRequest.query.filter(ReturnRequest.order_id.in_(order_ids)).all()
        return_by_order = {row.order_id: row for row in return_rows}
        return render_template(
            "order_history.html",
            title="Order History",
            orders=orders,
            return_by_order=return_by_order,
            return_status_labels=RETURN_STATUS_LABELS,
        )

    @app.route("/cart/loyalty", methods=["POST"])
    def apply_cart_loyalty() -> Any:
        user_id = _require_user()
        if user_id is None:
            return redirect(url_for("login"))

        action = _lower(request.form.get("action")) or "apply"
        if action == "remove":
            session.pop("cart_loyalty_discount", None)
            flash("Loyalty discount removed.", "info")
            return redirect(url_for("cart"))

        points_requested = max(_safe_int(request.form.get("points"), 0), 0)
        summary = cart_summary_for_user(user_id, session.get("cart_coupon"))
        profile = _get_or_create_profile(user_id)
        available_points = max(_safe_int(profile.loyalty_points), 0)
        subtotal = _safe_int(summary.get("subtotal"), 0)
        coupon_discount = _safe_int((summary.get("coupon") or {}).get("discount"), 0)
        max_allowed = min(available_points, int(max(subtotal - coupon_discount, 0) * 0.2))
        applied = min(points_requested, max_allowed)
        session["cart_loyalty_discount"] = applied
        if applied <= 0:
            flash("No loyalty points applied for this cart.", "warning")
        else:
            flash(f"Loyalty discount applied: {applied}", "success")
        return redirect(url_for("cart"))

    @app.route("/product/<plant_id>/review", methods=["POST"])
    def submit_product_review(plant_id: str) -> Any:
        user_id = _require_user()
        if user_id is None:
            return redirect(url_for("login"))

        base_plant_id, _ = split_catalog_key(plant_id)
        if not _verified_purchase(user_id, base_plant_id):
            flash("Only verified buyers can review this product.", "warning")
            return redirect(url_for("plant_detail", plant_id=base_plant_id))

        rating = _safe_int(request.form.get("rating"), 0)
        title = str(request.form.get("title") or "").strip()[:120]
        comment = str(request.form.get("comment") or "").strip()
        if rating < 1 or rating > 5 or not comment:
            flash("Provide rating (1-5) and review comment.", "warning")
            return redirect(url_for("plant_detail", plant_id=base_plant_id))

        review = ProductReview.query.filter_by(user_id=user_id, plant_id=base_plant_id).first()
        now = datetime.utcnow()
        if review is None:
            review = ProductReview(
                user_id=user_id,
                plant_id=base_plant_id,
                rating=rating,
                title=title,
                comment=comment,
                created_at=now,
                updated_at=now,
            )
            db.session.add(review)
            db.session.flush()
        else:
            review.rating = rating
            review.title = title
            review.comment = comment
            if hasattr(review, "updated_at"):
                review.updated_at = now

        moderation = ReviewModeration.query.filter_by(review_id=review.id).first()
        if moderation is None:
            moderation = ReviewModeration(review_id=review.id, status="pending")
            db.session.add(moderation)
        else:
            moderation.status = "pending"
            moderation.moderated_by = None
            moderation.moderated_at = None

        db.session.commit()
        flash("Review submitted and sent for moderation.", "success")
        return redirect(url_for("plant_detail", plant_id=base_plant_id))

    @app.route("/product/<plant_id>/stock-alert", methods=["POST"])
    def subscribe_stock_alert(plant_id: str) -> Any:
        user_id = _require_user()
        if user_id is None:
            return redirect(url_for("login"))

        base_plant_id, route_variant = split_catalog_key(plant_id)
        variant = _normalize_variant(request.form.get("variant")) or _normalize_variant(request.args.get("variant")) or route_variant

        catalog = get_catalog_with_marketplace_data()
        plant = catalog.get(base_plant_id)
        if not plant:
            flash("Product not found.", "warning")
            return redirect(url_for("showproduct"))

        enriched = enrich_plant(base_plant_id, plant)
        selected_variant = resolve_variant_option(enriched, variant)
        if selected_variant and selected_variant.get("in_stock"):
            flash("This variant is already in stock.", "info")
            return redirect(url_for("plant_detail", plant_id=base_plant_id, variant=selected_variant.get("code")))

        existing = StockAlertSubscription.query.filter_by(
            user_id=user_id,
            plant_id=base_plant_id,
            variant_code=variant or None,
        ).first()
        if existing is None:
            existing = StockAlertSubscription(
                user_id=user_id,
                plant_id=base_plant_id,
                variant_code=variant or None,
                status="pending",
            )
            db.session.add(existing)
        else:
            existing.status = "pending"
            existing.created_at = datetime.utcnow()

        db.session.commit()
        flash("Stock alert enabled. We will notify you when available.", "success")
        return redirect(url_for("plant_detail", plant_id=base_plant_id, variant=variant or None))

    @app.route("/order/<int:order_id>/track")
    def track_order(order_id: int) -> Any:
        user_id = _require_user()
        if user_id is None:
            return redirect(url_for("login"))

        order = Order.query.filter_by(id=order_id, user_id=user_id).first()
        if order is None:
            flash("Order not found.", "warning")
            return redirect(url_for("order_history"))

        timeline, exceptional_status = _status_timeline(str(order.order_status or "confirmed"))
        return render_template(
            "order_track.html",
            title=f"Track Order #{order.id}",
            order=order,
            timeline=timeline,
            exceptional_status=exceptional_status,
        )

    @app.route("/order/<int:order_id>/return", methods=["POST"])
    def request_return(order_id: int) -> Any:
        user_id = _require_user()
        if user_id is None:
            return redirect(url_for("login"))

        order = Order.query.filter_by(id=order_id, user_id=user_id).first()
        if order is None:
            flash("Order not found.", "warning")
            return redirect(url_for("order_history"))

        reason = str(request.form.get("reason") or "").strip()
        details = str(request.form.get("details") or "").strip()
        if not reason:
            flash("Please provide a reason for return.", "warning")
            return redirect(url_for("order_history"))

        req = ReturnRequest.query.filter_by(order_id=order_id, user_id=user_id).first()
        if req is None:
            req = ReturnRequest(
                order_id=order_id,
                user_id=user_id,
                reason=reason,
                details=details,
                status="requested",
            )
            db.session.add(req)
        else:
            req.reason = reason
            req.details = details
            req.status = "requested"
            req.updated_at = datetime.utcnow()

        if _lower(order.order_status) not in {"cancelled", "returned", "refunded"}:
            order.order_status = "return_requested"

        db.session.commit()
        flash("Return request submitted.", "success")
        return redirect(url_for("order_history"))

    @app.route("/admin/reviews")
    @admin_required
    def admin_reviews() -> Any:
        status_filter = _lower(request.args.get("status") or "pending")
        search_query = str(request.args.get("search") or "").strip().lower()

        query = ProductReview.query
        if hasattr(ProductReview, "user"):
            query = query.options(selectinload(ProductReview.user))
        if hasattr(ProductReview, "updated_at"):
            query = query.order_by(ProductReview.updated_at.desc(), ProductReview.id.desc())
        else:
            query = query.order_by(ProductReview.id.desc())

        rows = query.all()
        status_map = _review_status_map([row.id for row in rows])
        filtered = []
        for row in rows:
            status = status_map.get(row.id, "approved")
            if status_filter in {"pending", "approved"} and status != status_filter:
                continue
            if search_query:
                hay = " ".join(
                    [
                        str(row.plant_id or ""),
                        str(row.title or ""),
                        str(row.comment or ""),
                        str(getattr(getattr(row, "user", None), "name", "") or ""),
                        str(getattr(getattr(row, "user", None), "email", "") or ""),
                    ]
                ).lower()
                if search_query not in hay:
                    continue
            row.review_status = status
            filtered.append(row)

        return render_template(
            "admin_reviews.html",
            title="Review Moderation",
            reviews=filtered,
            status_filter=status_filter,
            search_query=search_query,
        )

    @app.route("/admin/reviews/<int:review_id>/status", methods=["POST"])
    @admin_required
    def admin_update_review_status(review_id: int) -> Any:
        action = _lower(request.form.get("action"))
        search_query = str(request.form.get("search_query") or "").strip()
        status_filter = str(request.form.get("status_filter") or "pending").strip()

        review = ProductReview.query.get(review_id)
        if review is None:
            flash("Review not found.", "warning")
            return redirect(url_for("admin_reviews", status=status_filter, search=search_query))

        moderation = ReviewModeration.query.filter_by(review_id=review_id).first()
        if moderation is None:
            moderation = ReviewModeration(review_id=review_id)
            db.session.add(moderation)

        if action == "approve":
            moderation.status = "approved"
            flash("Review approved.", "success")
        elif action == "reject":
            moderation.status = "rejected"
            flash("Review rejected.", "info")
        else:
            flash("Unknown action.", "warning")
            return redirect(url_for("admin_reviews", status=status_filter, search=search_query))

        moderation.moderated_by = str(session.get("admin_email") or session.get("admin_name") or "admin")
        moderation.moderated_at = datetime.utcnow()
        db.session.commit()
        return redirect(url_for("admin_reviews", status=status_filter, search=search_query))

    @app.route("/admin/returns")
    @admin_required
    def admin_returns() -> Any:
        status_filter = _lower(request.args.get("status") or "all")
        query = ReturnRequest.query.options(selectinload(ReturnRequest.order), selectinload(ReturnRequest.user))
        if status_filter in RETURN_STATUS_LABELS:
            query = query.filter(ReturnRequest.status == status_filter)
        requests_list = query.order_by(ReturnRequest.updated_at.desc(), ReturnRequest.id.desc()).all()
        return render_template(
            "admin_returns.html",
            title="Return Requests",
            requests_list=requests_list,
            status_filter=status_filter,
            status_labels=RETURN_STATUS_LABELS,
        )

    @app.route("/admin/returns/<int:return_id>", methods=["POST"])
    @admin_required
    def admin_update_return(return_id: int) -> Any:
        req = ReturnRequest.query.get(return_id)
        status_filter = str(request.form.get("status_filter") or "all").strip()
        if req is None:
            flash("Return request not found.", "warning")
            return redirect(url_for("admin_returns", status=status_filter))

        new_status = _lower(request.form.get("status"))
        if new_status not in RETURN_STATUS_LABELS:
            flash("Invalid return status.", "warning")
            return redirect(url_for("admin_returns", status=status_filter))

        req.status = new_status
        req.admin_note = str(request.form.get("admin_note") or "").strip()
        req.updated_at = datetime.utcnow()

        if req.order is not None:
            if new_status in {"approved", "pickup_scheduled", "received"}:
                req.order.order_status = "return_requested"
            elif new_status in {"refunded", "rejected", "cancelled"}:
                req.order.order_status = new_status

        db.session.commit()
        flash("Return request updated.", "success")
        return redirect(url_for("admin_returns", status=status_filter))

    @app.route("/admin/users/<int:user_id>/role", methods=["POST"])
    @admin_required
    def admin_update_user_role(user_id: int) -> Any:
        role_filter = str(request.form.get("role_filter") or "all").strip()
        search_query = str(request.form.get("search_query") or "").strip()
        new_role = _lower(request.form.get("role"))
        if new_role not in ROLE_LABELS:
            flash("Invalid role.", "warning")
            return redirect(url_for("admin_users", role=role_filter, search=search_query))

        user = Store.query.get(user_id)
        if user is None:
            flash("User not found.", "warning")
            return redirect(url_for("admin_users", role=role_filter, search=search_query))

        profile = _get_or_create_profile(user_id)
        profile.role = new_role
        db.session.commit()
        flash(f"Updated role for {user.email} to {ROLE_LABELS[new_role]}.", "success")
        return redirect(url_for("admin_users", role=role_filter, search=search_query))

    @admin_required
    def _admin_users_override() -> Any:
        search = str(request.args.get("search") or "").strip().lower()
        role_filter = _lower(request.args.get("role") or "all")

        users = Store.query.order_by(Store.created_at.desc(), Store.id.desc()).all()

        stats_rows = (
            db.session.query(
                Order.user_id,
                func.count(Order.id).label("order_count"),
                func.coalesce(func.sum(Order.grand_total), 0).label("spend_total"),
            )
            .group_by(Order.user_id)
            .all()
        )
        order_stats = {
            _safe_int(row[0]): {
                "order_count": _safe_int(row[1]),
                "spend_total": _safe_int(row[2]),
            }
            for row in stats_rows
        }

        profile_rows = UserProfile.query.filter(UserProfile.user_id.in_([user.id for user in users])).all() if users else []
        profile_map = {row.user_id: row for row in profile_rows}

        filtered_users = []
        for user in users:
            profile = profile_map.get(user.id)
            if profile is None:
                profile = _get_or_create_profile(user.id)
                profile_map[user.id] = profile

            effective_role = "admin" if _is_admin_email(user.email) else _lower(profile.role or "customer")
            user.role = effective_role
            user.loyalty_points = _safe_int(profile.loyalty_points, 0)
            user.referral_code = profile.referral_code

            if search:
                hay = " ".join(
                    [
                        str(user.id),
                        str(user.name or ""),
                        str(user.email or ""),
                        str(user.phone_number or ""),
                    ]
                ).lower()
                if search not in hay:
                    continue
            if role_filter in ROLE_LABELS and effective_role != role_filter:
                continue
            filtered_users.append(user)

        db.session.flush()

        return render_template(
            "admin_users.html",
            title="Admin User Management",
            users=filtered_users,
            order_stats=order_stats,
            search_query=search,
            role_filter=role_filter,
            role_labels=ROLE_LABELS,
        )

    @admin_required
    def _admin_dashboard_override() -> Any:
        total_users = Store.query.count()
        total_orders = Order.query.count()
        total_revenue = _safe_int(db.session.query(func.coalesce(func.sum(Order.grand_total), 0)).scalar())
        paid_revenue = _safe_int(
            db.session.query(func.coalesce(func.sum(Order.grand_total), 0))
            .filter(Order.payment_status == "paid")
            .scalar()
        )
        pending_orders = _safe_int(
            Order.query.filter(~Order.order_status.in_(["delivered", "cancelled", "returned", "refunded"])).count()
        )
        open_tickets = _safe_int(
            SupportTicket.query.filter(~SupportTicket.status.in_(["resolved", "closed"])).count()
        )

        catalog = get_catalog_with_marketplace_data()
        active_products = sum(1 for item in catalog.values() if bool(item.get("active", True)))
        inactive_products = max(len(catalog) - active_products, 0)
        low_stock_products = sum(
            1 for item in catalog.values() if bool(item.get("active", True)) and _safe_int(item.get("stock"), 0) <= 5
        )
        out_of_stock_products = sum(
            1 for item in catalog.values() if bool(item.get("active", True)) and _safe_int(item.get("stock"), 0) <= 0
        )
        stock_alert_subscriptions = _safe_int(
            StockAlertSubscription.query.filter(StockAlertSubscription.status == "pending").count()
        )

        category_counts: defaultdict[str, int] = defaultdict(int)
        for item in catalog.values():
            category_counts[str(item.get("category", "Other"))] += 1
        top_categories = sorted(category_counts.items(), key=lambda pair: pair[1], reverse=True)[:8]

        recent_orders = (
            Order.query.order_by(Order.order_date.desc(), Order.id.desc())
            .limit(10)
            .all()
        )
        top_selling_rows = (
            db.session.query(
                Order.plant_id,
                func.coalesce(func.sum(Order.quantity), 0).label("units"),
                func.coalesce(func.sum(Order.grand_total), 0).label("revenue"),
            )
            .group_by(Order.plant_id)
            .order_by(func.sum(Order.quantity).desc())
            .limit(8)
            .all()
        )
        top_selling = []
        for plant_id, units, revenue in top_selling_rows:
            base_id, _ = split_catalog_key(plant_id)
            info = catalog.get(base_id) or seed_plants.get(base_id) or {}
            top_selling.append(
                {
                    "plant_id": base_id,
                    "name": str(info.get("name") or base_id),
                    "units": _safe_int(units, 0),
                    "revenue": _safe_int(revenue, 0),
                }
            )

        return render_template(
            "admin_dashboard.html",
            title="Admin Dashboard",
            total_users=total_users,
            total_orders=total_orders,
            total_revenue=total_revenue,
            paid_revenue=paid_revenue,
            pending_orders=pending_orders,
            open_tickets=open_tickets,
            active_products=active_products,
            inactive_products=inactive_products,
            low_stock_products=low_stock_products,
            out_of_stock_products=out_of_stock_products,
            stock_alert_subscriptions=stock_alert_subscriptions,
            top_categories=top_categories,
            recent_orders=recent_orders,
            top_selling=top_selling,
        )

    @admin_required
    def _admin_support_override() -> Any:
        status_filter = _lower(request.args.get("status") or "all")
        priority_filter = _lower(request.args.get("priority") or "all")

        query = SupportTicket.query.options(
            selectinload(SupportTicket.messages),
            selectinload(SupportTicket.user),
        )
        if status_filter in support_status_labels:
            query = query.filter(SupportTicket.status == status_filter)
        if priority_filter in support_priority_labels:
            query = query.filter(SupportTicket.priority == priority_filter)
        tickets = query.order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc()).all()
        for ticket in tickets:
            _ensure_ticket_runtime_properties(ticket)

        return render_template(
            "admin_support.html",
            title="Admin Support",
            tickets=tickets,
            message_form=SupportTicketMessageForm(prefix="agent"),
            category_labels=support_category_labels,
            priority_labels=support_priority_labels,
            status_labels=support_status_labels,
            status_filter=status_filter,
            priority_filter=priority_filter,
            canned_responses=CANNED_RESPONSES,
        )

    def _support_chatbot_override() -> Any:
        payload = request.get_json(silent=True) or {}
        message = str(payload.get("message") or "").strip()
        history = payload.get("history") if isinstance(payload.get("history"), list) else []
        if not message:
            return jsonify({"reply": "Please type your message so I can help."}), 400
        reply = _chatbot_reply(message, history)
        return jsonify({"reply": reply})

    app.view_functions["showproduct"] = _showproduct_override
    app.view_functions["plant_detail"] = _plant_detail_override
    app.view_functions["cart"] = _cart_override
    app.view_functions["order_history"] = _order_history_override
    app.view_functions["admin_users"] = _admin_users_override
    app.view_functions["admin_dashboard"] = _admin_dashboard_override
    app.view_functions["admin_support"] = _admin_support_override
    app.view_functions["support_chatbot"] = _support_chatbot_override

    _ensure_order_runtime_properties()

    with app.app_context():
        db.create_all()

    app.config["ECO_BASKET_EXTENSIONS_READY"] = True
