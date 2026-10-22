import os
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
import requests
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
    send_file,
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super-secret-church-treasury-key-2026")
DB_NAME = os.getenv("DB_NAME", "church_tracker.db")

# Google OAuth Settings (from .env or environment variables)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    if os.path.exists("schema.sql"):
        with get_db() as conn:
            with open("schema.sql", "r") as f:
                conn.executescript(f.read())


# --- AUTH DECORATORS ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to access your portal.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def role_redirect(role):
    if role == "pastor":
        return redirect(url_for("pastor_dashboard"))
    elif role == "treasurer":
        return redirect(url_for("treasurer_dashboard"))
    elif role == "clerk":
        return redirect(url_for("clerk_dashboard"))
    return redirect(url_for("login"))


# --- BASE & AUTH ROUTES ---

@app.route("/")
def index():
    if "user_id" in session:
        return role_redirect(session.get("role", "pastor"))
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return role_redirect(session.get("role", "pastor"))

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")

        if not identifier or not password:
            flash("Please provide both email/phone and password.", "error")
            return render_template("login.html")

        conn = get_db()
        cursor = conn.cursor()
        # Search by email or phone
        cursor.execute(
            """
            SELECT * FROM users 
            WHERE email = ? OR phone = ?
            """,
            (identifier, identifier),
        )
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["church_id"] = user["church_id"]
            session["role"] = user["role"]
            session["full_name"] = user["full_name"]
            session["email"] = user["email"]
            flash(f"Welcome back, {user['full_name']}!", "success")
            return role_redirect(user["role"])
        else:
            flash("Invalid email/phone or password.", "error")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return role_redirect(session.get("role", "pastor"))

    if request.method == "POST":
        church_name = request.form.get("church_name", "").strip()
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        if not church_name or not full_name or not email or not password:
            flash("Please fill in all required fields.", "error")
            return render_template("register.html")

        conn = get_db()
        cursor = conn.cursor()

        # Check if user already exists
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        existing_user = cursor.fetchone()
        if existing_user:
            conn.close()
            flash("An account with that email already exists. Please sign in.", "error")
            return redirect(url_for("login"))

        # Create Church Organization (with 30-day free trial)
        trial_ends = (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            """
            INSERT INTO churches (name, trial_end, subscription_status, created_at)
            VALUES (?, ?, 'trial', CURRENT_TIMESTAMP)
            """,
            (church_name, trial_ends),
        )
        church_id = cursor.lastrowid

        # Create Pastor/Lead User
        password_hash = generate_password_hash(password)
        cursor.execute(
            """
            INSERT INTO users (church_id, full_name, email, phone, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?, 'pastor', CURRENT_TIMESTAMP)
            """,
            (church_id, full_name, email, phone, password_hash),
        )
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Establish Session
        session["user_id"] = user_id
        session["church_id"] = church_id
        session["role"] = "pastor"
        session["full_name"] = full_name
        session["email"] = email

        flash("Registration successful! Welcome to your 30-day free trial.", "success")
        return redirect(url_for("pastor_dashboard"))

    return render_template("register.html")


# --- GOOGLE OAUTH HANDLERS ---

@app.route("/google/login")
def google_login():
    if not GOOGLE_CLIENT_ID:
        flash("Google login is not configured yet. Set GOOGLE_CLIENT_ID in your environment.", "error")
        return redirect(url_for("login"))

    google_provider_cfg = requests.get(GOOGLE_DISCOVERY_URL).json()
    authorization_endpoint = google_provider_cfg["authorization_endpoint"]

    # Redirect URI pointing to /google/callback
    redirect_uri = url_for("google_callback", _external=True)

    request_uri = (
        f"{authorization_endpoint}?response_type=code"
        f"&client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=openid%20email%20profile"
        f"&access_type=offline"
    )
    return redirect(request_uri)


@app.route("/google/callback")
def google_callback():
    code = request.args.get("code")
    if not code:
        flash("Google authentication failed. Please try again.", "error")
        return redirect(url_for("login"))

    google_provider_cfg = requests.get(GOOGLE_DISCOVERY_URL).json()
    token_endpoint = google_provider_cfg["token_endpoint"]

    # Exchange code for tokens
    token_response = requests.post(
        token_endpoint,
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": url_for("google_callback", _external=True),
            "grant_type": "authorization_code",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ).json()

    userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
    user_info = requests.get(
        userinfo_endpoint,
        headers={"Authorization": f"Bearer {token_response.get('access_token')}"},
    ).json()

    if not user_info.get("email_verified", False):
        flash("Google account email is not verified.", "error")
        return redirect(url_for("login"))

    email = user_info["email"].lower()
    full_name = user_info.get("name", "Church Leader")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()

    # User already exists -> Log in directly
    if user:
        session["user_id"] = user["id"]
        session["church_id"] = user["church_id"]
        session["role"] = user["role"]
        session["full_name"] = user["full_name"]
        session["email"] = user["email"]
        conn.close()
        flash(f"Signed in as {user['full_name']}", "success")
        return role_redirect(user["role"])

    # First time sign-up via Google -> Provision Church & Account
    trial_ends = (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
        INSERT INTO churches (name, trial_end, subscription_status, created_at)
        VALUES (?, ?, 'trial', CURRENT_TIMESTAMP)
        """,
        (f"{full_name}'s Ministry", trial_ends),
    )
    church_id = cursor.lastrowid

    # Dummy secure hash for OAuth users
    dummy_hash = generate_password_hash(os.urandom(24).hex())
    cursor.execute(
        """
        INSERT INTO users (church_id, full_name, email, phone, password_hash, role, created_at)
        VALUES (?, ?, ?, '', ?, 'pastor', CURRENT_TIMESTAMP)
        """,
        (church_id, full_name, email, dummy_hash),
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()

    session["user_id"] = user_id
    session["church_id"] = church_id
    session["role"] = "pastor"
    session["full_name"] = full_name
    session["email"] = email

    flash("Account created with Google! Your 30-day trial is ready.", "success")
    return redirect(url_for("pastor_dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out successfully.", "success")
    return redirect(url_for("login"))


@app.route("/forgot-password")
def forgot_password():
    return render_template("forgot_password.html")


@app.route("/reset-password")
def reset_password():
    return render_template("reset_password.html")


@app.route("/verify-otp")
def verify_otp():
    return render_template("verify_otp.html")


# --- DASHBOARDS ---

@app.route("/pastor/dashboard")
@login_required
def pastor_dashboard():
    return render_template("pastor_dashboard.html", user=session)


@app.route("/treasurer/dashboard")
@login_required
def treasurer_dashboard():
    return render_template("treasurer_dashboard.html", user=session)


@app.route("/clerk/dashboard")
@login_required
def clerk_dashboard():
    return render_template("clerk_dashboard.html", user=session)


@app.route("/billing")
@login_required
def billing():
    return render_template("billing.html", user=session)


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)