# Receiving KPIs (Problem Tags + Daily Receiving Data)

Standalone Streamlit app to track receiving issues and measure error rates against daily baselines.

## Features
- Problem Tag Submissions (multiple SKU lines per submission)
- Short/Heavy pairing support
- Daily Receiving Data entry (orders received + estimated units)
- Analytics including daily error rate and monthly trends
- Customers & Employees list management
- PostgreSQL backend (Neon) via Streamlit Secrets

## Streamlit Secrets
```toml
[connections.receiving]
url="postgresql://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require"
```

## Logo
Place `silverscreen_logo.png` in the repo root (same as QC dashboard).

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```
