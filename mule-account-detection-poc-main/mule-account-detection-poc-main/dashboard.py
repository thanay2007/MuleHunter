import streamlit as st
import pandas as pd
import plotly.express as px

st.title("Mule Account Detection POC")

df = pd.read_csv("mule_predictions.csv")

st.subheader("Top Suspicious Accounts")

top_df = df.sort_values(
    by="risk_score",
    ascending=False
).head(20)

st.dataframe(top_df)

fig = px.scatter(
    top_df,
    x="txn_sum",
    y="risk_score",
    size="txn_count",
    hover_data=["account_id"],
)

st.plotly_chart(fig)

st.subheader("High Risk Accounts")

high_risk = df[df["risk_score"] > 50]

st.dataframe(high_risk)