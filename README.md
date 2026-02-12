# Flora Botanical (Flask)

Flora Botanical is a Flask-based plant store app with authentication, wishlist, and a server-authoritative checkout/payment flow.

## Key Improvements Included
- Environment-based config (`SECRET_KEY`, `DATABASE_URL`, etc.)
- Password hashing with Werkzeug
- Safer session defaults
- Server-side order creation and payment processing
- CSRF-protected payment submission
- Added missing templates (`newarrivals`, `offersection`)
- Project hygiene files (`requirements.txt`, `.gitignore`, `.env.example`)

## Quick Start
1. Create and activate a virtual environment.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Copy env file:
   - `copy .env.example .env` (Windows)
4. Run app:
   - `python app.py`

The app defaults to SQLite at `instance/stor.db` if `DATABASE_URL` is not set.

## Optional MySQL
- Set `DATABASE_URL` in `.env`, example:
  - `DATABASE_URL=mysql+pymysql://user:password@localhost/flora_db`
- You can use `db.py` to create the database first.

## Optional Flask-Migrate
`Flask-Migrate` is optional in this environment. The app runs without it using a built-in no-op fallback.
If your package index provides it, you can install it for migration commands:
- `pip install Flask-Migrate`

## Notes
- For schema evolution, prefer Flask-Migrate over only `db.create_all()`.
- Existing plaintext passwords are auto-upgraded to hashed format on successful login.
