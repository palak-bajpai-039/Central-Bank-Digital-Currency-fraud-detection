"""
CBDC Fraud Detection Backend
===============================
Modeled on UPI-style transaction patterns since India's Digital Rupee (e₹)
is designed to be interoperable with UPI's QR/wallet infrastructure, and
real CBDC transaction data isn't publicly available (still a limited pilot).

FastAPI service exposing:
  - POST /transaction        -> submit a transaction, get real-time risk decision
  - GET  /transactions        -> list recent transactions
  - GET  /alerts               -> list held/flagged transactions
  - GET  /wallet/{vpa}         -> wallet balance + history
  - GET  /stats                -> dashboard summary metrics
  - WS   /ws/live               -> live feed of new transactions/alerts
  - POST /simulate/start | /simulate/stop -> background transaction simulator

Run (from inside the backend/ folder — do NOT run this file with plain
`python main.py`, it must be started through uvicorn):
    cd backend
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000

Docs: http://localhost:8000/docs
"""

import asyncio
import os
import random
import smtplib
import sqlite3
import string
import ipaddress
from contextlib import contextmanager
from datetime import datetime
from email.mime.text import MIMEText
from typing import Optional, List

import joblib
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, EmailStr

from auth import (
    hash_password, verify_password, create_access_token, decode_access_token,
    get_current_user, generate_api_key, hash_api_key,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "upi_fraud.db")
MODELS_DIR = os.path.join(BASE_DIR, "..", "models")

app = FastAPI(title="CBDC Fraud Detection API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Load trained models at startup (once — not per request)
# ---------------------------------------------------------------------------
rf_model = joblib.load(f"{MODELS_DIR}/random_forest.joblib")
iso_model = joblib.load(f"{MODELS_DIR}/isolation_forest.joblib")
type_encoder = joblib.load(f"{MODELS_DIR}/type_encoder.joblib")
lookup = joblib.load(f"{MODELS_DIR}/feature_lookup.joblib")

RF_WEIGHT = lookup["rf_weight"]
IF_WEIGHT = lookup["if_weight"]
ISO_MIN = lookup["iso_score_min"]
ISO_MAX = lookup["iso_score_max"]
KNOWN_TYPES = set(type_encoder.classes_)

RISK_THRESHOLD = 0.5

# ---------------------------------------------------------------------------
# Email alerts (optional) — set these environment variables to get a real
# email the instant a transaction is flagged. Works with Gmail using an
# "App Password": https://myaccount.google.com/apppasswords
#   SMTP_HOST=smtp.gmail.com  SMTP_PORT=587
#   SMTP_USER=you@gmail.com  SMTP_PASS=app-password
#   ALERT_EMAIL_TO=you@gmail.com
# If unset, email alerts are silently skipped.
# ---------------------------------------------------------------------------
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
ALERT_EMAIL_TO = os.environ.get("ALERT_EMAIL_TO", "")


def send_email_alert(txn: dict):
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, ALERT_EMAIL_TO]):
        return
    try:
        body = (
            f"Transaction flagged for review\n\n"
            f"From: {txn['sender_vpa']}\nTo: {txn['receiver_vpa']}\n"
            f"Amount: Rs.{txn['amount']:,.2f}\nType: {txn['type']}\n"
            f"Risk score: {txn['risk_score']*100:.0f}%\n"
            f"Reasons: {', '.join(txn['reasons'])}\nTransaction ID: {txn['id']}\n"
        )
        msg = MIMEText(body)
        msg["Subject"] = f"[CBDC Fraud Alert] Transaction #{txn['id']} held for review"
        msg["From"] = SMTP_USER
        msg["To"] = ALERT_EMAIL_TO
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
    except Exception as e:
        print(f"Email alert failed (non-fatal): {e}")

# ---------------------------------------------------------------------------
# In-memory "known wallet" state — tracks each sender's usual device/location
# so we can compute is_new_device / is_new_location for LIVE transactions,
# same way the training script computed it from historical data.
# ---------------------------------------------------------------------------
wallet_known_device = {}
wallet_known_location = {}
wallet_txn_count = {}
wallet_created_at = {}
wallet_balance = {}

DEMO_HANDLES = ["okhdfcbank", "paytm", "ybl", "okicici", "oksbi", "okaxis"]
DEMO_CITIES = ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Kolkata", "Pune"]
DEMO_TYPES = ["P2P_TRANSFER", "P2M_PAYMENT", "COLLECT_REQUEST", "QR_SCAN", "BILL_PAYMENT", "RECHARGE"]


def seed_demo_wallets(n=20):
    names = ["aarav", "vivaan", "aditya", "rohan", "kabir", "ishaan", "ananya", "diya", "isha", "riya"]
    vpas = []
    for name in names:
        for handle in random.sample(DEMO_HANDLES, 2):
            vpas.append(f"{name}{random.randint(1,99)}@{handle}")
    for v in vpas[:n]:
        wallet_known_device[v] = f"DEV-{''.join(random.choices(string.ascii_uppercase+string.digits,k=8))}"
        wallet_known_location[v] = random.choice(DEMO_CITIES)
        wallet_txn_count[v] = random.randint(20, 400)
        wallet_created_at[v] = datetime.utcnow()
        wallet_balance[v] = round(random.uniform(500, 50000), 2)
    return vpas


DEMO_VPAS = seed_demo_wallets()

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS organizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id INTEGER NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT,
                FOREIGN KEY (org_id) REFERENCES organizations(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id INTEGER NOT NULL,
                key_prefix TEXT NOT NULL,
                key_hash TEXT UNIQUE NOT NULL,
                created_at TEXT,
                revoked INTEGER DEFAULT 0,
                last_used_at TEXT,
                FOREIGN KEY (org_id) REFERENCES organizations(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id INTEGER NOT NULL UNIQUE,
                vpa TEXT UNIQUE NOT NULL,
                balance REAL DEFAULT 10000,
                created_at TEXT,
                FOREIGN KEY (org_id) REFERENCES organizations(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id INTEGER,
                timestamp TEXT,
                type TEXT,
                sender_vpa TEXT,
                receiver_vpa TEXT,
                amount REAL,
                device_id TEXT,
                location TEXT,
                ip_address TEXT,
                risk_score REAL,
                status TEXT,
                reasons TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER,
                timestamp TEXT,
                risk_score REAL,
                reasons TEXT,
                reviewed INTEGER DEFAULT 0
            )
        """)

        # Seed a "demo" organization + API key so the existing background
        # simulator and demo dashboard keep working without requiring signup.
        existing = conn.execute(
            "SELECT id FROM organizations WHERE name = 'Demo Org'"
        ).fetchone()
        if not existing:
            cur = conn.execute(
                "INSERT INTO organizations (name, created_at) VALUES (?, ?)",
                ("Demo Org", datetime.utcnow().isoformat()),
            )
            demo_org_id = cur.lastrowid
            demo_key_hash = hash_api_key("sk_demo_public_key_for_testing_only")
            conn.execute(
                """INSERT INTO api_keys (org_id, key_prefix, key_hash, created_at)
                   VALUES (?, ?, ?, ?)""",
                (demo_org_id, "sk_demo_pub", demo_key_hash, datetime.utcnow().isoformat()),
            )


init_db()

with get_db() as _conn:
    DEMO_ORG_ID = _conn.execute(
        "SELECT id FROM organizations WHERE name = 'Demo Org'"
    ).fetchone()["id"]

# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------
class TransactionIn(BaseModel):
    sender_vpa: str = Field(..., examples=["aarav12@paytm"])
    receiver_vpa: str = Field(..., examples=["ananya5@ybl"])
    amount: float = Field(..., gt=0)
    type: str = Field(..., examples=DEMO_TYPES)
    device_id: Optional[str] = None
    location: Optional[str] = None
    ip_address: Optional[str] = None


class TransactionOut(BaseModel):
    status: str
    risk_score: float
    reasons: List[str]
    transaction_id: int


class SignupIn(BaseModel):
    org_name: str = Field(..., examples=["Acme Payments"])
    email: EmailStr
    password: str = Field(..., min_length=8)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ApiKeyOut(BaseModel):
    id: int
    key_prefix: str
    created_at: str
    revoked: bool
    last_used_at: Optional[str] = None


class NewApiKeyOut(BaseModel):
    api_key: str
    key_prefix: str
    warning: str = "Save this key now — it will not be shown again."


# ---------------------------------------------------------------------------
# Real-time risk scoring — this is the core of the "fraud check API"
# ---------------------------------------------------------------------------
def score_transaction(txn: TransactionIn):
    sender = txn.sender_vpa

    device = txn.device_id or wallet_known_device.get(sender) or "DEV-UNKNOWN"
    location = txn.location or wallet_known_location.get(sender) or random.choice(DEMO_CITIES)
    ip_address = txn.ip_address or str(ipaddress.IPv4Address(random.randint(0x0A000000, 0xDFFFFFFF)))

    known_device = wallet_known_device.get(sender)
    known_location = wallet_known_location.get(sender)
    is_new_device = int(known_device is not None and device != known_device)
    is_new_location = int(known_location is not None and location != known_location)

    created = wallet_created_at.get(sender, datetime.utcnow())
    wallet_age_days = max((datetime.utcnow() - created).days, 0)
    sender_txn_count = wallet_txn_count.get(sender, 1)
    hour_of_day = datetime.utcnow().hour

    txn_type = txn.type if txn.type in KNOWN_TYPES else DEMO_TYPES[0]
    type_encoded = int(type_encoder.transform([txn_type])[0])

    features = np.array([[
        txn.amount, hour_of_day, wallet_age_days, is_new_device,
        is_new_location, sender_txn_count, type_encoded,
    ]])

    rf_proba = float(rf_model.predict_proba(features)[0][1])
    iso_raw = float(iso_model.decision_function(features)[0])
    iso_anomaly = (ISO_MAX - iso_raw) / (ISO_MAX - ISO_MIN + 1e-9)
    iso_anomaly = min(max(iso_anomaly, 0.0), 1.0)

    final_risk = RF_WEIGHT * rf_proba + IF_WEIGHT * iso_anomaly

    reasons = []
    if is_new_device:
        reasons.append("Unfamiliar device")
    if is_new_location:
        reasons.append("Unfamiliar location")
    if wallet_age_days <= 2:
        reasons.append("Very new wallet")
    if txn.amount > 50000:
        reasons.append("Unusually large amount")
    if rf_proba > 0.5:
        reasons.append("Matches known fraud pattern")
    if iso_anomaly > 0.7:
        reasons.append("Statistically anomalous transaction")
    if not reasons:
        reasons.append("No risk signals detected")

    # Update wallet's "known" state after scoring (so legit repeat use adapts)
    if sender not in wallet_known_device:
        wallet_known_device[sender] = device
    if sender not in wallet_known_location:
        wallet_known_location[sender] = location
    wallet_txn_count[sender] = wallet_txn_count.get(sender, 0) + 1
    wallet_created_at.setdefault(sender, datetime.utcnow())

    return final_risk, reasons, device, location, ip_address


connected_clients: List[WebSocket] = []


async def broadcast(message: dict):
    dead = []
    for ws in connected_clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connected_clients.remove(ws)


# ---------------------------------------------------------------------------
# API key verification — protects the fraud-check endpoint. Every paying
# customer calls /transaction with their own key in the X-API-Key header;
# this resolves that key to an organization and rejects the request
# (401) if the key is missing, unknown, or revoked.
# ---------------------------------------------------------------------------
def get_org_from_api_key(x_api_key: Optional[str] = Header(None)) -> int:
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing X-API-Key header. Sign up at /auth/signup to get a key.",
        )
    key_hash = hash_api_key(x_api_key)
    with get_db() as conn:
        row = conn.execute(
            "SELECT org_id, revoked FROM api_keys WHERE key_hash = ?", (key_hash,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid API key")
        if row["revoked"]:
            raise HTTPException(status_code=401, detail="This API key has been revoked")
        conn.execute(
            "UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?",
            (datetime.utcnow().isoformat(), key_hash),
        )
    return row["org_id"]


def _org_id_from_jwt(authorization: Optional[str]) -> Optional[int]:
    """Returns org_id if a valid JWT Bearer token is present, else None
    (does not raise) — used to build both strict and optional dependencies."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        payload = decode_access_token(authorization.removeprefix("Bearer ").strip())
    except HTTPException:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT org_id FROM users WHERE id = ?", (int(payload["sub"]),)
        ).fetchone()
    return row["org_id"] if row else None


def get_org_id_flexible(
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
) -> int:
    """For the paid /transaction endpoint: accepts EITHER a customer's
    API key (server-to-server integration) OR a logged-in user's JWT
    (the dashboard acting on their own behalf) — same pattern Stripe uses
    (API keys for integrations, session auth for the dashboard)."""
    org_id = _org_id_from_jwt(authorization)
    if org_id is not None:
        return org_id
    return get_org_from_api_key(x_api_key)


def get_org_id_optional(authorization: Optional[str] = Header(None)) -> int:
    """For read-only endpoints: scopes to the logged-in user's org if a
    JWT is present, otherwise falls back to the public Demo Org — this is
    what keeps the old anonymous demo dashboard working unauthenticated
    while the new per-customer dashboard sees only its own data."""
    org_id = _org_id_from_jwt(authorization)
    return org_id if org_id is not None else DEMO_ORG_ID


# ---------------------------------------------------------------------------
# Auth endpoints — signup/login for the dashboard, key management for
# programmatic API access.
# ---------------------------------------------------------------------------
@app.post("/auth/signup", response_model=NewApiKeyOut)
def signup(body: SignupIn):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?", (body.email,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="An account with this email already exists")

        cur = conn.execute(
            "INSERT INTO organizations (name, created_at) VALUES (?, ?)",
            (body.org_name, datetime.utcnow().isoformat()),
        )
        org_id = cur.lastrowid

        conn.execute(
            "INSERT INTO users (org_id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (org_id, body.email, hash_password(body.password), datetime.utcnow().isoformat()),
        )

        plaintext_key, key_prefix, key_hash = generate_api_key()
        conn.execute(
            "INSERT INTO api_keys (org_id, key_prefix, key_hash, created_at) VALUES (?, ?, ?, ?)",
            (org_id, key_prefix, key_hash, datetime.utcnow().isoformat()),
        )

        # Give the new org a real, persistent wallet to transact from —
        # slugified org name + random suffix to guarantee uniqueness.
        slug = "".join(c.lower() if c.isalnum() else "" for c in body.org_name)[:16] or "org"
        vpa = f"{slug}{random.randint(100,999)}@saasbank"
        conn.execute(
            "INSERT INTO wallets (org_id, vpa, balance, created_at) VALUES (?, ?, ?, ?)",
            (org_id, vpa, 10000.0, datetime.utcnow().isoformat()),
        )

    return NewApiKeyOut(api_key=plaintext_key, key_prefix=key_prefix)


@app.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn):
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?", (body.email,)
        ).fetchone()
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    token = create_access_token(user_id=user["id"], email=user["email"])
    return TokenOut(access_token=token)


@app.get("/auth/keys", response_model=List[ApiKeyOut])
def list_api_keys(current_user: dict = Depends(get_current_user)):
    with get_db() as conn:
        org_row = conn.execute(
            "SELECT org_id FROM users WHERE id = ?", (current_user["user_id"],)
        ).fetchone()
        keys = conn.execute(
            """SELECT id, key_prefix, created_at, revoked, last_used_at
               FROM api_keys WHERE org_id = ? ORDER BY id DESC""",
            (org_row["org_id"],),
        ).fetchall()
    return [
        ApiKeyOut(
            id=k["id"], key_prefix=k["key_prefix"], created_at=k["created_at"],
            revoked=bool(k["revoked"]), last_used_at=k["last_used_at"],
        )
        for k in keys
    ]


@app.post("/auth/keys", response_model=NewApiKeyOut)
def create_api_key(current_user: dict = Depends(get_current_user)):
    with get_db() as conn:
        org_row = conn.execute(
            "SELECT org_id FROM users WHERE id = ?", (current_user["user_id"],)
        ).fetchone()
        plaintext_key, key_prefix, key_hash = generate_api_key()
        conn.execute(
            "INSERT INTO api_keys (org_id, key_prefix, key_hash, created_at) VALUES (?, ?, ?, ?)",
            (org_row["org_id"], key_prefix, key_hash, datetime.utcnow().isoformat()),
        )
    return NewApiKeyOut(api_key=plaintext_key, key_prefix=key_prefix)


@app.delete("/auth/keys/{key_id}")
def revoke_api_key(key_id: int, current_user: dict = Depends(get_current_user)):
    with get_db() as conn:
        org_row = conn.execute(
            "SELECT org_id FROM users WHERE id = ?", (current_user["user_id"],)
        ).fetchone()
        result = conn.execute(
            "UPDATE api_keys SET revoked = 1 WHERE id = ? AND org_id = ?",
            (key_id, org_row["org_id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="API key not found")
    return {"status": "revoked"}


@app.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    """Everything the dashboard needs right after login: who you are,
    which org you belong to, and your org's own wallet."""
    with get_db() as conn:
        user_row = conn.execute(
            "SELECT id, email, org_id FROM users WHERE id = ?", (current_user["user_id"],)
        ).fetchone()
        org_row = conn.execute(
            "SELECT id, name FROM organizations WHERE id = ?", (user_row["org_id"],)
        ).fetchone()
        wallet_row = conn.execute(
            "SELECT vpa, balance FROM wallets WHERE org_id = ?", (user_row["org_id"],)
        ).fetchone()
    return {
        "email": user_row["email"],
        "org_id": org_row["id"],
        "org_name": org_row["name"],
        "wallet": {
            "vpa": wallet_row["vpa"] if wallet_row else None,
            "balance": round(wallet_row["balance"], 2) if wallet_row else None,
        },
    }


async def _process_transaction(txn: TransactionIn, org_id: int) -> TransactionOut:
    if txn.type not in DEMO_TYPES:
        raise HTTPException(400, f"type must be one of {DEMO_TYPES}")

    risk_score, reasons, device, location, ip_address = score_transaction(txn)
    status = "held_for_review" if risk_score >= RISK_THRESHOLD else "approved"
    now = datetime.utcnow().isoformat()

    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO transactions
               (org_id, timestamp, type, sender_vpa, receiver_vpa, amount, device_id,
                location, ip_address, risk_score, status, reasons)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (org_id, now, txn.type, txn.sender_vpa, txn.receiver_vpa, txn.amount,
             device, location, ip_address, risk_score, status, ", ".join(reasons)),
        )
        txn_id = cur.lastrowid
        if txn_id is None:
            raise RuntimeError("Failed to create transaction ID")

        if status == "approved":
            # Real signed-up orgs have a persistent row in `wallets`; demo
            # simulator wallets only exist in the in-memory dict. Update
            # whichever applies to the sender/receiver involved.
            with_wallet_row = conn.execute(
                "SELECT vpa FROM wallets WHERE vpa = ?", (txn.sender_vpa,)
            ).fetchone()
            if with_wallet_row:
                conn.execute(
                    "UPDATE wallets SET balance = balance - ? WHERE vpa = ?",
                    (txn.amount, txn.sender_vpa),
                )
            else:
                wallet_balance[txn.sender_vpa] = wallet_balance.get(txn.sender_vpa, 10000) - txn.amount

            receiver_wallet_row = conn.execute(
                "SELECT vpa FROM wallets WHERE vpa = ?", (txn.receiver_vpa,)
            ).fetchone()
            if receiver_wallet_row:
                conn.execute(
                    "UPDATE wallets SET balance = balance + ? WHERE vpa = ?",
                    (txn.amount, txn.receiver_vpa),
                )
            else:
                wallet_balance[txn.receiver_vpa] = wallet_balance.get(txn.receiver_vpa, 0) + txn.amount
        else:
            conn.execute(
                """INSERT INTO alerts (transaction_id, timestamp, risk_score, reasons)
                   VALUES (?,?,?,?)""",
                (txn_id, now, risk_score, ", ".join(reasons)),
            )

    payload = {
        "id": txn_id, "org_id": org_id, "timestamp": now, "type": txn.type,
        "sender_vpa": txn.sender_vpa, "receiver_vpa": txn.receiver_vpa,
        "amount": txn.amount, "risk_score": round(risk_score, 4),
        "status": status, "reasons": reasons,
    }
    await broadcast({"event": "transaction", "data": payload})

    if status == "held_for_review":
        send_email_alert(payload)

    return TransactionOut(status=status, risk_score=round(risk_score, 4), reasons=reasons, transaction_id=txn_id)


@app.post("/transaction", response_model=TransactionOut)
async def create_transaction(txn: TransactionIn, org_id: int = Depends(get_org_id_flexible)):
    """Score a transaction in real time. Accepts EITHER an X-API-Key header
    (for programmatic/server-to-server integration) OR a logged-in user's
    JWT Bearer token (for the dashboard acting on its own org's behalf)."""
    return await _process_transaction(txn, org_id)


@app.get("/transactions")
def list_transactions(limit: int = 50, org_id: int = Depends(get_org_id_optional)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE org_id = ? ORDER BY id DESC LIMIT ?",
            (org_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/alerts")
def list_alerts(limit: int = 50, org_id: int = Depends(get_org_id_optional)):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT alerts.*, transactions.sender_vpa, transactions.receiver_vpa,
                      transactions.amount, transactions.type
               FROM alerts JOIN transactions ON alerts.transaction_id = transactions.id
               WHERE transactions.org_id = ?
               ORDER BY alerts.id DESC LIMIT ?""",
            (org_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/wallet/{vpa}")
def wallet_detail(vpa: str):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM transactions WHERE sender_vpa = ? OR receiver_vpa = ?
               ORDER BY id DESC LIMIT 50""",
            (vpa, vpa),
        ).fetchall()
        wallet_row = conn.execute("SELECT balance FROM wallets WHERE vpa = ?", (vpa,)).fetchone()
    balance = wallet_row["balance"] if wallet_row else wallet_balance.get(vpa, 10000.0)
    return {
        "vpa": vpa,
        "balance": round(balance, 2),
        "wallet_age_days": max((datetime.utcnow() - wallet_created_at.get(vpa, datetime.utcnow())).days, 0),
        "transactions": [dict(r) for r in rows],
    }


@app.get("/wallets")
def list_wallets():
    return {"demo_wallets": DEMO_VPAS}


@app.get("/stats")
def stats(org_id: int = Depends(get_org_id_optional)):
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) c FROM transactions WHERE org_id = ?", (org_id,)
        ).fetchone()["c"]
        held = conn.execute(
            "SELECT COUNT(*) c FROM transactions WHERE org_id = ? AND status='held_for_review'",
            (org_id,),
        ).fetchone()["c"]
        avg_risk = conn.execute(
            "SELECT AVG(risk_score) a FROM transactions WHERE org_id = ?", (org_id,)
        ).fetchone()["a"] or 0
    return {
        "total_transactions": total,
        "held_for_review": held,
        "avg_risk_score": round(avg_risk, 4),
    }


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


# ---------------------------------------------------------------------------
# Background simulator — generates realistic background traffic so the
# dashboard isn't empty. Real user transactions (from the wallet frontend)
# hit the same /transaction endpoint above.
# ---------------------------------------------------------------------------
simulator_task = None
simulator_running = False


async def simulate_loop():
    global simulator_running
    while simulator_running:
        sender = random.choice(DEMO_VPAS)
        receiver = random.choice([v for v in DEMO_VPAS if v != sender])
        fraud_roll = random.random() < 0.02  # occasional injected suspicious txn for demo
        txn = TransactionIn(
            sender_vpa=sender,
            receiver_vpa=receiver,
            amount=round(random.uniform(50000, 150000), 2) if fraud_roll else round(random.uniform(50, 5000), 2),
            type=random.choice(DEMO_TYPES),
            device_id=("DEV-" + "".join(random.choices(string.ascii_uppercase+string.digits, k=8))) if fraud_roll else None,
            location=random.choice(DEMO_CITIES) if fraud_roll else None,
        )
        await _process_transaction(txn, DEMO_ORG_ID)
        await asyncio.sleep(2)


@app.post("/simulate/start")
async def simulate_start():
    global simulator_task, simulator_running
    if not simulator_running:
        simulator_running = True
        simulator_task = asyncio.create_task(simulate_loop())
    return {"status": "started"}


@app.post("/simulate/stop")
async def simulate_stop():
    global simulator_running
    simulator_running = False
    return {"status": "stopped"}


@app.get("/api")
def api_status():
    return {"message": "CBDC Fraud Detection API running. See /docs for endpoints."}


# ---------------------------------------------------------------------------
# Serve the dashboard frontend directly from this same server, so the app
# runs on a single origin (http://localhost:8000) with zero CORS/cross-port
# configuration needed. This must be the LAST route registered — FastAPI
# matches specific routes (like /api, /transaction, /docs) before falling
# through to this catch-all, so it won't shadow the API endpoints above.
# ---------------------------------------------------------------------------
# Legacy vanilla-JS demo dashboard — kept available as a platform-wide
# "admin/ops view" showing all activity across every org (useful for
# demonstrating the background simulator and cross-tenant volume).
LEGACY_FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")
app.mount("/legacy", StaticFiles(directory=LEGACY_FRONTEND_DIR, html=True), name="legacy_frontend")

# Primary experience: the React app. Serves built assets (JS/CSS) directly
# when the requested path matches a real file, and falls back to index.html
# for everything else — required for React Router's client-side routes
# (e.g. /dashboard, /api-keys) to work on a direct visit or page refresh,
# not just when navigated to from within the app.
WEBAPP_DIST_DIR = os.path.join(BASE_DIR, "..", "webapp", "dist")


@app.get("/{full_path:path}")
async def serve_webapp(full_path: str):
    candidate = os.path.join(WEBAPP_DIST_DIR, full_path)
    if full_path and os.path.isfile(candidate):
        return FileResponse(candidate)
    return FileResponse(os.path.join(WEBAPP_DIST_DIR, "index.html"))
