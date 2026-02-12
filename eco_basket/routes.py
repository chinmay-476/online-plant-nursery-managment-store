from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from forms import AddressForm, CheckoutForm, Feedbackform, LoginForm, SignupForm, SupportTicketForm, SupportTicketMessageForm

from .auth import admin_required, clear_admin_session, clear_user_session, login_required
from .catalog import (
    CATEGORY_DISPLAY_ORDER,
    CATEGORY_ICON_MAP,
    COUPON_RULES,
    DIFFICULTY_LABELS,
    SUNLIGHT_LABELS,
    WATERING_LABELS,
    apply_review_stats_to_catalog,
    build_catalog_plant_key,
    build_variant_options,
    cart_summary_for_user,
    enrich_plant,
    evaluate_coupon,
    get_catalog_with_marketplace_data,
    get_delivery_fee,
    normalize_coupon_code,
    normalize_variant_code,
    normalize_wishlist_ids,
    parse_price,
    resolve_variant_option,
    split_catalog_plant_key,
    support_chatbot_reply,
    wishlist_ids_for_user,
)
from .database import db
from .models import (
    CartItem,
    CatalogOverride,
    Order,
    ProductReview,
    ReturnRequest,
    ReviewModeration,
    StockAlertSubscription,
    Store,
    SupportMessage,
    SupportTicket,
    UserProfile,
    WishlistItem,
)


ROLE_LABELS = {
    "customer": "Customer",
    "support": "Support Agent",
    "manager": "Manager",
    "admin": "Administrator",
}

SUPPORT_CATEGORY_LABELS = {
    "order": "Order Issue",
    "payment": "Payment Issue",
    "delivery": "Delivery Delay",
    "return_refund": "Return / Refund",
    "product_quality": "Product Quality",
    "other": "Other",
}

SUPPORT_PRIORITY_LABELS = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "urgent": "Urgent",
}

SUPPORT_STATUS_LABELS = {
    "open": "Open",
    "awaiting_agent": "Awaiting Agent",
    "in_progress": "In Progress",
    "resolved": "Resolved",
    "closed": "Closed",
}

ORDER_STATUS_OPTIONS = [
    "address_confirmed",
    "confirmed",
    "packed",
    "shipped",
    "out_for_delivery",
    "delivered",
    "return_requested",
    "returned",
    "cancelled",
    "refunded",
]

ORDER_STATUS_LABELS = {key: key.replace("_", " ").title() for key in ORDER_STATUS_OPTIONS}
PAYMENT_STATUS_OPTIONS = ["pending", "paid", "failed", "refunded"]
PAYMENT_STATUS_LABELS = {key: key.replace("_", " ").title() for key in PAYMENT_STATUS_OPTIONS}

RETURN_STATUS_LABELS = {
    "requested": "Requested",
    "approved": "Approved",
    "pickup_scheduled": "Pickup Scheduled",
    "received": "Received",
    "refunded": "Refunded",
    "rejected": "Rejected",
    "cancelled": "Cancelled",
}

CANNED_RESPONSES = [
    "Thanks for contacting us. I am checking this and will update you shortly.",
    "I have escalated your issue to the logistics team. You will receive an update within 24 hours.",
    "Please share order ID and product photo so we can process replacement quickly.",
    "Refund is initiated after return pickup and quality check, usually in 2 business days.",
    "If payment is debited but order is not confirmed, share transaction reference and timestamp.",
]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _current_user_id() -> int | None:
    return _safe_int(session.get("user_id"), 0) or None


def _admin_emails(app: Any) -> set[str]:
    raw = str(app.config.get("ADMIN_EMAILS", "") or "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _is_admin_email(email: str | None, app: Any) -> bool:
    return str(email or "").strip().lower() in _admin_emails(app)


def _get_or_create_profile(user_id: int) -> UserProfile:
    profile = UserProfile.query.filter_by(user_id=user_id).first()
    if profile is None:
        profile = UserProfile(user_id=user_id, role="customer", loyalty_points=0)
        db.session.add(profile)
        db.session.flush()
    return profile


def _ensure_order_runtime_attrs(order: Order) -> None:
    base_plant_id, variant_code = split_catalog_plant_key(order.plant_id)
    order.base_plant_id = base_plant_id
    order.variant_code = variant_code
    order.tracking_code = f"TRK{order.id:07d}"
    order.estimated_delivery_date = order.order_date + timedelta(days=4) if order.order_date else None


def _recommended_items(catalog: dict[str, dict], user_id: int | None, limit: int = 8) -> list[dict]:
    items = [enrich_plant(pid, pdata) for pid, pdata in catalog.items()]
    if not items:
        return []

    preferred_categories: dict[str, int] = {}
    if user_id:
        for row in Order.query.filter_by(user_id=user_id).order_by(Order.id.desc()).limit(40).all():
            base_id, _ = split_catalog_plant_key(row.plant_id)
            plant = catalog.get(base_id)
            if plant:
                category = str(plant.get("category", "Other"))
                preferred_categories[category] = preferred_categories.get(category, 0) + 2
        for base_id in wishlist_ids_for_user(user_id):
            plant = catalog.get(base_id)
            if plant:
                category = str(plant.get("category", "Other"))
                preferred_categories[category] = preferred_categories.get(category, 0) + 1

    def score(item: dict) -> tuple:
        category = str(item.get("category", "Other"))
        return (
            int(item.get("in_stock", True)),
            preferred_categories.get(category, 0),
            float(item.get("rating", 0)),
            int(item.get("rating_count", 0)),
            int(item.get("bestseller", False)),
        )

    return sorted(items, key=score, reverse=True)[:limit]


def _is_verified_purchase(user_id: int, base_plant_id: str) -> bool:
    rows = Order.query.filter_by(user_id=user_id).all()
    for row in rows:
        plant_id, _ = split_catalog_plant_key(row.plant_id)
        if plant_id == base_plant_id:
            return True
    return False


def _review_status_map(review_ids: list[int]) -> dict[int, str]:
    if not review_ids:
        return {}
    rows = ReviewModeration.query.filter(ReviewModeration.review_id.in_(review_ids)).all()
    status_map = {row.review_id: str(row.status or "pending").lower() for row in rows}
    for review_id in review_ids:
        status_map.setdefault(review_id, "approved")
    return status_map


def _next_ticket_reference() -> str:
    token = secrets.token_hex(2).upper()
    return f"TKT-{datetime.utcnow():%y%m%d}-{token}"


def _route_inventory(app: Any) -> list[dict[str, str]]:
    route_details: list[dict[str, str]] = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        methods = sorted([method for method in rule.methods if method not in {"HEAD", "OPTIONS"}])
        route_details.append(
            {
                "path": str(rule.rule),
                "methods": ", ".join(methods),
                "endpoint": str(rule.endpoint),
            }
        )
    route_details.sort(key=lambda row: (row["path"], row["endpoint"]))
    return route_details


def _masked_database_url(raw_url: str) -> str:
    raw = str(raw_url or "").strip()
    if not raw:
        return ""
    try:
        from sqlalchemy.engine.url import make_url
    except Exception:
        return raw
    try:
        parsed = make_url(raw)
        if parsed.password:
            parsed = parsed.set(password="***")
        return str(parsed)
    except Exception:
        return raw


def _with_loyalty(summary: dict, user_id: int) -> tuple[int, int, int]:
    profile = _get_or_create_profile(user_id)
    available_points = max(_safe_int(profile.loyalty_points), 0)
    coupon = summary.get("coupon", {}) or {}
    subtotal = _safe_int(summary.get("subtotal"), 0)
    coupon_discount = _safe_int(coupon.get("discount"), 0)
    max_now = min(available_points, int(max(subtotal - coupon_discount, 0) * 0.2))
    requested = max(_safe_int(session.get("cart_loyalty_discount"), 0), 0)
    discount = min(requested, max_now)
    summary["grand_total"] = max(_safe_int(summary.get("grand_total"), 0) - discount, 0)
    summary["total_savings"] = _safe_int(summary.get("total_savings"), 0) + discount
    return available_points, max_now, discount


def _order_timeline(order_status: str) -> tuple[list[dict], str | None]:
    steps = [
        ("address_confirmed", "Address Confirmed"),
        ("confirmed", "Order Confirmed"),
        ("packed", "Packed"),
        ("shipped", "Shipped"),
        ("out_for_delivery", "Out For Delivery"),
        ("delivered", "Delivered"),
    ]
    key = str(order_status or "").lower()
    order_keys = [value for value, _ in steps]
    current_idx = order_keys.index(key) if key in order_keys else 1
    timeline = []
    for idx, (_, label) in enumerate(steps):
        timeline.append({"label": label, "done": idx < current_idx, "active": idx == current_idx})
    if key == "delivered":
        for row in timeline:
            row["done"] = True
            row["active"] = False
    exceptional = {
        "cancelled": "Cancelled",
        "return_requested": "Return Requested",
        "returned": "Returned",
        "refunded": "Refunded",
    }.get(key)
    return timeline, exceptional


def register_routes(app: Any) -> None:
    if app.config.get("ROUTES_REGISTERED"):
        return

    admin_guard = admin_required(_admin_emails(app))

    @app.template_filter("inr")
    def inr(value: Any) -> str:
        amount = _safe_int(value, 0)
        return f"₹{amount:,}"

    @app.context_processor
    def inject_shared_context() -> dict[str, Any]:
        user_id = _current_user_id()
        points = 0
        if user_id:
            profile = UserProfile.query.filter_by(user_id=user_id).first()
            if profile:
                points = max(_safe_int(profile.loyalty_points), 0)
        is_admin_user = bool(session.get("admin_id")) and _is_admin_email(str(session.get("admin_email") or ""), app)
        return {
            "role_labels": ROLE_LABELS,
            "sunlight_labels": SUNLIGHT_LABELS,
            "watering_labels": WATERING_LABELS,
            "difficulty_labels": DIFFICULTY_LABELS,
            "return_status_labels": RETURN_STATUS_LABELS,
            "canned_responses": CANNED_RESPONSES,
            "user_loyalty_points": points,
            "available_loyalty_discount": points,
            "loyalty_discount": max(_safe_int(session.get("cart_loyalty_discount"), 0), 0),
            "recommended_items": [],
            "return_by_order": {},
            "is_admin_user": is_admin_user,
        }

    @app.route("/")
    def home() -> Any:
        return render_template("home.html", title="Home")

    @app.route("/shopnow")
    def shopnow() -> Any:
        return redirect(url_for("showproduct"))

    @app.route("/knowmore")
    def knowmore() -> Any:
        return render_template("about.html", title="About")

    @app.route("/help")
    def help() -> Any:
        return render_template("help.html", title="Help")

    @app.route("/faqs")
    def faqs() -> Any:
        return render_template("faqs.html", title="FAQs")

    @app.route("/contact")
    def contact() -> Any:
        return render_template("contact.html", title="Contact")

    @app.route("/feedback", methods=["GET", "POST"])
    def feedback() -> Any:
        form = Feedbackform()
        if form.validate_on_submit():
            flash("Thanks for your feedback.", "success")
            return redirect(url_for("feedback"))
        return render_template("feedback.html", title="Feedback", form=form)

    @app.route("/project-documentation")
    def project_documentation() -> Any:
        env_config = {
            "database_url": _masked_database_url(str(app.config.get("SQLALCHEMY_DATABASE_URI", "") or "")),
            "session_cookie_secure": bool(app.config.get("SESSION_COOKIE_SECURE", False)),
            "session_cookie_samesite": str(app.config.get("SESSION_COOKIE_SAMESITE", "Lax")),
        }
        return render_template(
            "project_documentation.html",
            title="Project Documentation",
            env_config=env_config,
            route_details=_route_inventory(app),
        )

    @app.route("/developer-documentation")
    def developer_documentation() -> Any:
        return render_template(
            "developer_documentation.html",
            title="Developer Documentation",
            database_uri=_masked_database_url(str(app.config.get("SQLALCHEMY_DATABASE_URI", "") or "")),
            route_details=_route_inventory(app),
        )

    @app.route("/database-documentation")
    def database_documentation() -> Any:
        doc_path = Path(app.root_path).resolve().parents[0] / "DATABASE_DOCUMENTATION.md"
        try:
            content = doc_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            content = "DATABASE_DOCUMENTATION.md not found."
        return render_template(
            "database_documentation.html",
            title="Database Documentation",
            markdown_content=content,
        )

    @app.route("/offersection")
    def offersection() -> Any:
        catalog = get_catalog_with_marketplace_data()
        apply_review_stats_to_catalog(catalog)
        offer_items = {pid: enrich_plant(pid, pdata) for pid, pdata in catalog.items() if pdata.get("offer")}
        return render_template("offersection.html", title="Offers", plants=offer_items)

    @app.route("/newarrivals")
    def newarrivals() -> Any:
        catalog = get_catalog_with_marketplace_data()
        apply_review_stats_to_catalog(catalog)
        new_items = {pid: enrich_plant(pid, pdata) for pid, pdata in catalog.items() if pdata.get("new")}
        return render_template("newarrivals.html", title="New Arrivals", plants=new_items)

    @app.route("/plantcaredetails")
    def plantcaredetails() -> Any:
        return render_template("plantcaredetails.html", title="Plant Care")

    @app.route("/login", methods=["GET", "POST"])
    def login() -> Any:
        form = LoginForm()
        if form.validate_on_submit():
            email = str(form.email.data or "").strip().lower()
            password = str(form.password.data or "")
            user = Store.query.filter_by(email=email).first()
            if user and user.check_password(password):
                clear_admin_session()
                session["user_id"] = user.id
                session["user_name"] = user.name
                session["user_email"] = user.email
                flash("Login successful.", "success")
                return redirect(url_for("showproduct"))
            flash("Invalid email or password.", "danger")
        return render_template("login.html", title="Login", form=form)

    @app.route("/signup", methods=["GET", "POST"])
    def signup() -> Any:
        form = SignupForm()
        if form.validate_on_submit():
            email = str(form.email.data or "").strip().lower()
            existing = Store.query.filter_by(email=email).first()
            if existing:
                flash("Email already registered.", "warning")
                return redirect(url_for("signup"))
            user = Store(
                name=str(form.username.data or "").strip(),
                email=email,
                phone_number=str(form.phone_number.data or "").strip(),
                password="",
                created_at=datetime.utcnow(),
            )
            user.set_password(str(form.password.data or ""))
            db.session.add(user)
            db.session.flush()
            profile = UserProfile(user_id=user.id, role="customer", loyalty_points=0)
            db.session.add(profile)
            db.session.commit()
            flash("Account created. Please login.", "success")
            return redirect(url_for("login"))
        return render_template("signup.html", title="Sign Up", form=form)

    @app.route("/logout")
    def logout() -> Any:
        clear_user_session()
        flash("Logged out successfully.", "info")
        return redirect(url_for("home"))

    @app.route("/showproduct")
    def showproduct() -> Any:
        catalog = get_catalog_with_marketplace_data()
        apply_review_stats_to_catalog(catalog)
        enriched = {pid: enrich_plant(pid, pdata) for pid, pdata in catalog.items()}
        category_set = {str(item.get("category", "Other")) for item in enriched.values()}
        rank_map = {name: idx for idx, name in enumerate(CATEGORY_DISPLAY_ORDER)}
        category_filters = sorted(category_set, key=lambda name: (rank_map.get(name, len(rank_map) + 1), name.lower()))
        return render_template(
            "showproduct.html",
            title="AVAILABLE PRODUCTS",
            plants=enriched,
            category_filters=category_filters,
            category_icons=CATEGORY_ICON_MAP,
            user_logged_in=_current_user_id() is not None,
            user_name=str(session.get("user_name", "") or ""),
            recommended_items=_recommended_items(catalog, _current_user_id()),
            sunlight_labels=SUNLIGHT_LABELS,
            watering_labels=WATERING_LABELS,
            difficulty_labels=DIFFICULTY_LABELS,
        )

    @app.route("/plant/<plant_id>")
    def plant_detail(plant_id: str) -> Any:
        catalog = get_catalog_with_marketplace_data()
        apply_review_stats_to_catalog(catalog)
        base_plant_id, route_variant = split_catalog_plant_key(plant_id)
        plant_data = catalog.get(base_plant_id)
        if not plant_data:
            flash("Plant not found.", "warning")
            return redirect(url_for("showproduct"))

        plant = enrich_plant(base_plant_id, plant_data)
        requested_variant = normalize_variant_code(request.args.get("variant")) or route_variant
        plant["variants"] = build_variant_options(base_plant_id, plant)
        selected_variant = resolve_variant_option(plant, requested_variant)

        recommended_plants = []
        for pid, pdata in catalog.items():
            if pid == base_plant_id:
                continue
            if str(pdata.get("category")) == str(plant.get("category")):
                recommended_plants.append(enrich_plant(pid, pdata))
        recommended_plants = sorted(
            recommended_plants,
            key=lambda item: (float(item.get("rating", 0)), int(item.get("rating_count", 0))),
            reverse=True,
        )[:4]

        review_query = ProductReview.query.filter_by(plant_id=base_plant_id).options(selectinload(ProductReview.user))
        reviews = review_query.order_by(ProductReview.updated_at.desc(), ProductReview.id.desc()).all()
        status_map = _review_status_map([row.id for row in reviews])
        approved_reviews = []
        current_user_review = None
        user_id = _current_user_id()
        for row in reviews:
            if user_id and row.user_id == user_id:
                current_user_review = row
            if status_map.get(row.id, "approved") == "approved":
                approved_reviews.append(row)

        verified_purchase = bool(user_id and _is_verified_purchase(user_id, base_plant_id))
        return render_template(
            "plant_detail.html",
            title="DETAILS",
            plant=plant,
            plant_key=base_plant_id,
            selected_variant=selected_variant,
            recommended_plants=recommended_plants,
            user_logged_in=user_id is not None,
            reviews=approved_reviews,
            review_count=len(approved_reviews),
            verified_purchase=verified_purchase,
            current_user_review=current_user_review,
        )

    @app.route("/wishlist")
    def wishlist() -> Any:
        user_id = _current_user_id()
        server_ids = wishlist_ids_for_user(user_id) if user_id else []
        return render_template(
            "wishlist.html",
            title="Wishlist",
            plants=get_catalog_with_marketplace_data(),
            user_logged_in=user_id is not None,
            server_wishlist_ids=server_ids,
        )

    @app.route("/wishlist/api")
    def wishlist_api() -> Any:
        user_id = _current_user_id()
        items = wishlist_ids_for_user(user_id) if user_id else []
        return jsonify({"items": items})

    @app.route("/wishlist/api/sync", methods=["POST"])
    def wishlist_api_sync() -> Any:
        user_id = _current_user_id()
        payload = request.get_json(silent=True) or {}
        items = normalize_wishlist_ids(payload.get("items"))
        if user_id is None:
            return jsonify({"items": items})
        WishlistItem.query.filter_by(user_id=user_id).delete()
        now = datetime.utcnow()
        for plant_id in items:
            db.session.add(WishlistItem(user_id=user_id, plant_id=plant_id, created_at=now))
        db.session.commit()
        return jsonify({"items": items})

    @app.route("/wishlist/api/clear", methods=["POST"])
    def wishlist_api_clear() -> Any:
        user_id = _current_user_id()
        if user_id is not None:
            WishlistItem.query.filter_by(user_id=user_id).delete()
            db.session.commit()
        return jsonify({"items": []})

    @app.route("/wishlist/api/<plant_id>", methods=["POST", "DELETE"])
    def wishlist_api_item(plant_id: str) -> Any:
        base_plant_id, _ = split_catalog_plant_key(plant_id)
        if base_plant_id not in get_catalog_with_marketplace_data(include_inactive=True):
            return jsonify({"items": [], "added": False, "message": "Product not found"}), 404

        user_id = _current_user_id()
        if user_id is None:
            return jsonify({"items": [], "added": False, "message": "Login required"}), 401

        row = WishlistItem.query.filter_by(user_id=user_id, plant_id=base_plant_id).first()
        if request.method == "POST":
            added = False
            if row is None:
                db.session.add(WishlistItem(user_id=user_id, plant_id=base_plant_id, created_at=datetime.utcnow()))
                db.session.commit()
                added = True
            return jsonify({"items": wishlist_ids_for_user(user_id), "added": added})

        if row is not None:
            db.session.delete(row)
            db.session.commit()
        return jsonify({"items": wishlist_ids_for_user(user_id), "removed": True})

    @app.route("/add-to-cart/<plant_id>")
    @login_required
    def add_to_cart(plant_id: str) -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))

        base_plant_id, _ = split_catalog_plant_key(plant_id)
        variant_code = normalize_variant_code(request.args.get("variant"))
        catalog = get_catalog_with_marketplace_data()
        plant_data = catalog.get(base_plant_id)
        if not plant_data:
            flash("Product not found.", "warning")
            return redirect(url_for("showproduct"))

        plant = enrich_plant(base_plant_id, plant_data)
        variant = resolve_variant_option(plant, variant_code)
        quantity = max(1, min(_safe_int(request.args.get("quantity"), 1), 10))
        item_key = build_catalog_plant_key(base_plant_id, variant.get("code"))
        existing = CartItem.query.filter_by(user_id=user_id, plant_id=item_key).first()
        if existing is None:
            row = CartItem(
                user_id=user_id,
                plant_id=item_key,
                quantity=quantity,
                unit_price=int(variant.get("price_value") or plant["price_value"]),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.session.add(row)
        else:
            existing.quantity = min(existing.quantity + quantity, 10)
            existing.unit_price = int(variant.get("price_value") or existing.unit_price)
            existing.updated_at = datetime.utcnow()
        db.session.commit()
        flash("Added to cart.", "success")
        next_url = request.args.get("next")
        if next_url:
            return redirect(next_url)
        return redirect(url_for("cart"))

    @app.route("/cart")
    @login_required
    def cart() -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))

        saved_coupon = session.get("cart_coupon")
        summary = cart_summary_for_user(user_id, saved_coupon)
        if saved_coupon and not bool((summary.get("coupon") or {}).get("applied")):
            session.pop("cart_coupon", None)
            summary = cart_summary_for_user(user_id, None)
        points, max_now, discount = _with_loyalty(summary, user_id)
        return render_template(
            "cart.html",
            title="Your Cart",
            coupon_rules=COUPON_RULES,
            user_loyalty_points=points,
            available_loyalty_discount=max_now,
            loyalty_discount=discount,
            **summary,
        )

    @app.route("/cart/coupon", methods=["POST"])
    @login_required
    def apply_cart_coupon() -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))

        action = str(request.form.get("action") or "apply").strip().lower()
        if action == "remove":
            session.pop("cart_coupon", None)
            flash("Coupon removed.", "info")
            return redirect(url_for("cart"))

        code = normalize_coupon_code(request.form.get("coupon_code"))
        summary = cart_summary_for_user(user_id, code)
        coupon = summary.get("coupon", {}) or {}
        if not summary.get("items"):
            flash("Add items to cart before applying a coupon.", "warning")
            return redirect(url_for("cart"))
        if coupon.get("applied"):
            session["cart_coupon"] = coupon.get("code")
            flash(str(coupon.get("message") or "Coupon applied."), "success")
        else:
            session.pop("cart_coupon", None)
            flash(str(coupon.get("message") or "Coupon could not be applied."), "warning")
        return redirect(url_for("cart"))

    @app.route("/cart/loyalty", methods=["POST"])
    @login_required
    def apply_cart_loyalty() -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))

        action = str(request.form.get("action") or "apply").strip().lower()
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
        max_now = min(available_points, int(max(subtotal - coupon_discount, 0) * 0.2))
        applied = min(points_requested, max_now)
        session["cart_loyalty_discount"] = applied
        if applied <= 0:
            flash("No loyalty points applied for this cart.", "warning")
        else:
            flash(f"Loyalty discount applied: ₹{applied}", "success")
        return redirect(url_for("cart"))

    @app.route("/cart/item/<int:item_id>/update", methods=["POST"])
    @login_required
    def update_cart_item(item_id: int) -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))
        row = CartItem.query.filter_by(id=item_id, user_id=user_id).first()
        if row is None:
            flash("Cart item not found.", "warning")
            return redirect(url_for("cart"))
        row.quantity = max(1, min(_safe_int(request.form.get("quantity"), row.quantity), 10))
        row.updated_at = datetime.utcnow()
        db.session.commit()
        flash("Cart updated.", "success")
        return redirect(url_for("cart"))

    @app.route("/cart/item/<int:item_id>/remove", methods=["POST"])
    @login_required
    def remove_cart_item(item_id: int) -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))
        row = CartItem.query.filter_by(id=item_id, user_id=user_id).first()
        if row is not None:
            db.session.delete(row)
            db.session.commit()
            flash("Item removed from cart.", "info")
        return redirect(url_for("cart"))

    @app.route("/cart/checkout/<int:item_id>")
    @login_required
    def checkout_cart_item(item_id: int) -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))
        item = CartItem.query.filter_by(id=item_id, user_id=user_id).first()
        if item is None:
            flash("Cart item not found.", "warning")
            return redirect(url_for("cart"))
        coupon_code = normalize_coupon_code(request.args.get("coupon") or session.get("cart_coupon"))
        return redirect(
            url_for(
                "deliveryinfo",
                plant_id=item.plant_id,
                quantity=item.quantity,
                cart_item_id=item.id,
                coupon=coupon_code if coupon_code else None,
            )
        )

    @app.route("/deliveryinfo", methods=["GET", "POST"])
    @login_required
    def deliveryinfo() -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))

        form = AddressForm()
        catalog = get_catalog_with_marketplace_data()

        if request.method == "GET":
            plant_key = request.args.get("plant_id") or str((session.get("checkout") or {}).get("plant_id") or "")
            base_plant_id, req_variant = split_catalog_plant_key(plant_key)
            variant_code = normalize_variant_code(request.args.get("variant")) or req_variant
            plant_data = catalog.get(base_plant_id)
            if not plant_data:
                flash("Select a plant before continuing to delivery.", "warning")
                return redirect(url_for("showproduct"))

            quantity = max(1, min(_safe_int(request.args.get("quantity"), 1), 10))
            cart_item_id = _safe_int(request.args.get("cart_item_id"), 0) or None
            plant = enrich_plant(base_plant_id, plant_data)
            variant = resolve_variant_option(plant, variant_code)
            unit_price = int(variant.get("price_value") or plant["price_value"])
            subtotal = unit_price * quantity
            coupon_code = normalize_coupon_code(request.args.get("coupon") or (session.get("checkout") or {}).get("coupon_code"))
            delivery_fee = get_delivery_fee(subtotal)
            coupon = evaluate_coupon(subtotal, delivery_fee, coupon_code)
            applied_coupon_code = coupon["code"] if coupon.get("applied") else None
            coupon_discount = _safe_int(coupon.get("discount"), 0)
            final_delivery_fee = _safe_int(coupon.get("delivery_fee"), delivery_fee)

            loyalty_discount = max(_safe_int(session.get("cart_loyalty_discount"), 0), 0)
            loyalty_discount = min(loyalty_discount, int(max(subtotal - coupon_discount, 0) * 0.2))
            grand_total = max(subtotal - coupon_discount - loyalty_discount, 0) + final_delivery_fee

            session["checkout"] = {
                "plant_id": build_catalog_plant_key(base_plant_id, variant.get("code")),
                "quantity": quantity,
                "subtotal": subtotal,
                "delivery_fee": final_delivery_fee,
                "coupon_code": applied_coupon_code,
                "coupon_discount": coupon_discount,
                "loyalty_discount": loyalty_discount,
                "grand_total": grand_total,
                "cart_item_id": cart_item_id,
            }

            user = Store.query.get(user_id)
            if user is not None:
                form.name.data = user.name
                form.email.data = user.email
                form.phone_number.data = user.phone_number

            return render_template(
                "deliveryinfo.html",
                title="Delivery Info",
                form=form,
                plant=plant,
                plant_id=base_plant_id,
                quantity=quantity,
                subtotal=subtotal,
                coupon=coupon,
                delivery_fee=final_delivery_fee,
                grand_total=grand_total,
            )

        checkout = session.get("checkout") or {}
        plant_key = str(checkout.get("plant_id") or "")
        base_plant_id, variant_code = split_catalog_plant_key(plant_key)
        plant_data = catalog.get(base_plant_id)
        if not checkout or not plant_data:
            flash("Your checkout session expired. Please select a plant again.", "warning")
            return redirect(url_for("showproduct"))

        if not form.validate_on_submit():
            plant = enrich_plant(base_plant_id, plant_data)
            subtotal = _safe_int(checkout.get("subtotal"), 0)
            delivery_fee = _safe_int(checkout.get("delivery_fee"), 0)
            coupon = evaluate_coupon(subtotal, delivery_fee, checkout.get("coupon_code"))
            coupon["applied"] = bool(checkout.get("coupon_code"))
            coupon["code"] = str(checkout.get("coupon_code") or "")
            coupon["discount"] = _safe_int(checkout.get("coupon_discount"), 0)
            grand_total = _safe_int(checkout.get("grand_total"), 0)
            return render_template(
                "deliveryinfo.html",
                title="Delivery Info",
                form=form,
                plant=plant,
                plant_id=base_plant_id,
                quantity=_safe_int(checkout.get("quantity"), 1),
                subtotal=subtotal,
                coupon=coupon,
                delivery_fee=delivery_fee,
                grand_total=grand_total,
            )

        plant = enrich_plant(base_plant_id, plant_data)
        variant = resolve_variant_option(plant, variant_code)
        quantity = max(1, min(_safe_int(checkout.get("quantity"), 1), 10))
        unit_price = int(variant.get("price_value") or plant["price_value"])
        subtotal = unit_price * quantity
        delivery_fee = _safe_int(checkout.get("delivery_fee"), get_delivery_fee(subtotal))
        applied_coupon_code = str(checkout.get("coupon_code") or "") or None
        coupon_discount = _safe_int(checkout.get("coupon_discount"), 0)
        loyalty_discount = _safe_int(checkout.get("loyalty_discount"), 0)
        grand_total = max(subtotal - coupon_discount - loyalty_discount, 0) + delivery_fee

        order = Order(
            user_id=user_id,
            customer_name=str(form.name.data or "").strip(),
            email=str(form.email.data or "").strip().lower(),
            phone_number=str(form.phone_number.data or "").strip(),
            address=str(form.address.data or "").strip(),
            pincode=str(form.pincode.data or "").strip(),
            address_type=str(form.homeoffice.data or "home"),
            plant_id=build_catalog_plant_key(base_plant_id, variant.get("code")),
            plant_name=str(plant["name"]),
            plant_image=str(plant["image"]),
            quantity=quantity,
            unit_price=unit_price,
            total_price=subtotal,
            delivery_fee=delivery_fee,
            coupon_code=applied_coupon_code,
            coupon_discount=coupon_discount + loyalty_discount,
            grand_total=grand_total,
            payment_status="pending",
            order_status="address_confirmed",
            order_date=datetime.utcnow(),
        )
        db.session.add(order)

        cart_item_id = checkout.get("cart_item_id")
        if cart_item_id:
            row = CartItem.query.filter_by(id=_safe_int(cart_item_id), user_id=user_id).first()
            if row is not None:
                db.session.delete(row)

        if applied_coupon_code and session.get("cart_coupon") == applied_coupon_code:
            session.pop("cart_coupon", None)
        db.session.flush()
        session["current_order_id"] = order.id
        db.session.commit()
        return redirect(url_for("payments", order_id=order.id))

    @app.route("/payments", methods=["GET", "POST"])
    @login_required
    def payments() -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))

        order_id = _safe_int(request.args.get("order_id"), 0) or _safe_int(session.get("current_order_id"), 0)
        if not order_id:
            flash("Invalid payment request.", "danger")
            return redirect(url_for("showproduct"))
        order = Order.query.get(order_id)
        if order is None or order.user_id != user_id:
            flash("Invalid payment session.", "danger")
            return redirect(url_for("showproduct"))

        form = CheckoutForm()
        if form.validate_on_submit():
            method = str(form.payment_method.data or "cod").strip().lower()
            upi_id = str(form.upi_id.data or "").strip()
            bank_name = str(form.bank_name.data or "").strip()
            payment_ref = upi_id or bank_name or f"COD-{order.id}"
            order.payment_method = method
            order.payment_reference = payment_ref[:120]
            order.order_status = "confirmed"
            db.session.commit()
            session["payment_processing"] = order.id
            return redirect(url_for("process_payment"))

        return render_template("payments.html", title="Payments", order=order, form=form)

    @app.route("/process-payment")
    @login_required
    def process_payment() -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))
        order_id = _safe_int(session.get("payment_processing"), 0)
        if not order_id:
            flash("Invalid payment request.", "danger")
            return redirect(url_for("showproduct"))
        order = Order.query.get(order_id)
        if order is None or order.user_id != user_id:
            session.pop("payment_processing", None)
            flash("Invalid payment session.", "danger")
            return redirect(url_for("showproduct"))
        return render_template("process_payment.html", title="Processing Payment", order=order)

    @app.route("/payment-success")
    @login_required
    def payment_success() -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))
        order_id = _safe_int(session.pop("payment_processing", 0), 0)
        if not order_id:
            flash("Invalid payment confirmation.", "danger")
            return redirect(url_for("showproduct"))
        order = Order.query.get(order_id)
        if order is None or order.user_id != user_id:
            flash("Order not found.", "danger")
            return redirect(url_for("showproduct"))

        order.payment_status = "paid"
        order.order_status = "confirmed"

        profile = _get_or_create_profile(user_id)
        earned = max(int(order.grand_total * 0.05), 0)
        spent = max(_safe_int((session.get("checkout") or {}).get("loyalty_discount"), 0), 0)
        profile.loyalty_points = max(profile.loyalty_points - spent, 0) + earned

        db.session.commit()
        session["last_order_id"] = order.id
        session.pop("checkout", None)
        session.pop("current_order_id", None)
        session.pop("cart_loyalty_discount", None)
        flash(f"Payment successful via {str(order.payment_method or 'cod').upper()}! Order confirmed.", "success")
        return redirect(url_for("ordersuccess", order_id=order.id))

    @app.route("/ordersuccess")
    @login_required
    def ordersuccess() -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))
        order_id = _safe_int(request.args.get("order_id"), 0) or _safe_int(session.get("last_order_id"), 0)
        if not order_id:
            flash("No completed order found.", "warning")
            return redirect(url_for("showproduct"))
        order = Order.query.get(order_id)
        if order is None or order.user_id != user_id:
            flash("Order not found.", "danger")
            return redirect(url_for("showproduct"))
        return render_template("ordersuccess.html", title="SUCCESS", order=order)

    @app.route("/ordernow")
    def ordernow() -> Any:
        flash("Please select a plant to place an order.", "warning")
        return redirect(url_for("showproduct"))

    @app.route("/order-history")
    @login_required
    def order_history() -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))
        orders = Order.query.filter_by(user_id=user_id).order_by(Order.order_date.desc(), Order.id.desc()).all()
        for row in orders:
            _ensure_order_runtime_attrs(row)
        request_rows = ReturnRequest.query.filter(ReturnRequest.order_id.in_([row.id for row in orders])).all() if orders else []
        return_by_order = {row.order_id: row for row in request_rows}
        return render_template(
            "order_history.html",
            title="Order History",
            orders=orders,
            return_by_order=return_by_order,
            return_status_labels=RETURN_STATUS_LABELS,
        )

    @app.route("/order/<int:order_id>/track")
    @login_required
    def track_order(order_id: int) -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))
        order = Order.query.filter_by(id=order_id, user_id=user_id).first()
        if order is None:
            flash("Order not found.", "warning")
            return redirect(url_for("order_history"))
        _ensure_order_runtime_attrs(order)
        timeline, exceptional_status = _order_timeline(order.order_status)
        return render_template(
            "order_track.html",
            title=f"Track Order #{order.id}",
            order=order,
            timeline=timeline,
            exceptional_status=exceptional_status,
        )

    @app.route("/order/<int:order_id>/return", methods=["POST"])
    @login_required
    def request_return(order_id: int) -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))
        order = Order.query.filter_by(id=order_id, user_id=user_id).first()
        if order is None:
            flash("Order not found.", "warning")
            return redirect(url_for("order_history"))

        reason = str(request.form.get("reason") or "").strip()
        details = str(request.form.get("details") or "").strip()
        if not reason:
            flash("Please provide return reason.", "warning")
            return redirect(url_for("order_history"))

        req = ReturnRequest.query.filter_by(order_id=order.id, user_id=user_id).first()
        if req is None:
            req = ReturnRequest(order_id=order.id, user_id=user_id, reason=reason, details=details, status="requested")
            db.session.add(req)
        else:
            req.reason = reason
            req.details = details
            req.status = "requested"
            req.updated_at = datetime.utcnow()
        order.order_status = "return_requested"
        db.session.commit()
        flash("Return request submitted.", "success")
        return redirect(url_for("order_history"))

    @app.route("/product/<plant_id>/review", methods=["POST"])
    @login_required
    def submit_product_review(plant_id: str) -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))
        base_plant_id, _ = split_catalog_plant_key(plant_id)
        if not _is_verified_purchase(user_id, base_plant_id):
            flash("Buy this product to post a verified review.", "warning")
            return redirect(url_for("plant_detail", plant_id=base_plant_id))

        rating = max(1, min(_safe_int(request.form.get("rating"), 0), 5))
        comment = str(request.form.get("comment") or "").strip()
        title = str(request.form.get("title") or "").strip()[:120]
        if not comment:
            flash("Review comment is required.", "warning")
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
    @login_required
    def subscribe_stock_alert(plant_id: str) -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))
        base_plant_id, route_variant = split_catalog_plant_key(plant_id)
        variant = normalize_variant_code(request.form.get("variant")) or normalize_variant_code(request.args.get("variant")) or route_variant
        row = StockAlertSubscription.query.filter_by(
            user_id=user_id,
            plant_id=base_plant_id,
            variant_code=variant or None,
        ).first()
        if row is None:
            row = StockAlertSubscription(user_id=user_id, plant_id=base_plant_id, variant_code=variant or None, status="pending")
            db.session.add(row)
        else:
            row.status = "pending"
            row.created_at = datetime.utcnow()
        db.session.commit()
        flash("Stock alert enabled.", "success")
        return redirect(url_for("plant_detail", plant_id=base_plant_id, variant=variant or None))

    @app.route("/support-center", methods=["GET", "POST"])
    def support_center() -> Any:
        user_id = _current_user_id()
        ticket_form = SupportTicketForm()
        message_form = SupportTicketMessageForm()

        if user_id and ticket_form.validate_on_submit():
            ticket = SupportTicket(
                user_id=user_id,
                reference_code=_next_ticket_reference(),
                subject=str(ticket_form.subject.data or "").strip(),
                category=str(ticket_form.category.data or "other"),
                priority=str(ticket_form.priority.data or "medium"),
                description=str(ticket_form.description.data or "").strip(),
                status="open",
                assigned_agent=None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.session.add(ticket)
            db.session.flush()
            db.session.add(
                SupportMessage(
                    ticket_id=ticket.id,
                    sender_role="user",
                    sender_name=str(session.get("user_name") or "Customer"),
                    message=ticket.description,
                    created_at=datetime.utcnow(),
                )
            )
            db.session.commit()
            flash(f"Ticket raised: {ticket.reference_code}", "success")
            return redirect(url_for("support_center"))

        tickets = []
        if user_id:
            tickets = (
                SupportTicket.query.filter_by(user_id=user_id)
                .options(selectinload(SupportTicket.messages), selectinload(SupportTicket.user))
                .order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc())
                .all()
            )

        return render_template(
            "support_center.html",
            title="Support Center",
            user_logged_in=user_id is not None,
            ticket_form=ticket_form,
            message_form=message_form,
            tickets=tickets,
            category_labels=SUPPORT_CATEGORY_LABELS,
            priority_labels=SUPPORT_PRIORITY_LABELS,
            status_labels=SUPPORT_STATUS_LABELS,
        )

    @app.route("/support/ticket/<int:ticket_id>/message", methods=["POST"])
    @login_required
    def add_support_ticket_message(ticket_id: int) -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))
        ticket = SupportTicket.query.filter_by(id=ticket_id, user_id=user_id).first()
        if ticket is None:
            flash("Ticket not found.", "warning")
            return redirect(url_for("support_center"))
        message = str(request.form.get("message") or "").strip()
        if not message:
            flash("Message is required.", "warning")
            return redirect(url_for("support_center"))
        db.session.add(
            SupportMessage(
                ticket_id=ticket.id,
                sender_role="user",
                sender_name=str(session.get("user_name") or "Customer"),
                message=message,
                created_at=datetime.utcnow(),
            )
        )
        if ticket.status == "closed":
            ticket.status = "open"
        ticket.updated_at = datetime.utcnow()
        db.session.commit()
        return redirect(url_for("support_center"))

    @app.route("/support/ticket/<int:ticket_id>/request-agent", methods=["POST"])
    @login_required
    def request_support_agent(ticket_id: int) -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))
        ticket = SupportTicket.query.filter_by(id=ticket_id, user_id=user_id).first()
        if ticket is None:
            flash("Ticket not found.", "warning")
            return redirect(url_for("support_center"))
        if ticket.status not in {"resolved", "closed"}:
            ticket.status = "awaiting_agent"
            ticket.updated_at = datetime.utcnow()
            db.session.commit()
            flash("Agent request submitted.", "success")
        return redirect(url_for("support_center"))

    @app.route("/support/ticket/<int:ticket_id>/close", methods=["POST"])
    @login_required
    def close_support_ticket(ticket_id: int) -> Any:
        user_id = _current_user_id()
        if user_id is None:
            return redirect(url_for("login"))
        ticket = SupportTicket.query.filter_by(id=ticket_id, user_id=user_id).first()
        if ticket is None:
            flash("Ticket not found.", "warning")
            return redirect(url_for("support_center"))
        ticket.status = "closed"
        ticket.updated_at = datetime.utcnow()
        db.session.commit()
        flash("Ticket closed.", "info")
        return redirect(url_for("support_center"))

    @app.route("/support/chatbot", methods=["POST"])
    def support_chatbot() -> Any:
        payload = request.get_json(silent=True) or {}
        message = str(payload.get("message") or "").strip()
        history = payload.get("history") if isinstance(payload.get("history"), list) else []
        if not message:
            return jsonify({"reply": "Please type your issue so I can help."}), 400
        return jsonify({"reply": support_chatbot_reply(message, history)})

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login() -> Any:
        form = LoginForm()
        if request.method == "POST":
            email = str(form.email.data or request.form.get("email") or "").strip().lower()
            password = str(form.password.data or request.form.get("password") or "")
            admin_user = Store.query.filter_by(email=email).first()
            if admin_user and admin_user.check_password(password) and _is_admin_email(admin_user.email, app):
                clear_user_session()
                session["admin_id"] = admin_user.id
                session["admin_name"] = admin_user.name
                session["admin_email"] = admin_user.email
                next_url = request.args.get("next")
                return redirect(next_url or url_for("admin_dashboard"))
            flash("Invalid admin credentials.", "danger")
        return render_template("admin_login.html", title="Admin Login", form=form)

    @app.route("/admin/logout")
    def admin_logout() -> Any:
        clear_admin_session()
        flash("Admin logged out.", "info")
        return redirect(url_for("admin_login"))

    @app.route("/admin")
    @app.route("/admin/dashboard")
    @admin_guard
    def admin_dashboard() -> Any:
        total_users = Store.query.count()
        total_orders = Order.query.count()
        total_revenue = _safe_int(db.session.query(func.coalesce(func.sum(Order.grand_total), 0)).scalar())
        paid_revenue = _safe_int(
            db.session.query(func.coalesce(func.sum(Order.grand_total), 0)).filter(Order.payment_status == "paid").scalar()
        )
        pending_orders = _safe_int(Order.query.filter(~Order.order_status.in_(["delivered", "cancelled", "returned", "refunded"])).count())
        open_tickets = _safe_int(SupportTicket.query.filter(~SupportTicket.status.in_(["resolved", "closed"])).count())

        catalog = get_catalog_with_marketplace_data()
        active_products = sum(1 for item in catalog.values() if bool(item.get("active", True)))
        inactive_products = max(len(catalog) - active_products, 0)
        low_stock_products = sum(1 for item in catalog.values() if bool(item.get("active", True)) and _safe_int(item.get("stock"), 0) <= 5)
        out_of_stock_products = sum(1 for item in catalog.values() if bool(item.get("active", True)) and _safe_int(item.get("stock"), 0) <= 0)
        stock_alert_subscriptions = _safe_int(StockAlertSubscription.query.filter_by(status="pending").count())

        category_counts: dict[str, int] = {}
        for item in catalog.values():
            category = str(item.get("category", "Other"))
            category_counts[category] = category_counts.get(category, 0) + 1
        top_categories = sorted(category_counts.items(), key=lambda pair: pair[1], reverse=True)[:8]

        recent_orders = Order.query.order_by(Order.order_date.desc(), Order.id.desc()).limit(10).all()
        top_rows = (
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
        for plant_key, units, revenue in top_rows:
            base_id, _ = split_catalog_plant_key(plant_key)
            info = catalog.get(base_id) or {}
            top_selling.append(
                {
                    "plant_id": base_id,
                    "name": str(info.get("name") or base_id),
                    "units": _safe_int(units),
                    "revenue": _safe_int(revenue),
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

    @app.route("/admin/products")
    @admin_guard
    def admin_products() -> Any:
        search_query = str(request.args.get("search") or "").strip().lower()
        selected_category = str(request.args.get("category") or "all").strip()
        active_filter = str(request.args.get("active") or "all").strip()

        catalog = get_catalog_with_marketplace_data(include_inactive=True)
        overrides = {row.plant_id: row for row in CatalogOverride.query.all()}
        items = []
        for plant_id, plant_data in catalog.items():
            item = enrich_plant(plant_id, plant_data)
            override = overrides.get(plant_id)
            item["override_price"] = override.price_override if override else None
            item["override_stock"] = override.stock_override if override else None
            item["override_offer"] = override.offer_override if override else None
            item["override_new"] = override.new_override if override else None
            item["active"] = bool(override.is_active) if override else bool(plant_data.get("active", True))

            if search_query:
                hay = f"{plant_id} {item.get('name','')} {item.get('category','')}".lower()
                if search_query not in hay:
                    continue
            if selected_category != "all" and str(item.get("category")) != selected_category:
                continue
            if active_filter == "active" and not item["active"]:
                continue
            if active_filter == "inactive" and item["active"]:
                continue
            items.append(item)

        categories = sorted({str(item.get("category", "Other")) for item in catalog.values()})
        return render_template(
            "admin_products.html",
            title="Admin Product Management",
            items=items,
            search_query=search_query,
            selected_category=selected_category,
            active_filter=active_filter,
            category_filters=categories,
            category_icons=CATEGORY_ICON_MAP,
        )

    @app.route("/admin/products/<plant_id>", methods=["POST"])
    @admin_guard
    def admin_update_product(plant_id: str) -> Any:
        override = CatalogOverride.query.get(plant_id)
        if override is None:
            override = CatalogOverride(plant_id=plant_id, is_active=True)
            db.session.add(override)

        price_raw = str(request.form.get("price_override") or "").strip()
        stock_raw = str(request.form.get("stock_override") or "").strip()
        override.price_override = _safe_int(price_raw) if price_raw else None
        override.stock_override = _safe_int(stock_raw) if stock_raw else None

        offer_override = str(request.form.get("offer_override") or "default")
        new_override = str(request.form.get("new_override") or "default")
        override.offer_override = None if offer_override == "default" else offer_override == "true"
        override.new_override = None if new_override == "default" else new_override == "true"
        override.is_active = str(request.form.get("is_active") or "true") == "true"
        override.updated_at = datetime.utcnow()
        db.session.commit()
        flash("Product updated.", "success")
        return redirect(request.form.get("next") or url_for("admin_products"))

    @app.route("/admin/orders")
    @admin_guard
    def admin_orders() -> Any:
        search_query = str(request.args.get("search") or "").strip().lower()
        status_filter = str(request.args.get("status") or "all").strip()
        payment_filter = str(request.args.get("payment") or "all").strip()

        query = Order.query
        if status_filter != "all":
            query = query.filter(Order.order_status == status_filter)
        if payment_filter != "all":
            query = query.filter(Order.payment_status == payment_filter)
        if search_query:
            like = f"%{search_query}%"
            query = query.filter(
                or_(
                    func.cast(Order.id, db.String).ilike(like),
                    Order.customer_name.ilike(like),
                    Order.email.ilike(like),
                    Order.plant_name.ilike(like),
                )
            )

        orders = query.order_by(Order.order_date.desc(), Order.id.desc()).all()
        return render_template(
            "admin_orders.html",
            title="Admin Order Management",
            orders=orders,
            search_query=search_query,
            status_filter=status_filter,
            payment_filter=payment_filter,
            order_status_options=ORDER_STATUS_OPTIONS,
            payment_status_options=PAYMENT_STATUS_OPTIONS,
            order_status_labels=ORDER_STATUS_LABELS,
            payment_status_labels=PAYMENT_STATUS_LABELS,
        )

    @app.route("/admin/orders/<int:order_id>", methods=["POST"])
    @admin_guard
    def admin_update_order(order_id: int) -> Any:
        order = Order.query.get(order_id)
        status_filter = str(request.form.get("status_filter") or "all")
        payment_filter = str(request.form.get("payment_filter") or "all")
        search_query = str(request.form.get("search_query") or "")
        if order is None:
            flash("Order not found.", "warning")
            return redirect(url_for("admin_orders", status=status_filter, payment=payment_filter, search=search_query))

        new_order_status = str(request.form.get("order_status") or order.order_status)
        new_payment_status = str(request.form.get("payment_status") or order.payment_status)
        if new_order_status in ORDER_STATUS_OPTIONS:
            order.order_status = new_order_status
        if new_payment_status in PAYMENT_STATUS_OPTIONS:
            order.payment_status = new_payment_status
        db.session.commit()
        flash("Order updated.", "success")
        return redirect(url_for("admin_orders", status=status_filter, payment=payment_filter, search=search_query))

    @app.route("/admin/users")
    @admin_guard
    def admin_users() -> Any:
        search_query = str(request.args.get("search") or "").strip().lower()
        role_filter = str(request.args.get("role") or "all").strip().lower()

        users = Store.query.order_by(Store.created_at.desc(), Store.id.desc()).all()
        profiles = UserProfile.query.filter(UserProfile.user_id.in_([row.id for row in users])).all() if users else []
        profile_map = {row.user_id: row for row in profiles}

        stats_rows = (
            db.session.query(
                Order.user_id,
                func.count(Order.id).label("order_count"),
                func.coalesce(func.sum(Order.grand_total), 0).label("spend_total"),
            )
            .group_by(Order.user_id)
            .all()
        )
        order_stats = {_safe_int(row[0]): {"order_count": _safe_int(row[1]), "spend_total": _safe_int(row[2])} for row in stats_rows}

        filtered = []
        for user in users:
            profile = profile_map.get(user.id)
            if profile is None:
                profile = _get_or_create_profile(user.id)
            user.role = "admin" if _is_admin_email(user.email, app) else str(profile.role or "customer")
            user.loyalty_points = _safe_int(profile.loyalty_points, 0)
            user.referral_code = profile.referral_code

            if search_query:
                hay = f"{user.id} {user.name} {user.email} {user.phone_number}".lower()
                if search_query not in hay:
                    continue
            if role_filter != "all" and user.role != role_filter:
                continue
            filtered.append(user)

        db.session.flush()
        return render_template(
            "admin_users.html",
            title="Admin User Management",
            users=filtered,
            order_stats=order_stats,
            search_query=search_query,
            role_filter=role_filter,
            role_labels=ROLE_LABELS,
        )

    @app.route("/admin/users/<int:user_id>/role", methods=["POST"])
    @admin_guard
    def admin_update_user_role(user_id: int) -> Any:
        role_filter = str(request.form.get("role_filter") or "all")
        search_query = str(request.form.get("search_query") or "")
        new_role = str(request.form.get("role") or "customer").lower()
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
        flash("User role updated.", "success")
        return redirect(url_for("admin_users", role=role_filter, search=search_query))

    @app.route("/admin/support")
    @admin_guard
    def admin_support() -> Any:
        status_filter = str(request.args.get("status") or "all").strip().lower()
        priority_filter = str(request.args.get("priority") or "all").strip().lower()

        query = SupportTicket.query.options(selectinload(SupportTicket.messages), selectinload(SupportTicket.user))
        if status_filter in SUPPORT_STATUS_LABELS:
            query = query.filter(SupportTicket.status == status_filter)
        if priority_filter in SUPPORT_PRIORITY_LABELS:
            query = query.filter(SupportTicket.priority == priority_filter)
        tickets = query.order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc()).all()
        for ticket in tickets:
            due_hours = {"urgent": 4, "high": 8, "medium": 24, "low": 48}.get(str(ticket.priority).lower(), 24)
            ticket.due_at = ticket.created_at + timedelta(hours=due_hours)
            ticket.escalated = str(ticket.status).lower() not in {"resolved", "closed"} and datetime.utcnow() > ticket.due_at
            ticket.escalation_level = 2 if ticket.escalated else 0

        return render_template(
            "admin_support.html",
            title="Admin Support",
            tickets=tickets,
            message_form=SupportTicketMessageForm(),
            category_labels=SUPPORT_CATEGORY_LABELS,
            priority_labels=SUPPORT_PRIORITY_LABELS,
            status_labels=SUPPORT_STATUS_LABELS,
            status_filter=status_filter,
            priority_filter=priority_filter,
            canned_responses=CANNED_RESPONSES,
        )

    @app.route("/admin/support/<int:ticket_id>/assign", methods=["POST"])
    @admin_guard
    def admin_assign_support_ticket(ticket_id: int) -> Any:
        ticket = SupportTicket.query.get(ticket_id)
        if ticket is None:
            flash("Ticket not found.", "warning")
            return redirect(url_for("admin_support"))
        ticket.assigned_agent = str(session.get("admin_name") or session.get("admin_email") or "Agent")
        if ticket.status in {"open", "awaiting_agent"}:
            ticket.status = "in_progress"
        ticket.updated_at = datetime.utcnow()
        db.session.commit()
        flash("Ticket assigned.", "success")
        return redirect(url_for("admin_support"))

    @app.route("/admin/support/<int:ticket_id>/status", methods=["POST"])
    @admin_guard
    def admin_update_support_ticket_status(ticket_id: int) -> Any:
        ticket = SupportTicket.query.get(ticket_id)
        if ticket is None:
            flash("Ticket not found.", "warning")
            return redirect(url_for("admin_support"))
        status = str(request.form.get("status") or "").strip().lower()
        if status in SUPPORT_STATUS_LABELS:
            ticket.status = status
            ticket.updated_at = datetime.utcnow()
            db.session.commit()
            flash("Ticket status updated.", "success")
        else:
            flash("Invalid status.", "warning")
        return redirect(url_for("admin_support"))

    @app.route("/admin/support/<int:ticket_id>/reply", methods=["POST"])
    @admin_guard
    def admin_reply_support_ticket(ticket_id: int) -> Any:
        ticket = SupportTicket.query.get(ticket_id)
        if ticket is None:
            flash("Ticket not found.", "warning")
            return redirect(url_for("admin_support"))
        message = str(request.form.get("message") or "").strip()
        if not message:
            flash("Reply cannot be empty.", "warning")
            return redirect(url_for("admin_support"))
        db.session.add(
            SupportMessage(
                ticket_id=ticket.id,
                sender_role="agent",
                sender_name=str(session.get("admin_name") or "Support Agent"),
                message=message,
                created_at=datetime.utcnow(),
            )
        )
        if ticket.status == "open":
            ticket.status = "in_progress"
        ticket.updated_at = datetime.utcnow()
        db.session.commit()
        return redirect(url_for("admin_support"))

    @app.route("/admin/reviews")
    @admin_guard
    def admin_reviews() -> Any:
        status_filter = str(request.args.get("status") or "pending").strip().lower()
        search_query = str(request.args.get("search") or "").strip().lower()

        rows = ProductReview.query.options(selectinload(ProductReview.user)).order_by(ProductReview.updated_at.desc(), ProductReview.id.desc()).all()
        status_map = _review_status_map([row.id for row in rows])
        reviews = []
        for row in rows:
            status = status_map.get(row.id, "approved")
            if status_filter in {"pending", "approved"} and status != status_filter:
                continue
            if search_query:
                hay = f"{row.plant_id} {row.title or ''} {row.comment or ''} {row.user.name if row.user else ''} {row.user.email if row.user else ''}".lower()
                if search_query not in hay:
                    continue
            reviews.append(row)
        return render_template(
            "admin_reviews.html",
            title="Review Moderation",
            reviews=reviews,
            status_filter=status_filter,
            search_query=search_query,
        )

    @app.route("/admin/reviews/<int:review_id>/status", methods=["POST"])
    @admin_guard
    def admin_update_review_status(review_id: int) -> Any:
        action = str(request.form.get("action") or "").strip().lower()
        status_filter = str(request.form.get("status_filter") or "pending")
        search_query = str(request.form.get("search_query") or "")

        review = ProductReview.query.get(review_id)
        if review is None:
            flash("Review not found.", "warning")
            return redirect(url_for("admin_reviews", status=status_filter, search=search_query))

        moderation = ReviewModeration.query.filter_by(review_id=review_id).first()
        if moderation is None:
            moderation = ReviewModeration(review_id=review_id, status="pending")
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
        moderation.moderated_by = str(session.get("admin_email") or "admin")
        moderation.moderated_at = datetime.utcnow()
        db.session.commit()
        return redirect(url_for("admin_reviews", status=status_filter, search=search_query))

    @app.route("/admin/returns")
    @admin_guard
    def admin_returns() -> Any:
        status_filter = str(request.args.get("status") or "all").strip().lower()
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
    @admin_guard
    def admin_update_return(return_id: int) -> Any:
        req = ReturnRequest.query.get(return_id)
        status_filter = str(request.form.get("status_filter") or "all")
        if req is None:
            flash("Return request not found.", "warning")
            return redirect(url_for("admin_returns", status=status_filter))
        new_status = str(request.form.get("status") or "").strip().lower()
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

    app.config["ROUTES_REGISTERED"] = True
