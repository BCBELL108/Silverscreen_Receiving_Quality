import streamlit as st
import pandas as pd
from datetime import date
from sqlalchemy import text

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
    "OTHER", "OSFA",
]

SHORT_HEAVY_OPTIONS = ["", "Short", "Heavy", "Short/Heavy"]  # optional per-line


# =============================================================================
# DB CONNECTION (Neon via Streamlit Secrets)
# =============================================================================

@st.cache_resource
def get_engine():
    # Streamlit Secrets must include:
    # [connections.receiving]
    # url="postgresql://...."
    return st.connection("receiving", type="sql").engine


def init_db():
    """Create tables if they don't exist and seed initial employees."""
    eng = get_engine()
    with eng.begin() as conn:
        # Customers
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customers (
                id SERIAL PRIMARY KEY,
                customer_name TEXT UNIQUE NOT NULL,
                date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active INTEGER DEFAULT 1
            );
        """))

        # Employees (mistake-made-by)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS employees (
                id SERIAL PRIMARY KEY,
                employee_name TEXT UNIQUE NOT NULL,
                date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active INTEGER DEFAULT 1
            );
        """))

        # Problem tag header (one per submission)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS receiving_problem_tags (
                id SERIAL PRIMARY KEY,
                date_entered TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                date_found DATE NOT NULL,
                po_number TEXT NOT NULL,
                customer_id INTEGER NOT NULL REFERENCES customers(id),
                job_name TEXT NOT NULL,
                team_name TEXT NOT NULL,
                author_name TEXT NOT NULL,
                problem_type TEXT NOT NULL,
                mistake_employee_id INTEGER NULL REFERENCES employees(id),
                notes TEXT
            );
        """))

        # Problem tag lines (one-or-many per header)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS receiving_problem_lines (
                id SERIAL PRIMARY KEY,
                tag_id INTEGER NOT NULL REFERENCES receiving_problem_tags(id) ON DELETE CASCADE,
                short_heavy_tag TEXT,
                style_number TEXT NOT NULL,
                item_description TEXT NOT NULL,
                color TEXT NOT NULL,
                size TEXT NOT NULL,
                vendor_packing_slip_matches BOOLEAN,
                qty_short INTEGER,
                qty_heavy INTEGER
            );
        """))

    seed_employees()


def seed_employees():
    """Seed the initial list of employees (idempotent)."""
    initial = [
        "Joey Quayle",
        "Izzy Price",
        "Montana Marsh",
        "Scott Frank",
        "Andie Dunsmore",
        "Jay Lobos",
        "Randi Robertson",
        "Yesenia Alcala Villa",
    ]
    eng = get_engine()
    with eng.begin() as conn:
        for name in initial:
            conn.execute(
                text("""
                    INSERT INTO employees (employee_name)
                    VALUES (:name)
                    ON CONFLICT (employee_name) DO NOTHING;
                """),
                {"name": name},
            )


# =============================================================================
# DB HELPERS
# =============================================================================

def get_customers() -> pd.DataFrame:
    eng = get_engine()
    with eng.connect() as conn:
        return pd.read_sql(
            text("""
                SELECT id, customer_name
                FROM customers
                WHERE active = 1
                ORDER BY customer_name;
            """),
            conn,
        )


def add_customer(customer_name: str) -> None:
    customer_name = (customer_name or "").strip()
    if not customer_name:
        return
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO customers (customer_name)
                VALUES (:n)
                ON CONFLICT (customer_name) DO NOTHING;
            """),
            {"n": customer_name},
        )


def get_employees() -> pd.DataFrame:
    eng = get_engine()
    with eng.connect() as conn:
        return pd.read_sql(
            text("""
                SELECT id, employee_name
                FROM employees
                WHERE active = 1
                ORDER BY employee_name;
            """),
            conn,
        )


def add_employee(employee_name: str) -> None:
    employee_name = (employee_name or "").strip()
    if not employee_name:
        return
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO employees (employee_name)
                VALUES (:n)
                ON CONFLICT (employee_name) DO NOTHING;
            """),
            {"n": employee_name},
        )


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
    """
    Saves header + line items in a transaction.
    Returns the new tag_id.
    """
    eng = get_engine()
    with eng.begin() as conn:
        tag_id = conn.execute(
            text("""
                INSERT INTO receiving_problem_tags (
                    date_found, po_number, customer_id, job_name, team_name,
                    author_name, problem_type, mistake_employee_id, notes
                )
                VALUES (
                    :date_found, :po_number, :customer_id, :job_name, :team_name,
                    :author_name, :problem_type, :mistake_employee_id, :notes
                )
                RETURNING id;
            """),
            {
                "date_found": date_found,
                "po_number": po_number.strip(),
                "customer_id": int(customer_id),
                "job_name": job_name.strip(),
                "team_name": team_name,
                "author_name": author_name.strip(),
                "problem_type": problem_type,
                "mistake_employee_id": int(mistake_employee_id) if mistake_employee_id else None,
                "notes": (notes or "").strip(),
            },
        ).scalar_one()

        for ln in lines:
            conn.execute(
                text("""
                    INSERT INTO receiving_problem_lines (
                        tag_id, short_heavy_tag, style_number, item_description, color, size,
                        vendor_packing_slip_matches, qty_short, qty_heavy
                    )
                    VALUES (
                        :tag_id, :short_heavy_tag, :style_number, :item_description, :color, :size,
                        :vendor_packing_slip_matches, :qty_short, :qty_heavy
                    );
                """),
                {
                    "tag_id": int(tag_id),
                    "short_heavy_tag": (ln.get("short_heavy_tag") or None),
                    "style_number": ln["style_number"].strip(),
                    "item_description": ln["item_description"].strip(),
                    "color": ln["color"].strip(),
                    "size": ln["size"],
                    "vendor_packing_slip_matches": ln.get("vendor_packing_slip_matches", None),
                    "qty_short": ln.get("qty_short", None),
                    "qty_heavy": ln.get("qty_heavy", None),
                },
            )

    return int(tag_id)


# =============================================================================
# UI HELPERS
# =============================================================================

def ensure_line_state():
    if "lines" not in st.session_state:
        st.session_state["lines"] = [default_line()]

def default_line():
    return {
        "short_heavy_tag": "",
        "style_number": "",
        "item_description": "",
        "color": "",
        "size": "M",
        "vendor_packing_slip_matches": None,
        "qty_short": None,
        "qty_heavy": None,
    }

def validate_submission(header: dict, lines: list[dict]) -> list[str]:
    errors = []

    # Header required fields
    if not header.get("po_number", "").strip():
        errors.append("PO# is required.")
    if not header.get("job_name", "").strip():
        errors.append("Job Name is required.")
    if not header.get("author_name", "").strip():
        errors.append("Author is required.")
    if not header.get("customer_id"):
        errors.append("Customer is required.")
    if not header.get("team_name"):
        errors.append("Team Name is required.")
    if not header.get("problem_type"):
        errors.append("Problem Type is required.")
    if not header.get("date_found"):
        errors.append("Date Found is required.")

    # At least one line
    if not lines or len(lines) == 0:
        errors.append("At least one SKU/problem line is required.")
        return errors

    # Line required fields
    for i, ln in enumerate(lines, start=1):
        if not (ln.get("style_number", "").strip()):
            errors.append(f"Line {i}: STYLE# is required.")
        if not (ln.get("item_description", "").strip()):
            errors.append(f"Line {i}: ITEM DESCRIPTION is required.")
        if not (ln.get("color", "").strip()):
            errors.append(f"Line {i}: COLOR is required.")
        if ln.get("size") not in SIZE_OPTIONS:
            errors.append(f"Line {i}: SIZE must be one of the allowed options.")

        sh = ln.get("short_heavy_tag") or ""
        if sh and sh not in SHORT_HEAVY_OPTIONS:
            errors.append(f"Line {i}: Short/Heavy tag is invalid.")

        # Optional: if they enter qty, it should be >= 0
        for field in ["qty_short", "qty_heavy"]:
            val = ln.get(field, None)
            if val is not None and val < 0:
                errors.append(f"Line {i}: {field} cannot be negative.")

    return errors


# =============================================================================
# APP
# =============================================================================

def main():
    st.set_page_config(page_title="Receiving Issues Dashboard", page_icon="📦", layout="wide")

    # Connection check
    try:
        eng = get_engine()
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        st.error("❌ Database NOT connected (check Streamlit secrets + Neon connection string).")
        st.exception(e)
        return

    init_db()

    st.markdown("<h1 style='text-align:center;'>Receiving Issues & Problem Tags</h1>", unsafe_allow_html=True)
    st.markdown("---")

    with st.sidebar:
        st.markdown("### Navigation")
        menu = st.radio(
            "",
            [
                "📝 Problem Tag Submission",
                "📋 View Submissions",
                "👥 Manage Lists",
            ],
            label_visibility="collapsed",
        )

    # -------------------------------------------------------------------------
    # 1) SUBMISSION TAB
    # -------------------------------------------------------------------------
    if menu == "📝 Problem Tag Submission":
        st.header("Problem Tag Submission")

        customers_df = get_customers()
        employees_df = get_employees()

        customer_options = ["-- Select Customer --"] + customers_df["customer_name"].tolist()
        employee_options = ["-- Unknown / Not Set --"] + employees_df["employee_name"].tolist()

        # Header fields
        c1, c2, c3 = st.columns(3)
        with c1:
            date_found = st.date_input("Date Found *", value=date.today())
            po_number = st.text_input("PO# *", placeholder="e.g., PO-12345")
        with c2:
            customer_name = st.selectbox("Customer Name *", customer_options)
            job_name = st.text_input("Job Name *", placeholder="e.g., Spring Promo Kit")
        with c3:
            team_name = st.selectbox("Team Name *", TEAM_OPTIONS)
            author_name = st.text_input("Author (who is submitting) *", placeholder="Type name...")

        c4, c5 = st.columns(2)
        with c4:
            problem_type = st.selectbox("Problem Type *", PROBLEM_TYPES)
        with c5:
            mistake_name = st.selectbox("Mistake Made By (optional)", employee_options)

        notes = st.text_area("Notes (optional)", placeholder="Anything helpful about what was found / how it was resolved...")

        # Resolve IDs
        customer_id = None
        if customer_name != "-- Select Customer --":
            customer_id = int(customers_df.loc[customers_df["customer_name"] == customer_name, "id"].values[0])

        mistake_employee_id = None
        if mistake_name != "-- Unknown / Not Set --":
            mistake_employee_id = int(employees_df.loc[employees_df["employee_name"] == mistake_name, "id"].values[0])

        st.markdown("---")
        st.subheader("SKU / Problem Lines (add as many as needed)")

        ensure_line_state()

        # Dynamic line editor
        for idx, ln in enumerate(st.session_state["lines"]):
            with st.container(border=True):
                top = st.columns([2, 2, 2, 2, 1])
                with top[0]:
                    ln["short_heavy_tag"] = st.selectbox(
                        "Short/Heavy Tag (optional)",
                        SHORT_HEAVY_OPTIONS,
                        index=SHORT_HEAVY_OPTIONS.index(ln.get("short_heavy_tag", "")) if ln.get("short_heavy_tag", "") in SHORT_HEAVY_OPTIONS else 0,
                        key=f"sh_{idx}",
                    )
                with top[1]:
                    ln["style_number"] = st.text_input("STYLE# *", value=ln.get("style_number", ""), key=f"style_{idx}")
                with top[2]:
                    ln["item_description"] = st.text_input("ITEM DESCRIPTION *", value=ln.get("item_description", ""), key=f"desc_{idx}")
                with top[3]:
                    ln["color"] = st.text_input("COLOR *", value=ln.get("color", ""), key=f"color_{idx}")
                with top[4]:
                    ln["size"] = st.selectbox(
                        "SIZE *",
                        SIZE_OPTIONS,
                        index=SIZE_OPTIONS.index(ln.get("size", "M")) if ln.get("size", "M") in SIZE_OPTIONS else SIZE_OPTIONS.index("M"),
                        key=f"size_{idx}",
                    )

                bottom = st.columns([2, 1, 1, 1])
                with bottom[0]:
                    ln["vendor_packing_slip_matches"] = st.checkbox(
                        "Vendor packing slip matches what we received? (optional)",
                        value=bool(ln.get("vendor_packing_slip_matches")) if ln.get("vendor_packing_slip_matches") is not None else False,
                        key=f"ps_{idx}",
                    )
                with bottom[1]:
                    ln["qty_short"] = st.number_input(
                        "Qty Short (optional)",
                        min_value=0,
                        step=1,
                        value=int(ln["qty_short"]) if ln.get("qty_short") is not None else 0,
                        key=f"qtys_{idx}",
                    )
                with bottom[2]:
                    ln["qty_heavy"] = st.number_input(
                        "Qty Heavy (optional)",
                        min_value=0,
                        step=1,
                        value=int(ln["qty_heavy"]) if ln.get("qty_heavy") is not None else 0,
                        key=f"qtyh_{idx}",
                    )
                with bottom[3]:
                    if st.button("Remove line", key=f"rm_{idx}", use_container_width=True):
                        st.session_state["lines"].pop(idx)
                        if len(st.session_state["lines"]) == 0:
                            st.session_state["lines"] = [default_line()]
                        st.rerun()

        controls = st.columns([1, 1, 2])
        with controls[0]:
            if st.button("➕ Add another line", use_container_width=True):
                st.session_state["lines"].append(default_line())
                st.rerun()

        with controls[1]:
            if st.button("🧹 Clear lines", use_container_width=True):
                st.session_state["lines"] = [default_line()]
                st.rerun()

        st.markdown("---")

        # Prepare payload
        header = {
            "date_found": date_found,
            "po_number": po_number,
            "customer_id": customer_id,
            "job_name": job_name,
            "team_name": team_name,
            "author_name": author_name,
            "problem_type": problem_type,
            "mistake_employee_id": mistake_employee_id,
            "notes": notes,
        }

        # Normalize qty inputs: treat 0 as None if you prefer (optional)
        lines_payload = []
        for ln in st.session_state["lines"]:
            payload = dict(ln)
            # convert checkbox bool to nullable (keep as bool, DB accepts boolean)
            # convert qty 0 => None to reduce noise
            payload["qty_short"] = None if payload.get("qty_short", 0) == 0 else int(payload["qty_short"])
            payload["qty_heavy"] = None if payload.get("qty_heavy", 0) == 0 else int(payload["qty_heavy"])
            lines_payload.append(payload)

        if st.button("💾 Submit Problem Tag", type="primary", use_container_width=True):
            errs = validate_submission(header, lines_payload)
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
                st.success(f"✅ Saved Problem Tag (ID: {tag_id})")
                st.session_state["lines"] = [default_line()]

    # -------------------------------------------------------------------------
    # 2) VIEW SUBMISSIONS
    # -------------------------------------------------------------------------
    elif menu == "📋 View Submissions":
        st.header("View Submissions")

        eng = get_engine()
        with eng.connect() as conn:
            tags = pd.read_sql(
                text("""
                    SELECT
                        t.id,
                        t.date_entered,
                        t.date_found,
                        t.po_number,
                        c.customer_name,
                        t.job_name,
                        t.team_name,
                        t.author_name,
                        t.problem_type,
                        e.employee_name AS mistake_made_by,
                        t.notes
                    FROM receiving_problem_tags t
                    JOIN customers c ON t.customer_id = c.id
                    LEFT JOIN employees e ON t.mistake_employee_id = e.id
                    ORDER BY t.date_found DESC, t.date_entered DESC
                    LIMIT 500;
                """),
                conn,
            )

        if tags.empty:
            st.info("No submissions yet.")
            return

        st.dataframe(tags, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("View Lines for a Submission")

        tag_id = st.number_input("Enter Tag ID", min_value=1, step=1, value=int(tags.iloc[0]["id"]))
        with eng.connect() as conn:
            lines = pd.read_sql(
                text("""
                    SELECT
                        id,
                        short_heavy_tag,
                        style_number,
                        item_description,
                        color,
                        size,
                        vendor_packing_slip_matches,
                        qty_short,
                        qty_heavy
                    FROM receiving_problem_lines
                    WHERE tag_id = :tid
                    ORDER BY id ASC;
                """),
                conn,
                params={"tid": int(tag_id)},
            )

        st.dataframe(lines, use_container_width=True, hide_index=True)

    # -------------------------------------------------------------------------
    # 3) MANAGE LISTS
    # -------------------------------------------------------------------------
    elif menu == "👥 Manage Lists":
        st.header("Manage Lists")

        tab1, tab2 = st.tabs(["🏢 Customers", "👤 Employees"])

        with tab1:
            st.subheader("Customers")
            customers_df = get_customers()
            st.dataframe(customers_df[["customer_name"]], use_container_width=True, hide_index=True)

            new_cust = st.text_input("Add new customer", placeholder="Type customer name…")
            if st.button("➕ Add Customer", use_container_width=True):
                add_customer(new_cust)
                st.success("Saved (or already existed).")
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
