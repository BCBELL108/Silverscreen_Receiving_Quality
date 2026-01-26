import streamlit as st
import pandas as pd
from datetime import date, timedelta
from sqlalchemy import text
import plotly.express as px
import plotly.graph_objects as go
import uuid

# =============================================================================
# CONFIG
# =============================================================================

TEAM_OPTIONS = ["Screenprint", "Embroidery", "Digital", "VAS"]

PROBLEM_TYPES = [
    "Damaged in Production",
    "Short/ Heavy Items",
    "Factory Damage",
]

SIZE_OPTIONS = [
    "2T", "3T", "4T", "5/6T",
    "YXS", "YS", "YM", "YL", "YXL",
    "XS", "S", "M", "L", "XL", "2XL", "3XL",
    "OTHER",
]

SHORT_HEAVY_OPTIONS = [
    "",
    "Short",
    "Heavy",
    "Short/Heavy",
]

# mapping used for main problem type vs lines' short/heavy tag (when the issue is short/heavy)
SHORT_HEAVY_LINE_PROBLEM_TYPES = [
    "Short/ Heavy Items",
]

# PRESET COLORS
COLOR_MATCH_OPTIONS = [
    "",
    "Matches Packing Slip",
    "Does Not Match Packing Slip",
]

# caching DB URL
@st.cache_resource
def get_engine():
    from sqlalchemy import create_engine

    # You can change this to your Neon URL
    db_url = st.secrets["db_url"]
    engine = create_engine(db_url, pool_pre_ping=True)
    return engine


# =============================================================================
# DB HELPERS
# =============================================================================


def init_db():
    """Create tables if they don't already exist."""
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS receiving_customers (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    customer_name TEXT NOT NULL UNIQUE
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS receiving_employees (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    employee_name TEXT NOT NULL UNIQUE
                )
                """
            )
        )

        # Daily "Receiving Data" baseline
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS receiving_daily_actuals (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    receiving_date DATE NOT NULL,
                    orders_received INTEGER NOT NULL,
                    estimated_units INTEGER NOT NULL,
                    author_name TEXT NOT NULL,
                    notes TEXT,
                    date_entered TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    active INTEGER DEFAULT 1
                )
                """
            )
        )

        # Problem tags - header
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS receiving_problem_tags (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    date_found DATE NOT NULL,
                    po_number TEXT NOT NULL,
                    customer_id INTEGER NOT NULL REFERENCES receiving_customers(id),
                    job_name TEXT NOT NULL,
                    team_name TEXT NOT NULL,
                    author_name TEXT NOT NULL,
                    problem_type TEXT NOT NULL,
                    mistake_employee_id INTEGER NULL REFERENCES receiving_employees(id),
                    notes TEXT,
                    date_entered TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    active INTEGER DEFAULT 1
                )
                """
            )
        )

        # Problem tags - line items
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS receiving_problem_lines (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    tag_id INTEGER NOT NULL REFERENCES receiving_problem_tags(id),
                    short_heavy_tag TEXT,
                    style_number TEXT NOT NULL,
                    item_description TEXT NOT NULL,
                    color TEXT NOT NULL,
                    size TEXT NOT NULL,
                    vendor_packing_slip_matches INTEGER,
                    qty_short INTEGER,
                    qty_heavy INTEGER
                )
                """
            )
        )


def get_customers() -> pd.DataFrame:
    eng = get_engine()
    with eng.connect() as conn:
        df = pd.read_sql(text("SELECT id, customer_name FROM receiving_customers ORDER BY customer_name"), conn)
    return df


def get_employees() -> pd.DataFrame:
    eng = get_engine()
    with eng.connect() as conn:
        df = pd.read_sql(text("SELECT id, employee_name FROM receiving_employees ORDER BY employee_name"), conn)
    return df


def add_customer_if_needed(name: str) -> int:
    name = name.strip()
    if not name:
        raise ValueError("Customer name cannot be empty.")
    eng = get_engine()
    with eng.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO receiving_customers (customer_name)
                VALUES (:name)
                ON CONFLICT (customer_name) DO UPDATE SET customer_name = EXCLUDED.customer_name
                RETURNING id
                """
            ),
            {"name": name},
        )
        cid = result.scalar_one()
    return cid


def add_employee(name: str) -> int:
    name = name.strip()
    if not name:
        raise ValueError("Employee name cannot be empty.")
    eng = get_engine()
    with eng.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO receiving_employees (employee_name)
                VALUES (:name)
                ON CONFLICT (employee_name) DO UPDATE SET employee_name = EXCLUDED.employee_name
                RETURNING id
                """
            ),
            {"name": name},
        )
        eid = result.scalar_one()
    return eid


def save_daily_actuals(
    *,
    receiving_date: date,
    orders_received: int,
    estimated_units: int,
    author_name: str,
    notes: str | None = None,
) -> int:
    eng = get_engine()
    with eng.begin() as conn:
        res = conn.execute(
            text(
                """
                INSERT INTO receiving_daily_actuals (
                    receiving_date, orders_received, estimated_units, author_name, notes
                )
                VALUES (:dt, :ord, :est, :auth, :notes)
                RETURNING id
                """
            ),
            {
                "dt": receiving_date,
                "ord": orders_received,
                "est": estimated_units,
                "auth": author_name,
                "notes": notes,
            },
        )
        return res.scalar_one()


def fetch_daily_actuals(start: date, end: date) -> pd.DataFrame:
    eng = get_engine()
    with eng.connect() as conn:
        df = pd.read_sql(
            text(
                """
                SELECT
                    id,
                    receiving_date,
                    orders_received,
                    estimated_units,
                    author_name,
                    notes,
                    date_entered,
                    active
                FROM receiving_daily_actuals
                WHERE receiving_date BETWEEN :s AND :e
                ORDER BY receiving_date
                """
            ),
            conn,
            params={"s": start, "e": end},
        )
    df["receiving_date"] = pd.to_datetime(df["receiving_date"])
    df["date_entered"] = pd.to_datetime(df["date_entered"])
    return df


def packing_slip_to_bool(val: str | None) -> int | None:
    if not val:
        return None
    if val == "Matches Packing Slip":
        return 1
    if val == "Does Not Match Packing Slip":
        return 0
    return None


def save_problem_tag(
    *,
    date_found: date,
    po_number: str,
    customer_id: int,
    job_name: str,
    team_name: str,
    author_name: str,
    problem_type: str,
    mistake_employee_id: int | None,
    notes: str,
    lines: list[dict],
) -> int:
    """Saves header + line items in a transaction. Returns the new tag_id."""
    eng = get_engine()
    with eng.begin() as conn:
        tag_id = conn.execute(
            text(
                """
                INSERT INTO receiving_problem_tags (
                    date_found, po_number, customer_id, job_name, team_name,
                    author_name, problem_type, mistake_employee_id, notes
                )
                VALUES (
                    :date_found, :po_number, :customer_id, :job_name, :team_name,
                    :author_name, :problem_type, :mistake_employee_id, :notes
                )
                RETURNING id
                """
            ),
            {
                "date_found": date_found,
                "po_number": po_number,
                "customer_id": customer_id,
                "job_name": job_name,
                "team_name": team_name,
                "author_name": author_name,
                "problem_type": problem_type,
                "mistake_employee_id": mistake_employee_id,
                "notes": notes,
            },
        ).scalar_one()

        for ln in lines:
            conn.execute(
                text(
                    """
                    INSERT INTO receiving_problem_lines (
                        tag_id,
                        short_heavy_tag,
                        style_number,
                        item_description,
                        color,
                        size,
                        vendor_packing_slip_matches,
                        qty_short,
                        qty_heavy
                    )
                    VALUES (
                        :tag_id,
                        :short_heavy_tag,
                        :style_number,
                        :item_description,
                        :color,
                        :size,
                        :vendor_packing_slip_matches,
                        :qty_short,
                        :qty_heavy
                    )
                    """
                ),
                {
                    "tag_id": tag_id,
                    "short_heavy_tag": ln.get("short_heavy_tag"),
                    "style_number": ln.get("style_number"),
                    "item_description": ln.get("item_description"),
                    "color": ln.get("color"),
                    "size": ln.get("size"),
                    "vendor_packing_slip_matches": ln.get("vendor_packing_slip_matches"),
                    "qty_short": ln.get("qty_short"),
                    "qty_heavy": ln.get("qty_heavy"),
                },
            )

    return tag_id


def fetch_problem_tags_and_lines(
    start: date, end: date, team_filter: str | None = None, customer_id: int | None = None
) -> pd.DataFrame:
    """Return a wide dataframe joining tags + lines for analytics."""
    eng = get_engine()
    with eng.connect() as conn:
        base_query = """
            SELECT
                t.id AS tag_id,
                t.date_found,
                t.po_number,
                t.job_name,
                t.team_name,
                t.author_name,
                t.problem_type,
                t.notes,
                t.date_entered,
                c.customer_name,
                e.employee_name AS mistake_made_by,
                l.id AS line_id,
                l.short_heavy_tag,
                l.style_number,
                l.item_description,
                l.color,
                l.size,
                l.vendor_packing_slip_matches,
                l.qty_short,
                l.qty_heavy
            FROM receiving_problem_tags t
            JOIN receiving_customers c
                ON t.customer_id = c.id
            LEFT JOIN receiving_employees e
                ON t.mistake_employee_id = e.id
            LEFT JOIN receiving_problem_lines l
                ON l.tag_id = t.id
            WHERE
                t.date_found BETWEEN :start_date AND :end_date
                AND t.active = 1
        """

        params: dict = {"start_date": start, "end_date": end}

        if team_filter and team_filter != "-- All --":
            base_query += " AND t.team_name = :team_name"
            params["team_name"] = team_filter

        if customer_id is not None:
            base_query += " AND t.customer_id = :customer_id"
            params["customer_id"] = customer_id

        base_query += """
            ORDER BY t.date_found, t.id, l.id
        """

        df = pd.read_sql(text(base_query), conn, params=params)

    if not df.empty:
        df["date_found"] = pd.to_datetime(df["date_found"])
        df["date_entered"] = pd.to_datetime(df["date_entered"])
    return df


def default_line() -> dict:
    """Default line dict for the older detailed mode (kept in case you ever want it back)."""
    return {
        "short_heavy_tag": "",
        "style_number": "",
        "item_description": "",
        "color": "",
        "size": "M",
        "vendor_packing_slip_matches": "",
        "qty_short": 0,
        "qty_heavy": 0,
        # pairing metadata for short/heavy
        "pair_group": None,
        "paired_role": None,  # "Short" or "Heavy"
    }


def ensure_line_state():
    """Initialize session lines for the old detailed UI (still referenced in a few places)."""
    if "lines" not in st.session_state:
        st.session_state["lines"] = [default_line()]


def validate_submission(header: dict, total_pieces_with_error: int | None) -> list[str]:
    """Validate the simplified problem tag submission.

    We now only *require*:
      - date_found
      - customer_id
      - problem_type
      - total_pieces_with_error (> 0)

    Other fields (PO#, job name, team, author) are optional and will be
    defaulted before saving so they satisfy the NOT NULL constraints.
    """
    errors: list[str] = []

    if not header.get("date_found"):
        errors.append("Date Found is required.")

    if not header.get("customer_id"):
        errors.append("Customer is required.")

    if not header.get("problem_type"):
        errors.append("Problem Type is required.")

    if total_pieces_with_error is None or total_pieces_with_error <= 0:
        errors.append("Total pieces with this problem must be greater than 0.")

    return errors


# =============================================================================
# APP
# =============================================================================


def main():
    st.set_page_config(page_title="Receiving KPIs", page_icon="📦", layout="wide")

    # Connection check
    try:
        eng = get_engine()
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        st.error("Could not connect to database. Check secrets['db_url'].")
        st.exception(e)
        return

    # Always ensure tables exist
    init_db()

    # Sidebar
    with st.sidebar:
        st.title("Receiving KPIs")
        st.markdown("Use this app to log problems, track daily receiving, and see error rates.")

        menu = st.radio(
            "Go to:",
            [
                "📝 Problem Tag Submission",
                "📦 Receiving Data",
                "📊 Analytics",
                "⚙️ Admin",
            ],
        )

        st.markdown("---")
        st.caption("Neon PostgreSQL • Streamlit • Plotly")

    # Header / subheader
    st.markdown("<h1 style='text-align:center;'>Receiving KPIs</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p style='text-align:center; font-size:14px; color:gray;'>Silverscreen Decoration &amp; Fulfillment®</p>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # -------------------------------------------------------------------------
    # 1) SUBMISSION TAB
    # -------------------------------------------------------------------------
    if menu == "📝 Problem Tag Submission":
        st.header("Problem Tag Submission")

        # If we just saved, show a confirmation and clear the form
        last_id = st.session_state.pop("problem_tag_form_submitted", None)
        if last_id is not None:
            st.success(f"✅ Saved Problem Tag (ID: {last_id})")

        customers_df = get_customers()
        employees_df = get_employees()

        customer_options = ["-- Select Customer --"] + customers_df["customer_name"].tolist()
        employee_options = ["-- Unknown / Not Set --"] + employees_df["employee_name"].tolist()

        # --- Core required fields (kept minimal on purpose) ---
        c1, c2 = st.columns(2)
        with c1:
            date_found = st.date_input("Date Found *", value=date.today(), format="MM/DD/YYYY")
            customer_name = st.selectbox("Customer Name *", customer_options)
        with c2:
            problem_type = st.selectbox("Problem Type *", PROBLEM_TYPES)
            mistake_name = st.selectbox("Mistake Made By (optional)", employee_options)

        total_pieces_with_error = st.number_input(
            "Total pieces with this problem *",
            min_value=1,
            step=1,
            key="total_pieces_with_error",
        )

        # --- Optional extra context (PO, Job, Team, Author, Notes) ---
        with st.expander("Optional details (PO, Job, Team, Author, Notes)"):
            c3, c4 = st.columns(2)
            with c3:
                po_number = st.text_input("PO# (optional)", placeholder="e.g., PO-12345")
                job_name = st.text_input("Job Name (optional)", placeholder="e.g., Spring Promo Kit")
            with c4:
                team_name = st.selectbox("Team Name (optional)", ["-- Auto: Receiving --"] + TEAM_OPTIONS)
                author_name = st.text_input("Author (optional)", placeholder="Who is submitting this?")

            notes = st.text_area(
                "Notes (optional)",
                placeholder="Anything helpful about what was found / how it was resolved...",
            )

        # Map friendly names back to ids
        customer_id = None
        if customer_name != "-- Select Customer --":
            customer_id = int(
                customers_df.loc[customers_df["customer_name"] == customer_name, "id"].values[0]
            )

        mistake_employee_id = None
        if mistake_name != "-- Unknown / Not Set --":
            mistake_employee_id = int(
                employees_df.loc[employees_df["employee_name"] == mistake_name, "id"].values[0]
            )

        # Defaults so DB NOT NULL constraints are always satisfied
        po_number_val = (po_number or "").strip()
        if not po_number_val:
            po_number_val = "N/A"

        job_name_val = (job_name or "").strip()
        if not job_name_val:
            job_name_val = "Quick Entry"

        team_name_val = team_name
        if not team_name_val or team_name_val == "-- Auto: Receiving --":
            team_name_val = "Receiving"

        author_name_val = (author_name or "").strip()
        if not author_name_val:
            author_name_val = "Receiving Team"

        header = {
            "date_found": date_found,
            "po_number": po_number_val,
            "customer_id": customer_id,
            "job_name": job_name_val,
            "team_name": team_name_val,
            "author_name": author_name_val,
            "problem_type": problem_type,
            "mistake_employee_id": mistake_employee_id,
            "notes": notes,
        }

        # We now store a single generic line where qty_short = total pieces with error.
        # This feeds the existing analytics (error_units / total_units) without needing SKU-level detail.
        lines_payload = [
            {
                "short_heavy_tag": None,
                "style_number": "N/A",
                "item_description": f"Quick entry ({problem_type})",
                "color": "N/A",
                "size": "M",
                "vendor_packing_slip_matches": None,
                "qty_short": int(total_pieces_with_error) if total_pieces_with_error else None,
                "qty_heavy": None,
            }
        ]

        if st.button("💾 Submit Problem Tag", type="primary", use_container_width=True):
            errs = validate_submission(
                header,
                int(total_pieces_with_error) if total_pieces_with_error else None,
            )
            if errs:
                st.error("Please fix the following before submitting:")
                for e in errs:
                    st.write(f"- {e}")
            else:
                tag_id = save_problem_tag(
                    date_found=header["date_found"],
                    po_number=header["po_number"],
                    customer_id=header["customer_id"],
                    job_name=header["job_name"],
                    team_name=header["team_name"],
                    author_name=header["author_name"],
                    problem_type=header["problem_type"],
                    mistake_employee_id=header["mistake_employee_id"],
                    notes=header["notes"],
                    lines=lines_payload,
                )
                # Flag so we can show success after rerun and give you a clean form
                st.session_state["problem_tag_form_submitted"] = tag_id
                # Also reset the pieces field to its minimum on next load
                st.session_state["total_pieces_with_error"] = 1
                st.rerun()

    # -------------------------------------------------------------------------
    # 2) RECEIVING DATA (DAILY ACTUALS / BASELINE)
    # -------------------------------------------------------------------------
    elif menu == "📦 Receiving Data":
        st.header("Receiving Data (Daily Actuals)")

        st.markdown(
            "Use this page to log what Receiving completed each day so we have a baseline "
            "for error rates (issues vs total orders/units received)."
        )

        c1, c2, c3 = st.columns(3)
        with c1:
            receiving_date = st.date_input(
                "Receiving Date *",
                value=date.today() - timedelta(days=1),
                format="MM/DD/YYYY",
                help="Typically enter yesterday's totals.",
            )
        with c2:
            orders_received = st.number_input("Total Orders Received *", min_value=0, step=1, value=0)
        with c3:
            estimated_units = st.number_input("Estimated Units Received *", min_value=0, step=1, value=0)

        author_name = st.text_input("Submitted By *", placeholder="Type name...")
        notes = st.text_area(
            "Notes (optional)",
            placeholder="Anything helpful (carrier delays, partial deliveries, etc.)",
        )

        if st.button("💾 Save Receiving Data", type="primary", use_container_width=True):
            if not author_name.strip():
                st.error("Submitted By is required.")
            elif orders_received <= 0:
                st.error("Total Orders Received must be greater than 0.")
            elif estimated_units <= 0:
                st.error("Estimated Units Received must be greater than 0.")
            else:
                rec_id = save_daily_actuals(
                    receiving_date=receiving_date,
                    orders_received=int(orders_received),
                    estimated_units=int(estimated_units),
                    author_name=author_name,
                    notes=notes,
                )
                st.success(f"✅ Saved daily receiving data (ID: {rec_id})")

        st.markdown("---")
        st.subheader("Recent Entries")

        recent_start = date.today() - timedelta(days=120)
        recent_end = date.today()
        daily_df = fetch_daily_actuals(recent_start, recent_end)

        if daily_df.empty:
            st.info("No daily receiving entries yet.")
        else:
            show_df = daily_df.copy()
            show_df["receiving_date"] = show_df["receiving_date"].dt.strftime("%m/%d/%Y")
            show_df["date_entered"] = show_df["date_entered"].dt.strftime("%m/%d/%Y")
            st.dataframe(
                show_df[
                    [
                        "receiving_date",
                        "orders_received",
                        "estimated_units",
                        "author_name",
                        "notes",
                        "date_entered",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

            csv = show_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇️ Download Receiving Data CSV",
                data=csv,
                file_name=f"receiving_daily_actuals_{date.today().strftime('%Y-%m-%d')}.csv",
                mime="text/csv",
            )

    # -------------------------------------------------------------------------
    # 2) ANALYTICS (UPDATED)
    # -------------------------------------------------------------------------
    elif menu == "📊 Analytics":
        st.header("Analytics")

        customers_df = get_customers()
        customer_list = ["-- All --"] + customers_df["customer_name"].tolist()

        f1, f2, f3, f4 = st.columns([2, 2, 2, 2])
        with f1:
            start_date = st.date_input("Start Date", value=date.today() - timedelta(days=180), format="MM/DD/YYYY", key="ana_sd")
        with f2:
            end_date = st.date_input("End Date", value=date.today(), format="MM/DD/YYYY", key="ana_ed")
        with f3:
            team_filter = st.selectbox("Team", ["-- All --"] + TEAM_OPTIONS, key="ana_team")
        with f4:
            cust_filter = st.selectbox("Customer", customer_list, key="ana_cust")

        p1, p2 = st.columns([2, 2])
        with p1:
            include_unit_detail = st.checkbox(
                "Show unit-level detail (error units)",
                value=True,
                help="If unchecked, metrics focus only on count of problem tags (orders with issues).",
            )
        with p2:
            sort_mode = st.selectbox(
                "Sort charts by",
                [
                    "Highest error rate",
                    "Most error units",
                    "Most problem tags",
                    "Customer name",
                ],
            )

        # Map cust_filter back to ID
        customer_id = None
        if cust_filter != "-- All --":
            customer_id = int(customers_df.loc[customers_df["customer_name"] == cust_filter, "id"].values[0])

        # Fetch problem tags + lines
        problems_df = fetch_problem_tags_and_lines(start_date, end_date, team_filter, customer_id)
        daily_df = fetch_daily_actuals(start_date, end_date)

        if problems_df.empty and daily_df.empty:
            st.info("No data found in this date range.")
            return

        # ---------------------------------------------------------------------
        # Compute baseline: daily total units
        # ---------------------------------------------------------------------
        if daily_df.empty:
            daily_units = pd.DataFrame(columns=["receiving_date", "total_units"])
        else:
            daily_units = (
                daily_df.groupby("receiving_date", as_index=False)["estimated_units"]
                .sum()
                .rename(columns={"receiving_date": "date_found", "estimated_units": "total_units"})
            )

        # ---------------------------------------------------------------------
        # Compute problem metrics
        # ---------------------------------------------------------------------
        if problems_df.empty:
            st.warning("No problem tags found in this date range.")
            return

        # Error units (for you now: this is literally the sum of 'total pieces with this problem' we captured as qty_short)
        problems_df["error_units"] = problems_df[["qty_short", "qty_heavy"]].fillna(0).sum(axis=1)

        # One row per tag to count "orders with issues"
        tag_level = (
            problems_df.groupby(
                ["tag_id", "date_found", "customer_name", "team_name", "problem_type"],
                as_index=False,
            )
            .agg(
                error_units=("error_units", "sum"),
            )
        )

        # Merge with baseline daily units to get error rate
        tag_level = tag_level.merge(daily_units, on="date_found", how="left")
        tag_level["total_units"] = tag_level["total_units"].fillna(0)

        tag_level["orders_with_issue"] = 1
        tag_level["error_rate"] = tag_level.apply(
            lambda row: (row["error_units"] / row["total_units"]) if row["total_units"] > 0 else 0.0,
            axis=1,
        )

        # Aggregate by customer
        cust_agg = (
            tag_level.groupby("customer_name", as_index=False)
            .agg(
                orders_with_issue=("orders_with_issue", "sum"),
                error_units=("error_units", "sum"),
                total_units=("total_units", "sum"),
            )
        )
        cust_agg["error_rate"] = cust_agg.apply(
            lambda row: (row["error_units"] / row["total_units"]) if row["total_units"] > 0 else 0.0,
            axis=1,
        )

        # For charts
        if sort_mode == "Highest error rate":
            cust_agg = cust_agg.sort_values("error_rate", ascending=False)
        elif sort_mode == "Most error units":
            cust_agg = cust_agg.sort_values("error_units", ascending=False)
        elif sort_mode == "Most problem tags":
            cust_agg = cust_agg.sort_values("orders_with_issue", ascending=False)
        elif sort_mode == "Customer name":
            cust_agg = cust_agg.sort_values("customer_name", ascending=True)

        # ---------------------------------------------------------------------
        # Charts
        # ---------------------------------------------------------------------
        st.subheader("Customer Error Overview")

        metric_cols = st.columns(4)
        with metric_cols[0]:
            total_orders_with_issues = int(tag_level["orders_with_issue"].sum())
            st.metric("Orders with Issues (tags)", f"{total_orders_with_issues:,}")
        with metric_cols[1]:
            total_error_units = int(tag_level["error_units"].sum())
            st.metric("Error Units (pieces in problem orders)", f"{total_error_units:,}")
        with metric_cols[2]:
            total_units_overall = int(daily_units["total_units"].sum())
            st.metric("Total Units Received", f"{total_units_overall:,}")
        with metric_cols[3]:
            if total_units_overall > 0:
                overall_error_rate = total_error_units / total_units_overall
            else:
                overall_error_rate = 0.0
            st.metric("Overall Error Rate", f"{overall_error_rate:.2%}")

        if not cust_agg.empty:
            fig1 = px.bar(
                cust_agg,
                x="customer_name",
                y="error_rate",
                title="Error Rate by Customer (error units / total units received)",
                labels={"customer_name": "Customer", "error_rate": "Error Rate"},
            )
            fig1.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig1, use_container_width=True)

            fig2 = px.bar(
                cust_agg,
                x="customer_name",
                y="error_units",
                title="Error Units by Customer (pieces in problem orders)",
                labels={"customer_name": "Customer", "error_units": "Error Units"},
            )
            fig2.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig2, use_container_width=True)

        # ---------------------------------------------------------------------
        # Detailed table
        # ---------------------------------------------------------------------
        st.subheader("Tag-Level Detail (Orders with Issues)")

        detail_df = tag_level[
            [
                "date_found",
                "customer_name",
                "team_name",
                "problem_type",
                "orders_with_issue",
                "error_units",
                "total_units",
                "error_rate",
            ]
        ].copy()
        detail_df["date_found"] = detail_df["date_found"].dt.strftime("%m/%d/%Y")
        detail_df["error_rate"] = (detail_df["error_rate"] * 100).round(2).astype(str) + "%"

        st.dataframe(detail_df, use_container_width=True, hide_index=True)

    # -------------------------------------------------------------------------
    # 4) ADMIN (CUSTOMERS, EMPLOYEES)
    # -------------------------------------------------------------------------
    elif menu == "⚙️ Admin":
        st.header("Admin")

        tab1, tab2 = st.tabs(["Customers", "Employees"])

        with tab1:
            st.subheader("Customers")
            customers_df = get_customers()
            st.dataframe(customers_df[["customer_name"]], use_container_width=True, hide_index=True)

            new_cust = st.text_input("Add new customer", placeholder="Type customer name…")
            if st.button("➕ Add Customer", use_container_width=True):
                cid = add_customer_if_needed(new_cust)
                st.success(f"Saved (or already existed). ID = {cid}")
                st.rerun()

        with tab2:
            st.subheader("Employees")
            employees_df = get_employees()
            st.dataframe(employees_df[["employee_name"]], use_container_width=True, hide_index=True)

            new_emp = st.text_input("Add new employee", placeholder="Type employee name…")
            if st.button("➕ Add Employee", use_container_width=True):
                add_employee(new_emp)
                st.success("Saved (or already existed).")
                st.rerun()


if __name__ == "__main__":
    main()
