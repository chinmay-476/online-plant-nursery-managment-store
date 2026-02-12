from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from flask import flash, redirect, session, url_for


def clear_user_session() -> None:
    for key in ["user_id", "user_name", "user_email", "checkout", "last_order_id", "cart_coupon", "cart_loyalty_discount"]:
        session.pop(key, None)


def clear_admin_session() -> None:
    for key in ["admin_id", "admin_name", "admin_email"]:
        session.pop(key, None)


def is_admin_identity(email: str | None, admin_emails: set[str]) -> bool:
    return str(email or "").strip().lower() in admin_emails


def is_admin_session(admin_emails: set[str]) -> bool:
    return bool(session.get("admin_id")) and is_admin_identity(session.get("admin_email"), admin_emails)


def login_required(view_fn: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view_fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if "user_id" not in session:
            flash("Please login to continue", "warning")
            return redirect(url_for("login"))
        return view_fn(*args, **kwargs)

    return wrapper


def admin_required(admin_emails: set[str]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(view_fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view_fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not is_admin_session(admin_emails):
                flash("Admin login required.", "warning")
                return redirect(url_for("admin_login", next=url_for(view_fn.__name__)))
            return view_fn(*args, **kwargs)

        return wrapper

    return decorator
