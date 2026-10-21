from datetime import date, datetime, timedelta
from email.message import EmailMessage
from functools import wraps
import os
import random
import smtplib
import sqlite3

from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

# Modular Daraja integration helper
from daraja import trigger_stk_push

load_dotenv()

app = Flask(__name__)
# Tells Flask it is behind a reverse proxy (Render, Railway, Nginx) so url_for generates https://
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.secret_key = os.environ.get(
    "SECRET_KEY", "super-secret-church-treasury-key-2026"
)
DATABASE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "church_tracker.db"
)

# -----------------------------------------------------------------------------
# GOOGLE OAUTH CONFIGURATION (AUTHLIB)
# -----------------------------------------------------------------------------
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# SMTP / Email Configuration (Port 465 SSL)
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 465))
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

# Offering Categories (Inflow)
OFFERING_CATEGORIES = [
    ("NORMAL_OFFERING", "Normal / Sunday Basket Offering"),
    ("TITHE", "Tithe Collection"),
    ("THANKSGIVING", "Thanksgiving Offering"),
    ("DEVELOPMENT", "Church Development / Building Fund"),
    ("SUNDAY_SCHOOL", "Children / Sunday School Ministry"),
    ("MISSIONS", "Missions & Evangelism Outreach"),
    ("WELFARE", "Welfare / Benevolence / Needy Fund"),
    ("FIRST_FRUITS", "First Fruits / Harvest Offering"),
    ("OTHER", "Other Special Collection"),
]

# Expense Categories (Outflow)
EXPENSE_CATEGORIES = [
    ("HONORARIUM", "Honorarium & Pastoral Stipend"),
    ("UTILITIES", "Utilities (Electricity, Water, Internet)"),
    ("RENT_FACILITY", "Church Rent & Facility Lease"),
    ("EQUIPMENT_MAINTENANCE", "Equipment, Sound & Repairs"),
    ("WELFARE_DISBURSAL", "Welfare / Benevolence Disbursal"),
    ("SUNDAY_SCHOOL_EXPENSE", "Sunday School Materials / Refreshments"),
    ("MISSIONS_OUTREACH", "Missions Outreach & Evangelism Logistics"),
    ("ADMIN_OPERATIONAL", "Administrative & Office Supplies"),
    ("TRANSPORT", "Transport & Fuel Logistics"),
    ("OTHER_EXPENSE", "Other Miscellaneous Expense"),
]


def send_otp_email(target_email, otp_code):
  """Dispatches verification code via direct SSL with terminal dev fallback."""
  if not SMTP_EMAIL or not SMTP_PASSWORD:
    print("\n==========================================")
    print(f"[DEV MODE] Missing SMTP credentials! SMTP_EMAIL='{SMTP_EMAIL}'")
    print(f"[DEV MODE] Email OTP for {target_email}: {otp_code}")
    print("==========================================\n")
    return True

  try:
    msg = EmailMessage()
    msg["Subject"] = "Your Church Portal Verification Code"
    msg["From"] = SMTP_EMAIL
    msg["To"] = target_email
    msg.set_content(
        f"Hello,\n\nYour one-time registration verification code is:"
        f" {otp_code}\n\nThis code will expire in 10 minutes.\n\nIf you did not"
        " initiate this request, please disregard this email."
    )

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=15) as server:
      server.login(SMTP_EMAIL, SMTP_PASSWORD)
      server.send_message(msg)

    print(f">> OTP successfully dispatched to {target_email} via SSL!")
    return True
  except Exception as e:
    print(f"\n[SMTP FAILURE ERROR]: {repr(e)}")
    print(f"[FALLBACK CODE FOR LOGIN]: {otp_code}\n")
    return False


# -----------------------------------------------------------------------------
# DATABASE HELPERS
# -----------------------------------------------------------------------------
def get_db():
  if "db" not in g:
    g.db = sqlite3.connect(DATABASE, timeout=10.0)
    g.db.row_factory = sqlite3.Row
    g.db.execute("PRAGMA foreign_keys = ON;")
    g.db.execute("PRAGMA journal_mode = WAL;")
  return g.db


@app.teardown_appcontext
def close_db(error):
  db = g.pop("db", None)
  if db is not None:
    db.close()


def init_db():
  with app.app_context():
    db = get_db()
    schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "schema.sql"
    )
    if os.path.exists(schema_path):
      with open(schema_path, mode="r", encoding="utf-8") as f:
        db.cursor().executescript(f.read())

    # Ensure pending STK push tracking table exists
    db.execute("""
            CREATE TABLE IF NOT EXISTS mpesa_stk_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checkout_request_id TEXT UNIQUE NOT NULL,
                church_id INTEGER NOT NULL,
                user_id INTEGER,
                phone_number TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                service_type TEXT DEFAULT 'FIRST_SERVICE',
                notes TEXT,
                status TEXT DEFAULT 'PENDING',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
    db.commit()


# -----------------------------------------------------------------------------
# CONTEXT PROCESSORS
# -----------------------------------------------------------------------------
@app.context_processor
def inject_subscription_status():
  return {
      "in_grace": getattr(g, "in_grace", False),
      "days_left_in_grace": getattr(g, "days_left_in_grace", 0),
  }


# -----------------------------------------------------------------------------
# AUTH & ACCESS DECORATORS
# -----------------------------------------------------------------------------
def login_required(f):

  @wraps(f)
  def decorated_function(*args, **kwargs):
    if "user_id" not in session or "church_id" not in session:
      flash("Please sign in to access your church portal.", "error")
      return redirect(url_for("login"))
    return f(*args, **kwargs)

  return decorated_function


def subscription_check(f):

  @wraps(f)
  def decorated_function(*args, **kwargs):
    church_id = session.get("church_id")
    if not church_id:
      if request.is_json:
        return (
            jsonify({"success": False, "error": "Authentication required."}),
            401,
        )
      return redirect(url_for("login"))

    conn = get_db()
    sub = conn.execute(
        """
            SELECT * FROM church_subscriptions
            WHERE church_id = ?
            ORDER BY id DESC LIMIT 1
            """,
        (church_id,),
    ).fetchone()

    if sub:
      today = date.today()
      try:
        expires_at = datetime.strptime(sub["expires_at"], "%Y-%m-%d").date()
      except (ValueError, TypeError):
        expires_at = today

      grace_cutoff = expires_at + timedelta(days=3)

      if today > grace_cutoff:
        if request.is_json:
          return (
              jsonify({
                  "success": False,
                  "error": "Subscription expired. Please renew your plan.",
              }),
              403,
          )
        flash(
            "Your subscription or free trial has expired. Please renew to"
            " continue.",
            "error",
        )
        return redirect(url_for("billing"))

      g.in_grace = expires_at < today <= grace_cutoff
      g.days_left_in_grace = (grace_cutoff - today).days

    return f(*args, **kwargs)

  return decorated_function


# -----------------------------------------------------------------------------
# AUTHENTICATION, OTP & GOOGLE OAUTH ROUTES
# -----------------------------------------------------------------------------
@app.route("/")
def index():
  if "user_id" in session:
    return redirect(url_for("role_dispatcher"))
  return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
  if request.method == "POST":
    identifier = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    conn = get_db()
    user = conn.execute(
        """
            SELECT * FROM users
            WHERE (email = ? OR phone = ?)
            """,
        (identifier, identifier),
    ).fetchone()

    if user and check_password_hash(user["password_hash"], password):
      church = conn.execute(
          "SELECT name FROM churches WHERE id = ?", (user["church_id"],)
      ).fetchone()

      session.clear()
      session["user_id"] = user["id"]
      session["user_name"] = user["name"]
      session["user_role"] = user["role"]
      session["church_id"] = user["church_id"]
      session["church_name"] = church["name"] if church else "Church Treasury"

      return redirect(url_for("role_dispatcher"))

    flash("Invalid email/phone or password.", "error")
  return render_template("login.html")


@app.route("/google-login")
def google_login():
  """Redirects the user to Google OAuth consent screen."""
  redirect_uri = url_for("google_callback", _external=True)
  return google.authorize_redirect(redirect_uri)


@app.route("/login/google/callback")
def google_callback():
  """Handles token response from Google and authenticates user session."""
  try:
    token = google.authorize_access_token()
    user_info = token.get("userinfo")
  except Exception as e:
    flash(f"Google Sign-In failed: {str(e)}", "error")
    return redirect(url_for("login"))

  if not user_info:
    flash("Could not obtain user details from Google.", "error")
    return redirect(url_for("login"))

  google_email = user_info["email"].lower().strip()

  conn = get_db()
  user = conn.execute(
      "SELECT * FROM users WHERE email = ?", (google_email,)
  ).fetchone()

  if not user:
    flash(
        f"No church account registered with {google_email}. Please register"
        " your church first.",
        "info",
    )
    return redirect(url_for("register"))

  church = conn.execute(
      "SELECT name FROM churches WHERE id = ?", (user["church_id"],)
  ).fetchone()

  session.clear()
  session["user_id"] = user["id"]
  session["user_name"] = user["name"]
  session["user_role"] = user["role"]
  session["church_id"] = user["church_id"]
  session["church_name"] = church["name"] if church else "Church Treasury"

  flash(f"Welcome back, {user['name']}!", "success")
  return redirect(url_for("role_dispatcher"))


@app.route("/register", methods=["GET", "POST"])
def register():
  if request.method == "POST":
    church_name = request.form.get("church_name", "").strip()
    admin_name = (
        request.form.get("name") or request.form.get("full_name") or ""
    ).strip()
    email = request.form.get("email", "").strip().lower()
    phone = (
        request.form.get("phone") or request.form.get("phone_number") or ""
    ).strip()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")
    role = request.form.get("role", "TREASURER")

    if not church_name and admin_name:
      church_name = f"{admin_name}'s Church"

    if not church_name or not email or not password or not confirm_password:
      flash("All required fields must be filled.", "error")
      return render_template("register.html")

    if password != confirm_password:
      flash("Passwords do not match.", "error")
      return render_template("register.html")

    if len(password) < 6:
      flash("Password must be at least 6 characters long.", "error")
      return render_template("register.html")

    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM users WHERE email = ?", (email,)
    ).fetchone()
    if existing:
      flash("An account with that email already exists.", "error")
      return render_template("register.html")

    otp = f"{random.randint(100000, 999999)}"
    expires_at = (datetime.now() + timedelta(minutes=10)).isoformat()

    session["pending_registration"] = {
        "church_name": church_name,
        "admin_name": admin_name,
        "email": email,
        "phone": phone,
        "password_hash": generate_password_hash(password),
        "role": role,
        "otp": otp,
        "expires_at": expires_at,
    }

    send_otp_email(email, otp)
    flash(f"A 6-digit verification code has been sent to {email}.", "info")
    return redirect(url_for("verify_otp"))

  return render_template("register.html")


@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
  pending = session.get("pending_registration")
  if not pending:
    flash("No registration in progress. Please sign up first.", "error")
    return redirect(url_for("register"))

  if request.method == "POST":
    user_otp = request.form.get("otp", "").strip()

    if datetime.now() > datetime.fromisoformat(pending["expires_at"]):
      session.pop("pending_registration", None)
      flash("OTP expired. Please register again.", "error")
      return redirect(url_for("register"))

    if user_otp != pending["otp"]:
      flash("Invalid OTP code. Please check and try again.", "error")
      return render_template("verify_otp.html", email=pending["email"])

    conn = get_db()
    cursor = conn.cursor()

    # Create Church Organization
    cursor.execute(
        "INSERT INTO churches (name, phone, email) VALUES (?, ?, ?)",
        (pending["church_name"], pending["phone"], pending["email"]),
    )
    church_id = cursor.lastrowid

    # 30-Day Free Trial
    today = date.today()
    trial_end = today + timedelta(days=30)
    cursor.execute(
        """
            INSERT INTO church_subscriptions 
            (church_id, plan_tier, billing_cycle, is_trial, trial_ends_at, expires_at, status)
            VALUES (?, 'TRIAL', 'MONTHLY', 1, ?, ?, 'ACTIVE')
            """,
        (church_id, trial_end.isoformat(), trial_end.isoformat()),
    )

    # Primary User
    cursor.execute(
        """
            INSERT INTO users (church_id, name, email, phone, password_hash, role)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
        (
            church_id,
            pending["admin_name"],
            pending["email"],
            pending["phone"],
            pending["password_hash"],
            pending["role"],
        ),
    )
    conn.commit()

    session.pop("pending_registration", None)
    flash("Registration verified successfully! Please sign in.", "success")
    return redirect(url_for("login"))

  return render_template("verify_otp.html", email=pending["email"])


@app.route("/resend-otp")
def resend_otp():
  pending = session.get("pending_registration")
  if not pending:
    flash("No active registration found. Please register.", "error")
    return redirect(url_for("register"))

  new_otp = f"{random.randint(100000, 999999)}"
  pending["otp"] = new_otp
  pending["expires_at"] = (datetime.now() + timedelta(minutes=10)).isoformat()
  session["pending_registration"] = pending

  send_otp_email(pending["email"], new_otp)
  flash(f"A new verification code has been sent to {pending['email']}.", "info")
  return redirect(url_for("verify_otp"))


@app.route("/logout")
def logout():
  session.clear()
  flash("Signed out successfully.", "info")
  return redirect(url_for("login"))


# -----------------------------------------------------------------------------
# ROLE DISPATCHER
# -----------------------------------------------------------------------------
@app.route("/role-dispatcher")
@login_required
def role_dispatcher():
  return redirect(url_for("treasurer_dashboard"))


# -----------------------------------------------------------------------------
# 1. CLERK MODULE
# -----------------------------------------------------------------------------
@app.route("/clerk/dashboard")
@login_required
@subscription_check
def clerk_dashboard():
  church_id = session.get("church_id")
  target_date = request.args.get("date", date.today().isoformat())
  conn = get_db()

  records = conn.execute(
      """
        SELECT g.*, u.name as recorder_name
        FROM giving_records g
        LEFT JOIN users u ON g.recorded_by_user_id = u.id
        WHERE g.church_id = ? AND g.service_date = ?
        ORDER BY g.id DESC
        """,
      (church_id, target_date),
  ).fetchall()

  summary_by_category = {}
  total_today = 0.0
  for r in records:
    amt = float(r["amount"] or 0)
    cat = r["category"]
    summary_by_category[cat] = summary_by_category.get(cat, 0.0) + amt
    total_today += amt

  expense_row = conn.execute(
      """
        SELECT COALESCE(SUM(amount), 0.0) as total_expenses
        FROM expenses
        WHERE church_id = ? AND expense_date = ?
        """,
      (church_id, target_date),
  ).fetchone()
  total_expenses_today = float(
      expense_row["total_expenses"] if expense_row else 0.0
  )
  net_today = total_today - total_expenses_today

  return render_template(
      "clerk_dashboard.html",
      records=records,
      categories=OFFERING_CATEGORIES,
      summary_by_category=summary_by_category,
      total_today=total_today,
      total_expenses_today=total_expenses_today,
      net_today=net_today,
      target_date=target_date,
  )


@app.route("/clerk/record-entry", methods=["POST"])
@login_required
@subscription_check
def record_entry():
  data = request.get_json() or {}
  church_id = session.get("church_id")
  user_id = session.get("user_id")

  category = data.get("category", "").strip().upper()
  payment_method = data.get("payment_method", "CASH").strip().upper()
  service_type = data.get("service_type", "FIRST_SERVICE").strip().upper()
  reference_code = data.get("reference_code", "").strip()
  notes = data.get("notes", "").strip()
  service_date_input = data.get("service_date", date.today().isoformat())

  valid_category_keys = [cat[0] for cat in OFFERING_CATEGORIES]
  if category not in valid_category_keys:
    return (
        jsonify({
            "success": False,
            "error": "Invalid offering category selected.",
        }),
        400,
    )

  try:
    amount = float(data.get("amount", 0))
  except (ValueError, TypeError):
    return (
        jsonify(
            {"success": False, "error": "Please enter a valid numeric amount."}
        ),
        400,
    )

  if amount <= 0:
    return (
        jsonify(
            {"success": False, "error": "Amount must be greater than zero."}
        ),
        400,
    )

  conn = get_db()
  cursor = conn.cursor()

  locked_check = cursor.execute(
      """
        SELECT id FROM giving_records
        WHERE church_id = ? AND service_date = ? AND batch_status = 'LOCKED'
        LIMIT 1
        """,
      (church_id, service_date_input),
  ).fetchone()

  if locked_check:
    return (
        jsonify({
            "success": False,
            "error": (
                "This service date batch has already been locked by the"
                " treasurer."
            ),
        }),
        403,
    )

  cursor.execute(
      """
        INSERT INTO giving_records 
        (church_id, recorded_by_user_id, service_date, service_type, category, payment_method, reference_code, amount, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
      (
          church_id,
          user_id,
          service_date_input,
          service_type,
          category,
          payment_method,
          reference_code,
          amount,
          notes,
      ),
  )
  new_id = cursor.lastrowid
  conn.commit()

  return jsonify({"success": True, "entry_id": new_id})


# -----------------------------------------------------------------------------
# 2. TREASURER MODULE
# -----------------------------------------------------------------------------
@app.route("/treasurer/dashboard")
@login_required
@subscription_check
def treasurer_dashboard():
  church_id = session.get("church_id")
  target_date = request.args.get("date", date.today().isoformat())
  conn = get_db()

  inflow_records = conn.execute(
      """
        SELECT g.*, u.name as recorder_name 
        FROM giving_records g
        LEFT JOIN users u ON g.recorded_by_user_id = u.id
        WHERE g.church_id = ? AND g.service_date = ?
        ORDER BY g.created_at DESC
        """,
      (church_id, target_date),
  ).fetchall()

  summary_by_mode = {
      "CASH": 0.0,
      "MPESA": 0.0,
      "BANK_TRANSFER": 0.0,
      "CHEQUE": 0.0,
  }
  summary_by_fund = {}
  is_batch_locked = False
  total_inflow = 0.0

  for r in inflow_records:
    amt = float(r["amount"] or 0)
    mode = r["payment_method"]
    fund = r["category"]

    summary_by_mode[mode] = summary_by_mode.get(mode, 0.0) + amt
    summary_by_fund[fund] = summary_by_fund.get(fund, 0.0) + amt
    total_inflow += amt

    if r["batch_status"] == "LOCKED":
      is_batch_locked = True

  expense_records = conn.execute(
      """
        SELECT e.*, u.name as recorder_name
        FROM expenses e
        LEFT JOIN users u ON e.recorded_by_user_id = u.id
        WHERE e.church_id = ? AND e.expense_date = ?
        ORDER BY e.created_at DESC
        """,
      (church_id, target_date),
  ).fetchall()

  total_expense = sum(float(e["amount"] or 0) for e in expense_records)
  net_balance = total_inflow - total_expense

  return render_template(
      "treasurer_dashboard.html",
      inflow_records=inflow_records,
      expense_records=expense_records,
      summary_by_mode=summary_by_mode,
      summary_by_fund=summary_by_fund,
      total_inflow=total_inflow,
      total_expense=total_expense,
      net_balance=net_balance,
      target_date=target_date,
      is_batch_locked=is_batch_locked,
      expense_categories=EXPENSE_CATEGORIES,
  )


@app.route("/treasurer/record-expense", methods=["POST"])
@login_required
@subscription_check
def record_expense():
  data = request.get_json() or {}
  church_id = session.get("church_id")
  user_id = session.get("user_id")

  expense_date_input = data.get("expense_date", date.today().isoformat())
  category = data.get("category", "ADMIN_OPERATIONAL").strip().upper()
  payee = data.get("payee", "").strip()
  payment_method = data.get("payment_method", "CASH").strip().upper()
  voucher_ref = data.get("voucher_ref", "").strip()
  approved_by = data.get("approved_by", "").strip()
  notes = data.get("notes", "").strip()

  try:
    amount = float(data.get("amount", 0))
  except (ValueError, TypeError):
    return jsonify({"success": False, "error": "Invalid amount."}), 400

  if not payee or amount <= 0:
    return (
        jsonify({
            "success": False,
            "error": "Payee name and a valid positive amount are required.",
        }),
        400,
    )

  conn = get_db()
  conn.execute(
      """
        INSERT INTO expenses 
        (church_id, recorded_by_user_id, expense_date, category, amount, payment_method, payee, voucher_ref, approved_by, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
      (
          church_id,
          user_id,
          expense_date_input,
          category,
          amount,
          payment_method,
          payee,
          voucher_ref,
          approved_by,
          notes,
      ),
  )
  conn.commit()

  return jsonify({"success": True})


@app.route("/treasurer/reconcile-batch", methods=["POST"])
@login_required
@subscription_check
def reconcile_batch():
  data = request.get_json() or {}
  church_id = session.get("church_id")
  user_id = session.get("user_id")
  service_date_input = data.get("service_date")
  bank_slip_ref = data.get("bank_slip_ref", "").strip()

  if not service_date_input:
    return jsonify({"success": False, "error": "Service date missing."}), 400

  now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  conn = get_db()
  conn.execute(
      """
        UPDATE giving_records
        SET batch_status = 'LOCKED',
            reconciled_by_user_id = ?,
            reconciled_at = ?,
            bank_slip_ref = ?
        WHERE church_id = ? AND service_date = ? AND batch_status != 'LOCKED'
        """,
      (user_id, now, bank_slip_ref, church_id, service_date_input),
  )
  conn.commit()

  return jsonify({"success": True})


# -----------------------------------------------------------------------------
# 3. PASTOR MODULE
# -----------------------------------------------------------------------------
@app.route("/pastor/dashboard")
@login_required
@subscription_check
def pastor_dashboard():
  church_id = session.get("church_id")
  conn = get_db()

  fund_summaries = conn.execute(
      """
        SELECT category, SUM(amount) as total_amount, COUNT(id) as transaction_count
        FROM giving_records
        WHERE church_id = ?
        GROUP BY category
        ORDER BY total_amount DESC
        """,
      (church_id,),
  ).fetchall()

  expense_summaries = conn.execute(
      """
        SELECT category, SUM(amount) as total_amount, COUNT(id) as transaction_count
        FROM expenses
        WHERE church_id = ?
        GROUP BY category
        ORDER BY total_amount DESC
        """,
      (church_id,),
  ).fetchall()

  total_inflow = sum(float(r["total_amount"] or 0) for r in fund_summaries)
  total_outflow = sum(float(r["total_amount"] or 0) for r in expense_summaries)
  net_position = total_inflow - total_outflow

  return render_template(
      "pastor_dashboard.html",
      fund_summaries=fund_summaries,
      expense_summaries=expense_summaries,
      total_inflow=total_inflow,
      total_outflow=total_outflow,
      net_position=net_position,
  )


# -----------------------------------------------------------------------------
# BILLING & SUBSCRIPTION MANAGEMENT
# -----------------------------------------------------------------------------
@app.route("/billing", methods=["GET", "POST"])
@login_required
def billing():
  church_id = session.get("church_id")
  conn = get_db()

  if request.method == "POST":
    plan_tier = request.form.get("plan_tier", "STANDARD")
    cycle = request.form.get("billing_cycle", "MONTHLY")
    mpesa_code = request.form.get("mpesa_code", "").strip().upper()

    days_to_add = 365 if cycle == "ANNUAL" else 30
    new_expiry = (date.today() + timedelta(days=days_to_add)).isoformat()

    conn.execute(
        """
            INSERT INTO church_subscriptions 
            (church_id, plan_tier, billing_cycle, is_trial, expires_at, status)
            VALUES (?, ?, ?, 0, ?, 'ACTIVE')
            """,
        (church_id, plan_tier, cycle, new_expiry),
    )
    conn.commit()

    flash(
        f"Subscription activated! Reference {mpesa_code or 'MANUAL'}. Valid"
        f" until {new_expiry}.",
        "success",
    )
    return redirect(url_for("role_dispatcher"))

  sub = conn.execute(
      """
        SELECT * FROM church_subscriptions
        WHERE church_id = ?
        ORDER BY id DESC LIMIT 1
        """,
      (church_id,),
  ).fetchone()

  return render_template("billing.html", subscription=sub)


# -----------------------------------------------------------------------------
# DARAJA M-PESA API INTEGRATION (OFFERINGS & SUBSCRIPTIONS)
# -----------------------------------------------------------------------------
def sanitize_phone_number(phone):
  """Sanitizes user input phone numbers to 2547XXXXXXXX or 2541XXXXXXXX format."""
  phone = str(phone).strip().replace(" ", "").replace("+", "")
  if phone.startswith("0"):
    return "254" + phone[1:]
  elif phone.startswith("7") or phone.startswith("1"):
    return "254" + phone
  return phone


@app.route("/api/offering/stk-push", methods=["POST"])
def initiate_offering_stk():
  """Initiates an STK push for church giving (Tithe, Sunday Basket, Thanksgiving, etc.)."""
  data = request.get_json() or {}
  raw_phone = data.get("phone", "")
  category = data.get("category", "NORMAL_OFFERING").strip().upper()
  service_type = data.get("service_type", "FIRST_SERVICE").strip().upper()
  notes = data.get("notes", "").strip()

  church_id = session.get("church_id") or data.get("church_id")
  user_id = session.get("user_id")

  if not church_id:
    return (
        jsonify(
            {"success": False, "error": "Church identification is missing."}
        ),
        400,
    )

  try:
    amount = int(float(data.get("amount", 0)))
  except (ValueError, TypeError):
    return (
        jsonify(
            {"success": False, "error": "Please provide a valid numeric amount."}
        ),
        400,
    )

  if not raw_phone or amount <= 0:
    return (
        jsonify({
            "success": False,
            "error": "Valid phone number and amount are required.",
        }),
        400,
    )

  phone = sanitize_phone_number(raw_phone)
  account_ref = category[:12]

  success, res = trigger_stk_push(phone, amount, account_ref)

  if success and res.get("ResponseCode") == "0":
    checkout_id = res.get("CheckoutRequestID")

    conn = get_db()
    conn.execute(
        """
            INSERT INTO mpesa_stk_requests 
            (checkout_request_id, church_id, user_id, phone_number, amount, category, service_type, notes, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
            """,
        (
            checkout_id,
            church_id,
            user_id,
            phone,
            amount,
            category,
            service_type,
            notes,
        ),
    )
    conn.commit()

    return jsonify({
        "success": True,
        "message": (
            "PIN prompt dispatched to handset. Enter your M-Pesa PIN to complete"
            " offering."
        ),
        "checkout_id": checkout_id,
    })

  return (
      jsonify({
          "success": False,
          "error": res.get(
              "errorMessage",
              "Failed to initiate M-Pesa prompt. Please verify phone number and"
              " retry.",
          ),
      }),
      500,
  )


@app.route("/api/offering/check-status/<checkout_id>")
def check_offering_status(checkout_id):
  """Enables frontend JavaScript to poll transaction status after triggering an STK push."""
  conn = get_db()
  row = conn.execute(
      "SELECT status FROM mpesa_stk_requests WHERE checkout_request_id = ?",
      (checkout_id,),
  ).fetchone()

  if not row:
    return jsonify({"status": "NOT_FOUND"}), 404

  return jsonify({"status": row["status"]})


@app.route("/api/stk-push", methods=["POST"])
@login_required
def initiate_subscription_stk():
  """Initiates an STK push for SaaS administrative subscriptions."""
  data = request.get_json() or {}
  phone = data.get("phone", "")
  cycle = data.get("billing_cycle", "MONTHLY")

  amount = 15000 if cycle == "ANNUAL" else 1500
  church_id = session.get("church_id")

  if not phone:
    return (
        jsonify({"success": False, "error": "Phone number is required."}),
        400,
    )

  clean_phone = sanitize_phone_number(phone)
  account_ref = f"CH-{church_id}"
  success, res = trigger_stk_push(clean_phone, amount, account_ref)

  if success and res.get("ResponseCode") == "0":
    return jsonify({
        "success": True,
        "message": (
            "PIN prompt dispatched to handset. Enter your M-Pesa PIN to complete"
            " payment."
        ),
        "checkout_id": res.get("CheckoutRequestID"),
    })

  return (
      jsonify({
          "success": False,
          "error": res.get(
              "errorMessage",
              "Failed to initiate M-Pesa prompt. Try manual payment.",
          ),
      }),
      500,
  )


@app.route("/api/v1/payment/callback", methods=["POST"])
def mpesa_callback():
  """Receives and processes instant payment notifications from Daraja."""
  payload = request.get_json() or {}
  try:
    body = payload.get("Body", {}).get("stkCallback", {})
    result_code = body.get("ResultCode")
    checkout_id = body.get("CheckoutRequestID")
    result_desc = body.get("ResultDesc")

    conn = get_db()

    # 1. Check if checkout matches a church offering
    stk_request = conn.execute(
        "SELECT * FROM mpesa_stk_requests WHERE checkout_request_id = ?",
        (checkout_id,),
    ).fetchone()

    if stk_request:
      if result_code == 0:
        metadata = body.get("CallbackMetadata", {}).get("Item", [])
        receipt_no = next(
            (
                i.get("Value")
                for i in metadata
                if i.get("Name") == "MpesaReceiptNumber"
            ),
            "MPESA_AUTO",
        )
        amount_paid = float(
            next(
                (i.get("Value") for i in metadata if i.get("Name") == "Amount"),
                stk_request["amount"],
            )
        )
        today_str = date.today().isoformat()

        # Insert into giving_records so it immediately updates dashboards
        conn.execute(
            """
                    INSERT INTO giving_records 
                    (church_id, recorded_by_user_id, service_date, service_type, category, 
                     payment_method, reference_code, amount, notes, batch_status)
                    VALUES (?, ?, ?, ?, ?, 'MPESA', ?, ?, ?, 'PENDING')
                    """,
            (
                stk_request["church_id"],
                stk_request["user_id"],
                today_str,
                stk_request["service_type"],
                stk_request["category"],
                receipt_no,
                amount_paid,
                f"M-Pesa STK: {receipt_no} | Phone:"
                f" {stk_request['phone_number']}. Notes:"
                f" {stk_request['notes'] or ''}",
            ),
        )

        # Update STK request status to COMPLETED
        conn.execute(
            "UPDATE mpesa_stk_requests SET status = 'COMPLETED' WHERE id = ?",
            (stk_request["id"],),
        )
        conn.commit()
        print(
            f">> [OFFERING RECORDED]: Receipt {receipt_no}, KES {amount_paid}"
            f" logged to church {stk_request['church_id']}."
        )
      else:
        conn.execute(
            "UPDATE mpesa_stk_requests SET status = 'FAILED' WHERE id = ?",
            (stk_request["id"],),
        )
        conn.commit()
        print(
            f">> [OFFERING CANCELLED/FAILED]: Checkout {checkout_id}. Reason:"
            f" {result_desc} (Code: {result_code})"
        )

    else:
      # 2. Otherwise handle SaaS subscription payment callback
      if result_code == 0:
        metadata = body.get("CallbackMetadata", {}).get("Item", [])
        receipt = next(
            (
                i.get("Value")
                for i in metadata
                if i.get("Name") == "MpesaReceiptNumber"
            ),
            None,
        )
        amount = float(
            next(
                (i.get("Value") for i in metadata if i.get("Name") == "Amount"),
                0,
            )
        )

        days_to_add = 365 if amount >= 15000 else 30
        cycle = "ANNUAL" if amount >= 15000 else "MONTHLY"
        tier = "PREMIUM" if amount >= 15000 else "STANDARD"
        new_expiry = (date.today() + timedelta(days=days_to_add)).isoformat()

        print(
            ">> [SUBSCRIPTION PAYMENT CONFIRMED]: Receipt"
            f" {receipt}, KES {amount}, Plan: {tier}/{cycle}, Expiry:"
            f" {new_expiry}"
        )

  except Exception as e:
    print(f"[CALLBACK PROCESSING ERROR]: {repr(e)}")

  # Always return 200 HTTP response to Safaricom
  return jsonify({"ResultCode": 0, "ResultDesc": "Success"}), 200


# -----------------------------------------------------------------------------
# APPLICATION ENTRY POINT
# -----------------------------------------------------------------------------
if __name__ == "__main__":
  init_db()
  # Uses the PORT environment variable provided by Render or defaults to 5000 locally
  port = int(os.environ.get("PORT", 5000))
  app.run(host="0.0.0.0", port=port, debug=True)