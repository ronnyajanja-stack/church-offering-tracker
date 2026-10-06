import os
import secrets
import sqlite3
from datetime import datetime, timedelta, date
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv

# Load local environment variables from .env if present
load_dotenv()

app = Flask(__name__)

# Configure application secret key
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-in-production-64char")

# Fix headers when deployed behind Render reverse proxy (ensures HTTPS callbacks match)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Database path configuration (supports optional Render persistent disk at /var/data)
DATA_DIR = os.getenv("DATA_DIR", ".")
DATABASE = os.path.join(DATA_DIR, "church_tracker.db")

# ---------------------------------------------------------
# GOOGLE OAUTH CONFIGURATION
# ---------------------------------------------------------
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"}
)

# ---------------------------------------------------------
# DATABASE UTILITIES
# ---------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes tables from schema.sql if they do not exist."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if os.path.exists(schema_path):
        with get_db() as db:
            with open(schema_path, "r", encoding="utf-8") as f:
                db.executescript(f.read())
            db.commit()

# ---------------------------------------------------------
# AUTHENTICATION DECORATOR
# ---------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to access the treasury portal.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# ---------------------------------------------------------
# AUTHENTICATION ROUTES
# ---------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")

        if not full_name or not email or not phone or not password:
            flash("All fields are mandatory.", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template("register.html")

        hashed_password = generate_password_hash(password)
        db = get_db()
        try:
            db.execute("""
                INSERT INTO users (full_name, email, phone, password_hash)
                VALUES (?, ?, ?, ?)
            """, (full_name, email, phone, hashed_password))
            db.commit()
            flash("Account registered successfully! You can now log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("An account with that email or phone number already exists.", "error")
            return render_template("register.html")

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()  # Accepts Email or Phone
        password = request.form.get("password")

        if not identifier or not password:
            flash("Please provide both email/phone and your password.", "error")
            return render_template("login.html")

        db = get_db()
        user = db.execute("""
            SELECT * FROM users WHERE email = ? OR phone = ?
        """, (identifier, identifier)).fetchone()

        if user and user["password_hash"] and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["full_name"]
            session["user_role"] = user["role"]
            flash(f"Welcome back, {user['full_name']}!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid email/phone or password.", "error")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out successfully.", "info")
    return redirect(url_for("login"))

# ---------------------------------------------------------
# GOOGLE OAUTH ROUTES
# ---------------------------------------------------------
@app.route("/login/google")
def google_login():
    redirect_uri = url_for("google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route("/login/google/callback")
def google_callback():
    try:
        token = google.authorize_access_token()
        user_info = token.get("userinfo")
    except Exception as e:
        flash(f"Authentication with Google failed: {str(e)}", "error")
        return redirect(url_for("login"))

    if not user_info or not user_info.get("email"):
        flash("Could not obtain user email from Google.", "error")
        return redirect(url_for("login"))

    email = user_info["email"].lower()
    full_name = user_info.get("name", "Church Member")
    google_id = user_info.get("sub")

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ? OR google_id = ?", (email, google_id)).fetchone()

    if not user:
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO users (full_name, email, google_id, role)
            VALUES (?, ?, ?, 'member')
        """, (full_name, email, google_id))
        db.commit()
        user_id = cursor.lastrowid
        role = "member"
    else:
        user_id = user["id"]
        role = user["role"]
        if not user["google_id"]:
            db.execute("UPDATE users SET google_id = ? WHERE id = ?", (google_id, user_id))
            db.commit()

    session.clear()
    session["user_id"] = user_id
    session["user_name"] = full_name
    session["user_role"] = role

    flash(f"Signed in successfully via Google as {email}", "success")
    return redirect(url_for("dashboard"))

# ---------------------------------------------------------
# PASSWORD RECOVERY ROUTES
# ---------------------------------------------------------
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if user:
            token = secrets.token_urlsafe(32)
            expiry = datetime.now() + timedelta(minutes=30)
            
            db.execute("""
                UPDATE users SET reset_token = ?, reset_token_expiry = ? WHERE id = ?
            """, (token, expiry, user["id"]))
            db.commit()

            # Output the reset URL directly for local development and demonstration
            reset_url = url_for("reset_password", token=token, _external=True)
            flash(f"Password reset link generated: {reset_url}", "info")
            return redirect(url_for("login"))
        else:
            flash("If that email address exists in our database, a reset link has been dispatched.", "info")
            return redirect(url_for("login"))

    return render_template("forgot_password.html")

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    db = get_db()
    user = db.execute("""
        SELECT * FROM users WHERE reset_token = ? AND reset_token_expiry > ?
    """, (token, datetime.now())).fetchone()

    if not user:
        flash("Reset token is invalid or has expired. Please request a new one.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")

        if not new_password or new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("reset_password.html", token=token, user=user)

        if len(new_password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("reset_password.html", token=token, user=user)

        hashed = generate_password_hash(new_password)
        db.execute("""
            UPDATE users 
            SET password_hash = ?, reset_token = NULL, reset_token_expiry = NULL 
            WHERE id = ?
        """, (hashed, user["id"]))
        db.commit()

        flash("Your password has been reset successfully. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html", token=token, user=user)

# ---------------------------------------------------------
# TREASURY DASHBOARD & TRANSACTION PROCESSING
# ---------------------------------------------------------
@app.route("/")
@login_required
def dashboard():
    db = get_db()

    # Calculate net balance per category: Inflows - Outflows
    funds = db.execute("""
        SELECT 
            c.id,
            c.name,
            COALESCE(SUM(CASE WHEN t.transaction_type = 'contribution' THEN t.amount ELSE 0 END), 0) AS total_in,
            COALESCE(SUM(CASE WHEN t.transaction_type = 'disbursement' THEN t.amount ELSE 0 END), 0) AS total_out,
            (COALESCE(SUM(CASE WHEN t.transaction_type = 'contribution' THEN t.amount ELSE 0 END), 0) -
             COALESCE(SUM(CASE WHEN t.transaction_type = 'disbursement' THEN t.amount ELSE 0 END), 0)) AS balance
        FROM fund_categories c
        LEFT JOIN transactions t ON c.id = t.category_id
        GROUP BY c.id, c.name
        ORDER BY c.id ASC
    """).fetchall()

    # Net total across all church coffers
    total_coffers = sum(row["balance"] for row in funds)

    # Fetch last 10 transactions with contributor details
    recent_transactions = db.execute("""
        SELECT 
            t.*, 
            c.name AS category_name, 
            u.full_name AS member_name
        FROM transactions t
        JOIN fund_categories c ON t.category_id = c.id
        LEFT JOIN users u ON t.user_id = u.id
        ORDER BY t.service_date DESC, t.id DESC
        LIMIT 10
    """).fetchall()

    return render_template(
        "index.html",
        funds=funds,
        total_coffers=total_coffers,
        recent_transactions=recent_transactions,
        user_name=session.get("user_name"),
        today=date.today().isoformat()
    )

@app.route("/record", methods=["POST"])
@login_required
def record_transaction():
    category_id = request.form.get("category_id")
    transaction_type = request.form.get("transaction_type")
    payment_method = request.form.get("payment_method")
    reference_no = request.form.get("reference_no", "").strip()
    service_date = request.form.get("service_date") or date.today().isoformat()
    notes = request.form.get("notes", "").strip()
    user_id = session.get("user_id")

    try:
        amount = float(request.form.get("amount", 0))
    except (ValueError, TypeError):
        amount = 0.0

    if amount <= 0 or not category_id or not transaction_type or not payment_method:
        flash("Please provide a valid positive amount and select all required fields.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()
    db.execute("""
        INSERT INTO transactions (
            user_id, category_id, transaction_type, amount, 
            payment_method, reference_no, service_date, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, category_id, transaction_type, amount, payment_method, reference_no, service_date, notes))
    db.commit()

    flash(f"Transaction of KSh {amount:,.2f} logged successfully!", "success")
    return redirect(url_for("dashboard"))

# ---------------------------------------------------------
# APPLICATION ENTRY POINT
# ---------------------------------------------------------
if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)