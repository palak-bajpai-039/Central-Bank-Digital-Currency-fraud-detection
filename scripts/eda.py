"""
Phase 1.3 — Exploratory Data Analysis
=======================================
Generates the 4 chart types your roadmap calls for (pie, histogram, heatmap,
line graph) plus a printed summary of key findings.

Run: python3 eda.py
Output: PNG charts in ../eda_output/
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os

os.makedirs("../eda_output", exist_ok=True)
plt.rcParams.update({"figure.facecolor": "white", "axes.facecolor": "white"})

df = pd.read_csv("../data/upi_transactions.csv", parse_dates=["timestamp"])
df["hour_of_day"] = df["timestamp"].dt.hour
df["day"] = df["timestamp"].dt.day

print("=" * 60)
print("DATASET OVERVIEW")
print("=" * 60)
print(f"Total transactions: {len(df):,}")
print(f"Fraud transactions: {df['is_fraud'].sum()} ({df['is_fraud'].mean()*100:.3f}%)")
print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
print()

# ---------------------------------------------------------------------------
# 1. PIE CHART — Fraud distribution
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(6, 6))
counts = df["is_fraud"].value_counts()
ax.pie(
    counts, labels=["Legitimate", "Fraud"], autopct="%1.2f%%",
    colors=["#34d399", "#f87171"], startangle=90,
    textprops={"fontsize": 12},
)
ax.set_title("Transaction Fraud Distribution", fontsize=14, fontweight="bold")
plt.tight_layout()
plt.savefig("../eda_output/1_fraud_distribution_pie.png", dpi=120)
plt.close()

# ---------------------------------------------------------------------------
# 2. HISTOGRAM — Amount distribution, fraud vs legit (log scale since amounts skew)
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 5))
legit_amt = df[df["is_fraud"] == 0]["amount"]
fraud_amt = df[df["is_fraud"] == 1]["amount"]
bins = np.logspace(np.log10(max(df["amount"].min(), 1)), np.log10(df["amount"].max()), 40)
ax.hist(legit_amt, bins=bins, alpha=0.6, label="Legitimate", color="#34d399")
ax.hist(fraud_amt, bins=bins, alpha=0.7, label="Fraud", color="#f87171")
ax.set_xscale("log")
ax.set_xlabel("Transaction amount (₹, log scale)")
ax.set_ylabel("Count")
ax.set_title("Transaction Amount Distribution: Fraud vs Legitimate", fontsize=13, fontweight="bold")
ax.legend()
plt.tight_layout()
plt.savefig("../eda_output/2_amount_histogram.png", dpi=120)
plt.close()

# ---------------------------------------------------------------------------
# 3. HEATMAP — Fraud rate by hour of day x transaction type
# ---------------------------------------------------------------------------
pivot = df.pivot_table(values="is_fraud", index="type", columns="hour_of_day", aggfunc="mean")
fig, ax = plt.subplots(figsize=(12, 4))
im = ax.imshow(pivot.values, aspect="auto", cmap="Reds")
ax.set_xticks(range(len(pivot.columns)))
ax.set_xticklabels(pivot.columns, fontsize=8)
ax.set_yticks(range(len(pivot.index)))
ax.set_yticklabels(pivot.index, fontsize=9)
ax.set_xlabel("Hour of day")
ax.set_title("Fraud Rate Heatmap: Transaction Type vs Hour of Day", fontsize=13, fontweight="bold")
plt.colorbar(im, ax=ax, label="Fraud rate")
plt.tight_layout()
plt.savefig("../eda_output/3_fraud_heatmap.png", dpi=120)
plt.close()

# ---------------------------------------------------------------------------
# 4. LINE GRAPH — Transaction frequency over the 30-day simulation
# ---------------------------------------------------------------------------
daily = df.groupby(df["timestamp"].dt.date).agg(
    total=("is_fraud", "count"), fraud=("is_fraud", "sum")
)
fig, ax1 = plt.subplots(figsize=(10, 4.5))
ax1.plot(daily.index, daily["total"], color="#2dd4bf", label="Total transactions", linewidth=2)
ax1.set_ylabel("Total transactions", color="#2dd4bf")
ax1.set_xlabel("Date")
ax2 = ax1.twinx()
ax2.plot(daily.index, daily["fraud"], color="#f87171", label="Fraud count", linewidth=2, linestyle="--")
ax2.set_ylabel("Fraud count", color="#f87171")
ax1.set_title("Daily Transaction Volume & Fraud Count", fontsize=13, fontweight="bold")
fig.autofmt_xdate()
plt.tight_layout()
plt.savefig("../eda_output/4_daily_trend_line.png", dpi=120)
plt.close()

# ---------------------------------------------------------------------------
# Extra: transaction type breakdown (bar) — useful for report
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 4.5))
type_counts = df["type"].value_counts()
type_fraud_rate = df.groupby("type")["is_fraud"].mean() * 100
colors = plt.cm.Set2(np.linspace(0, 1, len(type_counts)))
ax.bar(type_counts.index, type_counts.values, color=colors)
ax.set_ylabel("Transaction count")
ax.set_title("Transaction Volume by Type", fontsize=13, fontweight="bold")
plt.xticks(rotation=20)
plt.tight_layout()
plt.savefig("../eda_output/5_transaction_type_bar.png", dpi=120)
plt.close()

# ---------------------------------------------------------------------------
# Printed summary (goes straight into report)
# ---------------------------------------------------------------------------
print("KEY FINDINGS")
print("-" * 60)
print(f"1. Fraud amount is much higher on average:")
print(f"   Legit avg: ₹{legit_amt.mean():,.0f}  |  Fraud avg: ₹{fraud_amt.mean():,.0f}")
print(f"   ({fraud_amt.mean()/legit_amt.mean():.1f}x higher)")
print()
print(f"2. Fraud only occurs in these transaction types:")
fraud_types = df[df["is_fraud"] == 1]["type"].value_counts()
print(fraud_types.to_string())
print()
print(f"3. Fraud subtype breakdown:")
print(df["fraud_subtype"].value_counts().to_string())
print()
print(f"4. New device rate — fraud vs legit:")
print(f"   (computed downstream in feature engineering, see train_models.py)")
print()
print("Charts saved to ../eda_output/")
