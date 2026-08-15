import pandas as pd
import numpy as np
import random
from datetime import datetime, timedelta

np.random.seed(42)

NUM_ACCOUNTS = 200
NUM_TRANSACTIONS = 5000

accounts = []

# Generate accounts
for i in range(NUM_ACCOUNTS):

    mule_flag = 1 if random.random() < 0.12 else 0

    accounts.append({
        "account_id": f"ACC{i:04}",
        "account_age_days": np.random.randint(10, 2000),
        "kyc_risk": np.random.randint(1, 5),
        "shared_device_count": np.random.randint(1, 10) if mule_flag else np.random.randint(1, 3),
        "is_mule": mule_flag
    })

accounts_df = pd.DataFrame(accounts)

transactions = []

for _ in range(NUM_TRANSACTIONS):

    sender = random.choice(accounts)
    receiver = random.choice(accounts)

    while sender["account_id"] == receiver["account_id"]:
        receiver = random.choice(accounts)

    mule_behavior = sender["is_mule"]

    amount = (
        np.random.randint(5000, 50000)
        if mule_behavior
        else np.random.randint(100, 5000)
    )

    txn_time = datetime.now() - timedelta(
        minutes=np.random.randint(0, 100000)
    )

    transactions.append({
        "sender": sender["account_id"],
        "receiver": receiver["account_id"],
        "amount": amount,
        "timestamp": txn_time
    })

transactions_df = pd.DataFrame(transactions)

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

accounts_df.to_csv(
    os.path.join(BASE_DIR, "accounts.csv"),
    index=False
)

transactions_df.to_csv(
    os.path.join(BASE_DIR, "transactions.csv"),
    index=False
)

print("Dummy data generated successfully.")


