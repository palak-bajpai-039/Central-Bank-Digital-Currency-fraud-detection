"""
UPI-style Fraud Detection Dataset Generator
=============================================
Generates synthetic UPI transactions (VPA-based) with realistic transaction
types and fraud patterns modeled after real UPI fraud tactics: collect
request scams, QR code tampering, new-device/new-location transfers, and
mule-account (young wallet) behavior.

Run: python3 generate_dataset.py
Output: ../data/upi_transactions.csv
"""

import numpy as np
import pandas as pd
import random
import string
import ipaddress
from datetime import datetime, timedelta

SEED = 42
N_TRANSACTIONS = 50_000
N_DAYS = 30
FRAUD_RATE_TARGET = 0.0025

random.seed(SEED)
np.random.seed(SEED)

TXN_TYPES = ["P2P_TRANSFER", "P2M_PAYMENT", "COLLECT_REQUEST", "QR_SCAN", "BILL_PAYMENT", "RECHARGE"]
TXN_TYPE_WEIGHTS = [0.28, 0.24, 0.10, 0.18, 0.12, 0.08]

HANDLES = ["okhdfcbank", "paytm", "ybl", "okicici", "oksbi", "okaxis"]
CITIES = [
    "Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Kolkata",
    "Pune", "Ahmedabad", "Jaipur", "Lucknow", "Kanpur", "Nagpur",
    "Surat", "Indore", "Bhopal", "Patna", "Chandigarh", "Kochi",
]
MERCHANT_CATEGORIES = [
    "Grocery", "Electronics", "Fuel", "Utility_Bill", "E-commerce",
    "Restaurant", "Travel", "Healthcare", "Education", "Government_Payment",
]

N_USERS = 8_000
N_MERCHANTS = 600
FIRST_NAMES = ["aarav","vivaan","aditya","rohan","kabir","ishaan","aryan","dev",
               "ananya","diya","isha","riya","saanvi","meera","tanvi","navya"]


def make_vpa(is_merchant=False):
    name = random.choice(FIRST_NAMES) + str(random.randint(1, 999))
    handle = random.choice(HANDLES) if not is_merchant else "paytm"
    prefix = "merchant" if is_merchant else name
    return f"{prefix}@{handle}"


def random_ip():
    return str(ipaddress.IPv4Address(random.randint(0x0A000000, 0xDFFFFFFF)))


def make_device_id():
    return "DEV-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


# --- User / merchant pools with fixed attributes -----------------------------
user_vpas = list({make_vpa() for _ in range(N_USERS)})
merchant_vpas = list({make_vpa(is_merchant=True) for _ in range(N_MERCHANTS)})

vpa_home_city = {v: random.choice(CITIES) for v in user_vpas + merchant_vpas}
vpa_created_offset = {v: -random.randint(1, 1500) for v in user_vpas + merchant_vpas}
vpa_device = {v: make_device_id() for v in user_vpas}
vpa_ip = {v: random_ip() for v in user_vpas}

sim_start = datetime(2026, 1, 1)

# --- Generate transactions ----------------------------------------------------
rows = []
n_fraud_target = int(N_TRANSACTIONS * FRAUD_RATE_TARGET)
fraud_indices = set(np.random.choice(N_TRANSACTIONS, size=n_fraud_target, replace=False))

FRAUD_SUBTYPES = ["collect_request_scam", "qr_tampering", "mule_transfer", "unusual_high_value"]

for i in range(N_TRANSACTIONS):
    is_fraud = i in fraud_indices
    hour_step = random.randint(1, N_DAYS * 24)
    fraud_subtype = None

    if is_fraud:
        fraud_subtype = random.choice(FRAUD_SUBTYPES)
        sender = random.choice(user_vpas)
        if fraud_subtype == "collect_request_scam":
            txn_type = "COLLECT_REQUEST"
            amount = round(np.random.lognormal(mean=9.5, sigma=0.8), 2)
            receiver = random.choice(user_vpas)
        elif fraud_subtype == "qr_tampering":
            txn_type = "QR_SCAN"
            amount = round(np.random.lognormal(mean=9.0, sigma=0.7), 2)
            receiver = random.choice(user_vpas)  # tampered QR redirects to unexpected VPA
        elif fraud_subtype == "mule_transfer":
            txn_type = "P2P_TRANSFER"
            amount = round(np.random.lognormal(mean=10.5, sigma=1.0), 2)
            receiver = random.choice(user_vpas)
        else:  # unusual_high_value
            txn_type = random.choice(["P2P_TRANSFER", "P2M_PAYMENT"])
            amount = round(np.random.lognormal(mean=11.5, sigma=0.9), 2)
            receiver = random.choice(user_vpas + merchant_vpas)
    else:
        txn_type = random.choices(TXN_TYPES, weights=TXN_TYPE_WEIGHTS, k=1)[0]
        amount = round(np.random.lognormal(mean=7.8, sigma=1.2), 2)
        sender = random.choice(user_vpas)
        if txn_type in ("P2M_PAYMENT", "QR_SCAN", "BILL_PAYMENT", "RECHARGE"):
            receiver = random.choice(merchant_vpas)
        else:
            receiver = random.choice(user_vpas)

    rows.append({
        "hour_step": hour_step,
        "type": txn_type,
        "amount": amount,
        "sender_vpa": sender,
        "receiver_vpa": receiver,
        "is_fraud": int(is_fraud),
        "fraud_subtype": fraud_subtype,
    })

df = pd.DataFrame(rows).sort_values("hour_step").reset_index(drop=True)
df["timestamp"] = df["hour_step"].apply(lambda h: sim_start + timedelta(hours=int(h)))


def device_for(sender, fraud):
    if sender not in vpa_device:
        return make_device_id()
    if fraud and random.random() < 0.7:
        return make_device_id()
    return vpa_device[sender]


def ip_for(sender, fraud):
    if sender not in vpa_ip:
        return random_ip()
    if fraud and random.random() < 0.6:
        return random_ip()
    return vpa_ip[sender]


def location_for(sender, fraud):
    home = vpa_home_city.get(sender, random.choice(CITIES))
    if fraud and random.random() < 0.5:
        return random.choice([c for c in CITIES if c != home])
    return home


def wallet_age_days(sender, ts):
    offset = vpa_created_offset.get(sender, -random.randint(1, 1500))
    created = sim_start + timedelta(days=offset)
    return max((ts - created).days, 0)


df["device_id"] = [device_for(s, f) for s, f in zip(df["sender_vpa"], df["is_fraud"])]
df["ip_address"] = [ip_for(s, f) for s, f in zip(df["sender_vpa"], df["is_fraud"])]
df["location"] = [location_for(s, f) for s, f in zip(df["sender_vpa"], df["is_fraud"])]
df["wallet_age_days"] = [wallet_age_days(s, t) for s, t in zip(df["sender_vpa"], df["timestamp"])]
df["merchant_category"] = [
    random.choice(MERCHANT_CATEGORIES) if r in merchant_vpas else "N/A"
    for r in df["receiver_vpa"]
]

young_mask = (df["is_fraud"] == 1) & (np.random.rand(len(df)) < 0.4)
df.loc[young_mask, "wallet_age_days"] = np.random.randint(0, 3, size=young_mask.sum())

final_cols = [
    "timestamp", "hour_step", "type", "sender_vpa", "receiver_vpa", "amount",
    "device_id", "location", "ip_address", "wallet_age_days", "merchant_category",
    "is_fraud", "fraud_subtype",
]
df = df[final_cols]

df.to_csv("../data/upi_transactions.csv", index=False)

print("Total rows:", len(df))
print("Fraud rows:", df["is_fraud"].sum(), f"({df['is_fraud'].mean()*100:.3f}%)")
print(df["fraud_subtype"].value_counts(dropna=True))
print(df.head(5).to_string())
