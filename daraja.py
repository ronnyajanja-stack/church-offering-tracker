import base64
from datetime import datetime
import os
import requests

DARAJA_ENV = os.environ.get("DARAJA_ENV", "sandbox")
CONSUMER_KEY = os.environ.get("DARAJA_CONSUMER_KEY", "").strip()
CONSUMER_SECRET = os.environ.get("DARAJA_CONSUMER_SECRET", "").strip()
SHORTCODE = os.environ.get("DARAJA_SHORTCODE", "174379").strip()
# Standard Daraja sandbox passkey fallback if not provided in .env
DEFAULT_SANDBOX_PASSKEY = (
    "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"
)
PASSKEY = os.environ.get("DARAJA_PASSKEY", DEFAULT_SANDBOX_PASSKEY).strip()

BASE_URL = (
    "https://sandbox.safaricom.co.ke"
    if DARAJA_ENV == "sandbox"
    else "https://api.safaricom.co.ke"
)


def get_callback_url():
  """Determines the active public callback URL for Safaricom webhooks."""
  if os.environ.get("DARAJA_CALLBACK_URL"):
    return os.environ.get("DARAJA_CALLBACK_URL").strip()

  base = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
  if base:
    return f"{base}/api/v1/payment/callback"

  # Fallback dummy URL to prevent Daraja request rejection during offline testing
  return "https://example.com/api/v1/payment/callback"


def get_access_token():
  """Generates an OAuth 2.0 Bearer Token from Daraja."""
  if not CONSUMER_KEY or not CONSUMER_SECRET:
    print("[DARAJA ERROR]: Missing CONSUMER_KEY or CONSUMER_SECRET in .env")
    return None

  url = f"{BASE_URL}/oauth/v1/generate?grant_type=client_credentials"
  try:
    auth_str = f"{CONSUMER_KEY}:{CONSUMER_SECRET}"
    encoded_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
    headers = {"Authorization": f"Basic {encoded_auth}"}

    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    return response.json().get("access_token")
  except Exception as e:
    print(f"[DARAJA TOKEN ERROR]: {e}")
    return None


def format_phone_number(phone):
  """Formats 07XXXXXXXX, 01XXXXXXXX, or +254...

  to 254XXXXXXXXX.
  """
  cleaned = str(phone).strip().replace("+", "").replace(" ", "")
  if cleaned.startswith("0"):
    cleaned = "254" + cleaned[1:]
  elif cleaned.startswith("7") or cleaned.startswith("1"):
    cleaned = "254" + cleaned
  return cleaned


def trigger_stk_push(
    phone_number,
    amount,
    account_reference="OFFERING",
    description="Church Giving",
):
  """Dispatches an STK Push prompt directly to the subscriber's phone.

  Returns: (success: bool, response_dict: dict)
  """
  token = get_access_token()
  if not token:
    return False, {"errorMessage": "Failed to generate Daraja access token"}

  formatted_phone = format_phone_number(phone_number)
  timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
  password_str = f"{SHORTCODE}{PASSKEY}{timestamp}"
  password = base64.b64encode(password_str.encode("utf-8")).decode("utf-8")
  callback_url = get_callback_url()

  payload = {
      "BusinessShortCode": SHORTCODE,
      "Password": password,
      "Timestamp": timestamp,
      "TransactionType": "CustomerPayBillOnline",
      "Amount": int(float(amount)),
      "PartyA": formatted_phone,
      "PartyB": SHORTCODE,
      "PhoneNumber": formatted_phone,
      "CallBackURL": callback_url,
      "AccountReference": str(account_reference)[:12],
      "TransactionDesc": str(description)[:12],
  }

  headers = {
      "Authorization": f"Bearer {token}",
      "Content-Type": "application/json",
  }

  try:
    endpoint = f"{BASE_URL}/mpesa/stkpush/v1/processrequest"
    resp = requests.post(endpoint, json=payload, headers=headers, timeout=25)
    res_data = resp.json()

    if resp.status_code == 200 and res_data.get("ResponseCode") == "0":
      return True, res_data

    error_msg = res_data.get(
        "errorMessage", res_data.get("ResponseDescription", "STK push failed")
    )
    return False, {"errorMessage": error_msg, "raw": res_data}
  except Exception as e:
    print(f"[DARAJA STK ERROR]: {e}")
    return False, {"errorMessage": str(e)}