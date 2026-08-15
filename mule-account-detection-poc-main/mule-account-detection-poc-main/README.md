# Mule Account Detection POC

## Overview

This project is a Proof of Concept (POC) for identifying potentially suspicious mule accounts using synthetic banking data, machine learning, transaction analytics, and network analysis.

The solution generates synthetic account and transaction data, trains an anomaly detection model, calculates risk scores, and displays suspicious accounts through an interactive dashboard.

---

# Project Architecture

```text
Synthetic Data Generation
          ↓
Feature Engineering
          ↓
Anomaly Detection Model
          ↓
Network Analysis
          ↓
Risk Scoring
          ↓
Investigator Dashboard
```

---

# Project Files

| File                 | Purpose                                                |
| -------------------- | ------------------------------------------------------ |
| generate_data.py     | Creates synthetic account and transaction data         |
| train_model.py       | Trains mule detection model and calculates risk scores |
| dashboard.py         | Launches investigator dashboard                        |
| requirements.txt     | Python package dependencies                            |
| accounts.csv         | Generated account dataset                              |
| transactions.csv     | Generated transaction dataset                          |
| mule_predictions.csv | Model output and risk scores                           |
| mule_model.pkl       | Trained machine learning model                         |
| scaler.pkl           | Feature scaling object                                 |

---

# Prerequisites

The following software must be installed:

1. Python 3.10 or higher
2. Internet connection (only required during package installation)

Verify Python installation:

```bash
python --version
```

Expected output:

```text
Python 3.x.x
```

---

# Installation

Navigate to the project folder:

```bash
cd C:\Users\HP\Desktop\mule-poc
```

Install required libraries:

```bash
python -m pip install -r requirements.txt
```

---

# Running the Application

The project should be executed in the following order.

## Step 1 – Generate Synthetic Data

Run:

```bash
python generate_data.py
```

Expected output:

```text
Dummy data generated successfully.
```

Generated files:

```text
accounts.csv
transactions.csv
```

---

## Step 2 – Train Mule Detection Model

Run:

```bash
python train_model.py
```

This step performs:

* Feature engineering
* Data normalization
* Anomaly detection
* Network analysis
* Risk score generation

Expected output:

```text
Top suspicious accounts...
Model training complete.
```

Generated files:

```text
mule_predictions.csv
mule_model.pkl
scaler.pkl
```

---

## Step 3 – Launch Dashboard

Run:

```bash
python -m streamlit run dashboard.py
```

Expected output:

```text
Local URL: http://localhost:8501
```

Open the URL in a browser:

```text
http://localhost:8501
```

The dashboard will display:

* Top suspicious accounts
* Risk scores
* Transaction analytics
* Interactive visualizations
* High-risk account list

---

# Understanding the Output

## accounts.csv

Contains synthetic customer account information.

Sample fields:

* account_id
* account_age_days
* kyc_risk
* shared_device_count

---

## transactions.csv

Contains synthetic transaction activity.

Sample fields:

* sender
* receiver
* amount
* timestamp

---

## mule_predictions.csv

Contains model-generated risk indicators.

Sample fields:

* account_id
* txn_count
* txn_sum
* velocity_score
* network_score
* risk_score
* mule_prediction

### Interpretation

| Value | Meaning            |
| ----- | ------------------ |
| 0     | Normal Account     |
| 1     | Suspicious Account |

Higher risk scores indicate higher investigation priority.

---

# Machine Learning Approach

The POC uses the Isolation Forest algorithm, an unsupervised anomaly detection technique.

The model identifies accounts that behave significantly differently from the general population using features such as:

* Transaction volume
* Transaction velocity
* Shared device indicators
* Network connectivity
* Aggregate transaction values

---

# Network Analysis

Network analysis is performed using NetworkX.

Each account is represented as a node and each transaction as an edge.

This helps identify:

* Transaction hubs
* Highly connected accounts
* Suspicious money movement patterns
* Potential mule account clusters

---

# Troubleshooting

## Python Not Found

Verify installation:

```bash
python --version
```

If Python is not recognized:

* Reinstall Python
* Enable **Add Python to PATH** during installation

---

## No Module Named pandas

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

---

## Streamlit Command Not Found

Run:

```bash
python -m streamlit run dashboard.py
```

instead of:

```bash
streamlit run dashboard.py
```

---

## Dashboard Does Not Open

Open the browser manually and navigate to:

```text
http://localhost:8501
```

If port 8501 is unavailable:

```bash
python -m streamlit run dashboard.py --server.port 8502
```

Then open:

```text
http://localhost:8502
```

---

# Limitations

This is a Proof of Concept and not a production-grade AML or fraud detection system.

The data is synthetic and intended for demonstration purposes only.

The model should not be used for actual customer risk decisions without additional controls, validation, governance, and regulatory review.

---

# Future Enhancements

Potential enhancements include:

* Shared mobile number analysis
* Shared IP address detection
* Device fingerprinting
* Dormant account activation monitoring
* Circular transaction detection
* Real-time transaction monitoring
* Graph neural networks
* Explainable AI (SHAP)
* Automated SAR narrative generation using AI

---

# Conclusion

This POC demonstrates an end-to-end mule account detection workflow comprising:

1. Synthetic banking data generation
2. Feature engineering
3. Machine learning-based anomaly detection
4. Network and relationship analysis
5. Risk scoring
6. Investigator dashboard visualization

The architecture provides a foundation that can be extended into a more sophisticated financial crime and AML monitoring solution.
