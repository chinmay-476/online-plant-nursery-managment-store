from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

from .config import ensure_mysql_database_exists, env_bool
from .database import db
from .models import Store, UserProfile
from .routes import register_routes


def _ensure_default_admin_user(app: Flask) -> None:
    if not env_bool("AUTO_CREATE_DEFAULT_ADMIN", True):
        return

    admin_email = str(os.getenv("DEFAULT_ADMIN_EMAIL", "chinmay@gmail.com")).strip().lower()
    admin_password = str(os.getenv("DEFAULT_ADMIN_PASSWORD", "chin1987")).strip()
    admin_name = str(os.getenv("DEFAULT_ADMIN_NAME", "Chinmay Admin")).strip() or "Chinmay Admin"
    admin_phone = str(os.getenv("DEFAULT_ADMIN_PHONE", "9876543210")).strip() or "9876543210"
    if not admin_email or not admin_password:
        return

    admin_user = Store.query.filter_by(email=admin_email).first()
    if admin_user is None:
        admin_user = Store(
            name=admin_name,
            email=admin_email,
            phone_number=admin_phone,
            password="",
        )
        admin_user.set_password(admin_password)
        db.session.add(admin_user)
        db.session.flush()
    else:
        if not admin_user.password:
            admin_user.set_password(admin_password)
        if not admin_user.name:
            admin_user.name = admin_name
        if not admin_user.phone_number:
            admin_user.phone_number = admin_phone

    profile = UserProfile.query.filter_by(user_id=admin_user.id).first()
    if profile is None:
        profile = UserProfile(
            user_id=admin_user.id,
            role="admin",
            loyalty_points=0,
            referral_code=None,
            referred_by=None,
        )
        db.session.add(profile)
    else:
        profile.role = "admin"

    current_admins = {
        value.strip().lower()
        for value in str(app.config.get("ADMIN_EMAILS", "")).split(",")
        if value.strip()
    }
    current_admins.add(admin_email)
    app.config["ADMIN_EMAILS"] = ",".join(sorted(current_admins))

    db.session.commit()


def _create_app() -> Flask:
    load_dotenv()
    ensure_mysql_database_exists()

    base_dir = Path(__file__).resolve().parents[1]
    app = Flask(
        __name__,
        template_folder=str(base_dir / "templates"),
        static_folder=str(base_dir / "static"),
    )

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me-in-production")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///instance/flora.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SESSION_COOKIE_SECURE"] = env_bool("SESSION_COOKIE_SECURE", False)
    app.config["ADMIN_EMAILS"] = os.getenv("ADMIN_EMAILS", "admin@flora.local,chinmay@gmail.com")

    db.init_app(app)
    with app.app_context():
        db.create_all()
        _ensure_default_admin_user(app)

    register_routes(app)
    return app


app = _create_app()

__all__ = ["app", "db", "env_bool"]
