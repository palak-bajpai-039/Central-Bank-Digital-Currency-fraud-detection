"""
Real-World Validation — Random Forest + Isolation Forest on the ULB
Credit Card Fraud Detection dataset
======================================================================
This validates the SAME modeling approach used in this project (supervised
Random Forest + unsupervised Isolation Forest, combined into a weighted
risk score) against a genuinely real, publicly-available, widely-cited
benchmark dataset -- not synthetic data.

Dataset: 284,807 real anonymized credit card transactions from European
cardholders, September 2013. Collected by Worldline and the Machine
Learning Group of Universite Libre de Bruxelles (ULB). This is the most
widely used academic and industry benchmark for fraud detection.

Get the dataset yourself (requires a free Kaggle account):
    https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud

Download creditcard.csv and place it in this scripts/ folder, then run:
    python3 validate_on_real_data.py
"""

import os
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    classification_report, precision_score, recall_score, f1_score,
    roc_auc_score, confusion_matrix,
)

DATA_PATH = "creditcard.csv"

if not os.path.exists(DATA_PATH):
    print(f"'{DATA_PATH}' not found in this folder.")
    print("Download it from https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud")
    print("(requires a free Kaggle account), place creditcard.csv here, and re-run.")
    raise SystemExit(1)

df = pd.read_csv(DATA_PATH)
print(f"Loaded {len(df):,} real transactions "
      f"({df['Class'].sum()} fraud, {df['Class'].mean()*100:.3f}%)")

# This dataset's features (V1-V28) are already PCA-anonymized by the
# original researchers for privacy -- we use them directly, plus Time
# and Amount, exactly as the dataset is designed to be used.
FEATURES = [c for c in df.columns if c != "Class"]
X = df[FEATURES]
y = df["Class"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.25, random_state=42, stratify=y
)

# Same architecture as the main project: RF (supervised) + Isolation
# Forest (unsupervised), weighted combination.
rf = RandomForestClassifier(
    n_estimators=200, max_depth=12, class_weight="balanced",
    random_state=42, n_jobs=-1,
)
rf.fit(X_train, y_train)
rf_proba = rf.predict_proba(X_test)[:, 1]

X_train_legit = X_train[y_train == 0]
iso = IsolationForest(
    n_estimators=200, contamination=float(y.mean()), random_state=42, n_jobs=-1,
)
iso.fit(X_train_legit)
iso_raw = iso.decision_function(X_test)
iso_anomaly = (iso_raw.max() - iso_raw) / (iso_raw.max() - iso_raw.min())

combined_score = 0.6 * rf_proba + 0.4 * iso_anomaly
combined_pred = (combined_score >= 0.5).astype(int)

precision = precision_score(y_test, combined_pred)
recall = recall_score(y_test, combined_pred)
f1 = f1_score(y_test, combined_pred)
auc = roc_auc_score(y_test, combined_score)

print("\n" + "=" * 60)
print("REAL-WORLD VALIDATION RESULTS (ULB Credit Card Fraud dataset)")
print("=" * 60)
print(classification_report(y_test, combined_pred, target_names=["Legit", "Fraud"]))
print("ROC-AUC:", round(auc, 4))
print("Confusion matrix:\n", confusion_matrix(y_test, combined_pred))

with open("real_data_validation_report.md", "w") as f:
    f.write("# Real-World Validation Report\n\n")
    f.write("Same model architecture (Random Forest + Isolation Forest, 0.6/0.4 "
            "weighted combination) validated on the **real** ULB Credit Card "
            "Fraud Detection dataset (284,807 real anonymized European card "
            "transactions), not synthetic data.\n\n")
    f.write(f"- **Test set size:** {len(y_test):,} transactions ({int(y_test.sum())} fraud)\n")
    f.write(f"- **Precision (fraud class):** {precision:.4f}\n")
    f.write(f"- **Recall (fraud class):** {recall:.4f}\n")
    f.write(f"- **F1 score (fraud class):** {f1:.4f}\n")
    f.write(f"- **ROC-AUC:** {auc:.4f}\n\n")
    f.write("Dataset source: https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud\n")

print("\nSaved: real_data_validation_report.md")
