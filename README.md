# Receiving Issues & Problem Tags Dashboard

This is a standalone Streamlit application for tracking receiving-related issues such as:
- Short / Heavy items
- Damaged in Production
- Factory Damage

The app supports:
- Multi-line problem tag submissions (multiple SKUs per issue)
- Dynamic dropdowns for Customers and Employees
- Monthly trend-ready data (via Date Found)
- PostgreSQL backend hosted on Neon
- Deployment via Streamlit Community Cloud

## Tech Stack
- Streamlit
- PostgreSQL (Neon)
- SQLAlchemy
- Pandas

## Setup Instructions

### 1. Neon Database
Create a new **Neon project** (recommended) and copy the connection string.

### 2. Streamlit Secrets
In Streamlit Cloud → App Settings → Secrets:

```toml
[connections.receiving]
url="postgresql://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require"
```

### 3. Requirements
Install dependencies locally if needed:

```bash
pip install -r requirements.txt
```

### 4. Run Locally
```bash
streamlit run app.py
```

## Logo
This app expects a file named:

```
silverscreen_logo.png
```

placed in the **root directory**, matching the QC Dashboard layout.

## Deployment
- Push this repo to GitHub
- Connect it to Streamlit Community Cloud
- Point secrets to your Neon project

Tables are auto-created on first run.
