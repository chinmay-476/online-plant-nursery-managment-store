# Database Documentation - Flora Botanical

## Active Database Configuration
This project is configured for MySQL (Workbench/local server) using:

- Host: `localhost`
- Port: `3306`
- User: `root`
- Password: `chin1987`
- Database: `flora_db`
- SQLAlchemy URL: `mysql+pymysql://root:chin1987@localhost:3306/flora_db`

The same values are present in:

- `.env`
- `.env.example`
- `db.py` defaults

## Admin Bootstrap Configuration
Admin bootstrap runs on startup (`_ensure_default_admin_user` in `eco_basket/application.py`) and ensures an admin account exists.

- Admin email: `chinmay@gmail.com`
- Admin password: `chin1987`
- Admin allowlist: `ADMIN_EMAILS=admin@flora.local,chinmay@gmail.com`
- Admin portal URL: `/admin/login` (separate session from customer `/login`)

Environment keys:

- `DEFAULT_ADMIN_EMAIL`
- `DEFAULT_ADMIN_PASSWORD`
- `DEFAULT_ADMIN_NAME`
- `DEFAULT_ADMIN_PHONE`
- `AUTO_CREATE_DEFAULT_ADMIN=true`

## Database Initialization
1. Create database (one-time):
```bash
python db.py
```

2. Start app:
```bash
python app.py
```

On startup the app runs:
- `db.create_all()` for tables
- `_ensure_default_admin_user()` to create/update the configured admin login

## SQLAlchemy Tables (Current)

### `store`
- `id` (PK)
- `name`
- `email` (unique, indexed)
- `phone_number`
- `password` (hashed)
- `created_at`

### `catalog_override`
- `plant_id` (PK)
- `price_override`
- `stock_override`
- `offer_override`
- `new_override`
- `is_active`
- `updated_at`

### `cart_item`
- `id` (PK)
- `user_id` (FK -> `store.id`)
- `plant_id`
- `quantity`, `unit_price`
- `created_at`, `updated_at`

### `wishlist_item`
- `id` (PK)
- `user_id` (FK -> `store.id`)
- `plant_id`
- `created_at`
- Unique: `(user_id, plant_id)`

### `order`
- `id` (PK)
- `user_id` (FK -> `store.id`)
- `customer_name`, `email`, `phone_number`
- `address`, `pincode`, `address_type`
- `plant_id`, `plant_name`, `plant_image`
- `quantity`, `unit_price`, `total_price`
- `delivery_fee`, `coupon_code`, `coupon_discount`, `grand_total`
- `payment_method`, `payment_reference`, `payment_status`
- `order_status`
- `order_date`

### `user_profile`
- `id` (PK)
- `user_id` (FK -> `store.id`)
- `role`
- `loyalty_points`
- `referral_code` (unique, nullable)
- `referred_by`
- `created_at`, `updated_at`

### `support_ticket`
- `id` (PK)
- `user_id` (FK -> `store.id`)
- `reference_code` (unique)
- `subject`, `category`, `priority`, `description`
- `status`, `assigned_agent`
- `created_at`, `updated_at`

### `support_message`
- `id` (PK)
- `ticket_id` (FK -> `support_ticket.id`)
- `sender_role`, `sender_name`
- `message`
- `created_at`

### `product_review`
- `id` (PK)
- `user_id` (FK -> `store.id`)
- `plant_id`
- `rating`, `title`, `comment`
- `created_at`, `updated_at`
- Unique: `(user_id, plant_id)`

### `review_moderation`
- `id` (PK)
- `review_id` (FK -> `product_review.id`, unique)
- `status`
- `moderated_by`, `moderated_at`
- `created_at`

### `return_request`
- `id` (PK)
- `order_id` (FK -> `order.id`, unique)
- `user_id` (FK -> `store.id`)
- `reason`, `details`
- `status`
- `admin_note`
- `created_at`
- `updated_at`

### `stock_alert_subscription`
- `id` (PK)
- `user_id` (FK -> `store.id`)
- `plant_id`
- `variant_code`
- `status`
- `created_at`
- Unique: `(user_id, plant_id, variant_code)`

## Notes
- Passwords are stored hashed using Werkzeug.
- Admin session is separate (`admin_id`, `admin_email`) and does not reuse customer cart/order session keys.
- If you change database credentials, update both `.env` and `.env.example`.
