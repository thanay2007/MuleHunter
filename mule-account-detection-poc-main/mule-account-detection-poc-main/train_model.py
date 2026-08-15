import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import joblib

# Load data
accounts = pd.read_csv("accounts.csv")
transactions = pd.read_csv("transactions.csv")

# Transaction aggregations
txn_out = transactions.groupby("sender").agg({
    "amount": ["count", "sum", "mean"]
})

txn_out.columns = [
    "txn_count",
    "txn_sum",
    "txn_avg"
]

txn_out.reset_index(inplace=True)

# Merge with account data
df = accounts.merge(
    txn_out,
    left_on="account_id",
    right_on="sender",
    how="left"
)

df.fillna(0, inplace=True)

# Feature engineering
df["velocity_score"] = df["txn_count"] / (df["account_age_days"] + 1)

features = [
    "account_age_days",
    "kyc_risk",
    "shared_device_count",
    "txn_count",
    "txn_sum",
    "txn_avg",
    "velocity_score"
]

X = df[features]

# Scale data
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# Isolation Forest
model = IsolationForest(
    contamination=0.12,
    random_state=42
)

model.fit(X_scaled)

# Predictions
df["anomaly"] = model.predict(X_scaled)

# Convert:
# -1 => suspicious
#  1 => normal
df["mule_prediction"] = df["anomaly"].apply(
    lambda x: 1 if x == -1 else 0
)

# Save model
joblib.dump(model, "mule_model.pkl")
joblib.dump(scaler, "scaler.pkl")

# Export results
df.to_csv("mule_predictions.csv", index=False)

print(df[
    [
        "account_id",
        "mule_prediction",
        "txn_count",
        "txn_sum",
        "shared_device_count"
    ]
].head(20))

print("\nModel training complete.")

import networkx as nx

G = nx.from_pandas_edgelist(
    transactions,
    source="sender",
    target="receiver",
    edge_attr="amount"
)

centrality = nx.degree_centrality(G)

df["network_score"] = df["account_id"].map(centrality)

df["network_score"] = df["network_score"].fillna(0)

# Final risk score
df["risk_score"] = (
    df["shared_device_count"] * 10
    + df["velocity_score"] * 100
    + df["network_score"] * 200
)

df = df.sort_values(by="risk_score", ascending=False)

df.to_csv("mule_predictions.csv", index=False)

print("\nTop suspicious accounts:\n")
print(df[
    [
        "account_id",
        "risk_score",
        "mule_prediction",
        "network_score"
    ]
].head(10))