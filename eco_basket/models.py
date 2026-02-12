from __future__ import annotations

from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from .database import db


class Store(db.Model):
    __tablename__ = "store"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True, index=True)
    phone_number = db.Column(db.String(20), nullable=False)
    password = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def set_password(self, raw_password: str) -> None:
        self.password = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        if not raw_password:
            return False
        return check_password_hash(self.password, raw_password)


class CatalogOverride(db.Model):
    __tablename__ = "catalog_override"

    plant_id = db.Column(db.String(80), primary_key=True)
    price_override = db.Column(db.Integer, nullable=True)
    stock_override = db.Column(db.Integer, nullable=True)
    offer_override = db.Column(db.Boolean, nullable=True)
    new_override = db.Column(db.Boolean, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class CartItem(db.Model):
    __tablename__ = "cart_item"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("store.id"), nullable=False, index=True)
    plant_id = db.Column(db.String(80), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("Store", backref=db.backref("cart_items", lazy="dynamic", cascade="all, delete-orphan"))


class WishlistItem(db.Model):
    __tablename__ = "wishlist_item"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("store.id"), nullable=False, index=True)
    plant_id = db.Column(db.String(80), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("Store", backref=db.backref("wishlist_items", lazy="dynamic", cascade="all, delete-orphan"))
    __table_args__ = (
        db.UniqueConstraint("user_id", "plant_id", name="uq_wishlist_user_plant"),
    )


class Order(db.Model):
    __tablename__ = "order"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("store.id"), nullable=False, index=True)
    customer_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    address = db.Column(db.String(255), nullable=False)
    pincode = db.Column(db.String(10), nullable=False)
    address_type = db.Column(db.String(20), nullable=False)
    plant_id = db.Column(db.String(80), nullable=False, index=True)
    plant_name = db.Column(db.String(150), nullable=False)
    plant_image = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Integer, nullable=False)
    delivery_fee = db.Column(db.Integer, nullable=False, default=0)
    coupon_code = db.Column(db.String(32), nullable=True)
    coupon_discount = db.Column(db.Integer, nullable=False, default=0)
    grand_total = db.Column(db.Integer, nullable=False)
    payment_method = db.Column(db.String(30), nullable=True)
    payment_reference = db.Column(db.String(120), nullable=True)
    payment_status = db.Column(db.String(30), nullable=False, default="pending")
    order_status = db.Column(db.String(30), nullable=False, default="address_confirmed")
    order_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("Store", backref=db.backref("orders", lazy="dynamic"))


class SupportTicket(db.Model):
    __tablename__ = "support_ticket"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("store.id"), nullable=False, index=True)
    reference_code = db.Column(db.String(20), nullable=False, unique=True, index=True)
    subject = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(40), nullable=False)
    priority = db.Column(db.String(20), nullable=False, default="medium")
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="open")
    assigned_agent = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("Store", backref=db.backref("support_tickets", lazy="dynamic"))


class SupportMessage(db.Model):
    __tablename__ = "support_message"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("support_ticket.id"), nullable=False, index=True)
    sender_role = db.Column(db.String(20), nullable=False)
    sender_name = db.Column(db.String(120), nullable=True)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    ticket = db.relationship(
        "SupportTicket",
        backref=db.backref("messages", lazy="select", cascade="all, delete-orphan"),
    )


class ProductReview(db.Model):
    __tablename__ = "product_review"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("store.id"), nullable=False, index=True)
    plant_id = db.Column(db.String(80), nullable=False, index=True)
    rating = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(120), nullable=True)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("Store", backref=db.backref("product_reviews", lazy="dynamic"))
    __table_args__ = (
        db.UniqueConstraint("user_id", "plant_id", name="uq_review_user_plant"),
    )


class UserProfile(db.Model):
    __tablename__ = "user_profile"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("store.id"), nullable=False, unique=True, index=True)
    role = db.Column(db.String(20), nullable=False, default="customer")
    loyalty_points = db.Column(db.Integer, nullable=False, default=0)
    referral_code = db.Column(db.String(32), nullable=True, unique=True)
    referred_by = db.Column(db.String(32), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("Store", backref=db.backref("profile", uselist=False))


class ReturnRequest(db.Model):
    __tablename__ = "return_request"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False, unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("store.id"), nullable=False, index=True)
    reason = db.Column(db.String(150), nullable=False)
    details = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(30), nullable=False, default="requested")
    admin_note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    order = db.relationship("Order", backref=db.backref("return_request_record", uselist=False))
    user = db.relationship("Store", backref=db.backref("return_requests", lazy="dynamic"))


class StockAlertSubscription(db.Model):
    __tablename__ = "stock_alert_subscription"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("store.id"), nullable=False, index=True)
    plant_id = db.Column(db.String(80), nullable=False, index=True)
    variant_code = db.Column(db.String(40), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("Store", backref=db.backref("stock_alert_subscriptions", lazy="dynamic"))
    __table_args__ = (
        db.UniqueConstraint("user_id", "plant_id", "variant_code", name="uq_stock_alert_user_plant_variant"),
    )


class ReviewModeration(db.Model):
    __tablename__ = "review_moderation"

    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey("product_review.id"), nullable=False, unique=True, index=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    moderated_by = db.Column(db.String(120), nullable=True)
    moderated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    review = db.relationship("ProductReview", backref=db.backref("moderation", uselist=False))
