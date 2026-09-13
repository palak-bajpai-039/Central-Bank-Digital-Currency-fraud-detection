"""
Train Random Forest (supervised) + Isolation Forest (unsupervised) on the
UPI transaction dataset, evaluate with precision/recall/F1, and save the
trained models + feature engineering artifacts for the backend to load.

Run: python3 train_models.py
"""

import pandas as pd
import numpy as np
import joblib
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    classification_report, precision_score, recall_score, f1_score,
    roc_auc_score, confusion_matrix,
)
from sklearn.preprocessing import LabelEncoder

df = pd.read_csv("../data/upi_transactions.csv", parse_dates=["timestamp"])

# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------
df["hour_of_day"] = df["timestamp"].dt.hour

# Sender's historical "usual" device / ip / location, computed from the
# FIRST time we see them acting normally (mode of device per sender)
sender_mode_device = df.groupby("sender_vpa")["device_id"].agg(lambda x: x.mode()[0])
sender_mode_location = df.groupby("sender_vpa")["location"].agg(lambda x: x.mode()[0])

df["is_new_device"] = (
    df["sender_vpa"].map(sender_mode_device) != df["device_id"]
).astype(int)
df["is_new_location"] = (
    df["sender_vpa"].map(sender_mode_location) != df["location"]
).astype(int)

# Transaction frequency for sender within the dataset (rough proxy for
# "how established" this sender is)
sender_txn_count = df.groupby("sender_vpa")["sender_vpa"].transform("count")
df["sender_txn_count"] = sender_txn_count

le_type = LabelEncoder()
df["type_encoded"] = le_type.fit_transform(df["type"])

FEATURES = [
    "amount", "hour_of_day", "wallet_age_days", "is_new_device",
    "is_new_location", "sender_txn_count", "type_encoded",
]

X = df[FEATURES]
y = df["is_fraud"]

# ---------------------------------------------------------------------------
# Train/test split (stratified, since fraud is rare)
# ---------------------------------------------------------------------------
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.25, random_state=42, stratify=y
)

# ---------------------------------------------------------------------------
# Random Forest (supervised)
# ---------------------------------------------------------------------------
rf = RandomForestClassifier(
    n_estimators=200,
    max_depth=12,
    class_weight="balanced",  # important: fraud is ~0.25% of data
    random_state=42,
    n_jobs=-1,
)
rf.fit(X_train, y_train)

rf_pred = rf.predict(X_test)
rf_proba = rf.predict_proba(X_test)[:, 1]

print("=" * 60)
print("RANDOM FOREST — evaluation on held-out test set")
print("=" * 60)
print(classification_report(y_test, rf_pred, target_names=["Legit", "Fraud"]))
print("ROC-AUC:", round(roc_auc_score(y_test, rf_proba), 4))
print("Confusion matrix:\n", confusion_matrix(y_test, rf_pred))

# ---------------------------------------------------------------------------
# Isolation Forest (unsupervised anomaly detection)
# Trained ONLY on legitimate transactions, so it learns what "normal" looks
# like and flags deviations — this is what catches fraud patterns RF hasn't
# seen before.
# ---------------------------------------------------------------------------
X_train_legit = X_train[y_train == 0]

iso = IsolationForest(
    n_estimators=200,
    contamination=0.0025,  # matches our known fraud rate
    random_state=42,
    n_jobs=-1,
)
iso.fit(X_train_legit)

# decision_function: higher = more normal, lower = more anomalous
iso_raw_scores = iso.decision_function(X_test)
# Normalize to 0-1 where 1 = most anomalous, for combining with RF probability
iso_anomaly_score = (iso_raw_scores.max() - iso_raw_scores) / (
    iso_raw_scores.max() - iso_raw_scores.min()
)
iso_pred = (iso.predict(X_test) == -1).astype(int)  # -1 = anomaly

print("\n" + "=" * 60)
print("ISOLATION FOREST — evaluation on held-out test set")
print("=" * 60)
print(classification_report(y_test, iso_pred, target_names=["Legit", "Fraud"]))

# ---------------------------------------------------------------------------
# Combined risk score (weighted, matches roadmap Phase 7 logic)
# ---------------------------------------------------------------------------
RF_WEIGHT = 0.6
IF_WEIGHT = 0.4
combined_score = RF_WEIGHT * rf_proba + IF_WEIGHT * iso_anomaly_score
combined_pred = (combined_score >= 0.5).astype(int)

print("\n" + "=" * 60)
print("COMBINED RISK SCORE (0.6*RF + 0.4*IsolationForest) — final model")
print("=" * 60)
print(classification_report(y_test, combined_pred, target_names=["Legit", "Fraud"]))
print("ROC-AUC:", round(roc_auc_score(y_test, combined_score), 4))
print("Confusion matrix:\n", confusion_matrix(y_test, combined_pred))

precision = precision_score(y_test, combined_pred)
recall = recall_score(y_test, combined_pred)
f1 = f1_score(y_test, combined_pred)

# ---------------------------------------------------------------------------
# Save artifacts for the backend
# ---------------------------------------------------------------------------
joblib.dump(rf, "../models/random_forest.joblib")
joblib.dump(iso, "../models/isolation_forest.joblib")
joblib.dump(le_type, "../models/type_encoder.joblib")
joblib.dump(
    {
        "sender_mode_device": sender_mode_device.to_dict(),
        "sender_mode_location": sender_mode_location.to_dict(),
        "sender_txn_count": sender_txn_count.groupby(df["sender_vpa"]).first().to_dict()
        if False else df.groupby("sender_vpa")["sender_vpa"].count().to_dict(),
        "features": FEATURES,
        "rf_weight": RF_WEIGHT,
        "if_weight": IF_WEIGHT,
        "iso_score_min": float(iso_raw_scores.min()),
        "iso_score_max": float(iso_raw_scores.max()),
    },
    "../models/feature_lookup.joblib",
)

with open("../models/evaluation_report.md", "w") as f:
    f.write("# Model Evaluation Report\n\n")
    f.write(f"- **Test set size:** {len(y_test)} transactions ({y_test.sum()} fraud)\n")
    f.write(f"- **Precision (fraud class):** {precision:.4f}\n")
    f.write(f"- **Recall (fraud class):** {recall:.4f}\n")
    f.write(f"- **F1 score (fraud class):** {f1:.4f}\n")
    f.write(f"- **ROC-AUC:** {roc_auc_score(y_test, combined_score):.4f}\n\n")
    f.write("## Confusion Matrix\n\n```\n")
    f.write(str(confusion_matrix(y_test, combined_pred)))
    f.write("\n```\n\n")
    f.write("Rows = actual, Columns = predicted. Order: [Legit, Fraud]\n")

print("\nSaved models to ../models/")
print(f"\nFinal combined-score metrics — Precision: {precision:.3f}  Recall: {recall:.3f}  F1: {f1:.3f}")
