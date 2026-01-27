import streamlit as st
import pandas as pd
from datetime import date, timedelta, datetime
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

SHORT_HEAVY_LINE_PROBLEM_TYPES = [
    "Short/ Heavy Items",
]

COLOR_MATCH_OPTIONS = [
    "",
    "Matches Packing Slip",
    "Does Not Match Packing Slip",
]

# TAGGING PRODUCTION CONFIG
TAGGING_EMPLOYEES = [
    "Jay K", "Kristin H", "Robin H", "Scott F", "Andie D",
    "Yesenia A", "Montana M", "Izzy P", "Joey Q", "Randi R", "Steve Z"
]

TAGGING_CUSTOMERS = ["Del Sol", "Cariloha", "Purpose Built"]

# Production rates per 8-hour day
HANG_TAG_DAILY_RATE = 800
STICKER_DAILY_RATE = 2400

# caching DB URL
@st.cache_resource
def get_engine():
    from sqlalchemy import create_engine
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
        # Existing tables
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

        # NEW: Tagging Production Tables
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS tagging_employees (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    employee_name TEXT NOT NULL UNIQUE
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS tagging_customers (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    customer_name TEXT NOT NULL UNIQUE
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS tagging_production (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    production_date DATE NOT NULL,
                    employee_id INTEGER NOT NULL REFERENCES tagging_employees(id),
                    customer_id INTEGER NOT NULL REFERENCES tagging_customers(id),
                    hang_tags_qty INTEGER DEFAULT 0,
                    stickers_qty INTEGER DEFAULT 0,
                    date_entered TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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


# =============================================================================
# TAGGING PRODUCTION DB HELPERS
# =============================================================================

def get_tagging_employees() -> pd.DataFrame:
    eng = get_engine()
    with eng.connect() as conn:
        df = pd.read_sql(text("SELECT id, employee_name FROM tagging_employees ORDER BY employee_name"), conn)
    return df


def get_tagging_customers() -> pd.DataFrame:
    eng = get_engine()
    with eng.connect() as conn:
        df = pd.read_sql(text("SELECT id, customer_name FROM tagging_customers ORDER BY customer_name"), conn)
    return df


def add_tagging_employee(name: str) -> int:
    name = name.strip()
    if not name:
        raise ValueError("Employee name cannot be empty.")
    eng = get_engine()
    with eng.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO tagging_employees (employee_name)
                VALUES (:name)
                ON CONFLICT (employee_name) DO UPDATE SET employee_name = EXCLUDED.employee_name
                RETURNING id
                """
            ),
            {"name": name},
        )
        eid = result.scalar_one()
    return eid


def add_tagging_customer(name: str) -> int:
    name = name.strip()
    if not name:
        raise ValueError("Customer name cannot be empty.")
    eng = get_engine()
    with eng.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO tagging_customers (customer_name)
                VALUES (:name)
                ON CONFLICT (customer_name) DO UPDATE SET customer_name = EXCLUDED.customer_name
                RETURNING id
                """
            ),
            {"name": name},
        )
        cid = result.scalar_one()
    return cid


def load_default_tagging_data():
    """Load default employees and customers for tagging"""
    for emp in TAGGING_EMPLOYEES:
        try:
            add_tagging_employee(emp)
        except:
            pass
    
    for cust in TAGGING_CUSTOMERS:
        try:
            add_tagging_customer(cust)
        except:
            pass


def submit_tagging_production(production_date, employee_id, customer_id, hang_tags_qty, stickers_qty):
    """Submit tagging production record"""
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO tagging_production (production_date, employee_id, customer_id, hang_tags_qty, stickers_qty)
                VALUES (:prod_date, :emp_id, :cust_id, :hang_qty, :stick_qty)
                """
            ),
            {
                "prod_date": production_date,
                "emp_id": employee_id,
                "cust_id": customer_id,
                "hang_qty": hang_tags_qty,
                "stick_qty": stickers_qty,
            },
        )


def get_tagging_production_data(start_date, end_date) -> pd.DataFrame:
    """Get tagging production data for date range"""
    eng = get_engine()
    with eng.connect() as conn:
        df = pd.read_sql(
            text(
                """
                SELECT 
                    tp.id,
                    tp.production_date,
                    te.employee_name,
                    tc.customer_name,
                    tp.hang_tags_qty,
                    tp.stickers_qty,
                    tp.date_entered
                FROM tagging_production tp
                JOIN tagging_employees te ON tp.employee_id = te.id
                JOIN tagging_customers tc ON tp.customer_id = tc.id
                WHERE tp.production_date BETWEEN :start_date AND :end_date
                ORDER BY tp.production_date DESC, te.employee_name
                """
            ),
            conn,
            params={"start_date": start_date, "end_date": end_date},
        )
    return df


# =============================================================================
# TAGGING PRODUCTION PAGE
# =============================================================================

def tagging_production_submission_page():
    st.header("Tagging Production Submission")
    
    # Initialize session state for form
    if 'tagging_submitted' not in st.session_state:
        st.session_state.tagging_submitted = False
    
    if 'include_stickers' not in st.session_state:
        st.session_state.include_stickers = False
    
    # Show success message if just submitted
    if st.session_state.tagging_submitted:
        st.success("✅ Production submitted successfully!")
        if st.button("Submit Another Entry"):
            st.session_state.tagging_submitted = False
            st.session_state.include_stickers = False
            st.rerun()
        return
    
    # Load employees and customers
    employees_df = get_tagging_employees()
    customers_df = get_tagging_customers()
    
    if employees_df.empty or customers_df.empty:
        st.warning("⚠️ No employees or customers found. Loading defaults...")
        load_default_tagging_data()
        st.rerun()
    
    # Form
    with st.form("tagging_production_form"):
        st.markdown("### Production Details")
        
        col1, col2 = st.columns(2)
        
        with col1:
            production_date = st.date_input(
                "Production Date *",
                value=date.today(),
                max_value=date.today()
            )
            
            employee_name = st.selectbox(
                "Employee *",
                options=employees_df["employee_name"].tolist()
            )
        
        with col2:
            customer_name = st.selectbox(
                "Customer *",
                options=customers_df["customer_name"].tolist()
            )
        
        st.markdown("---")
        st.markdown("### Production Quantities")
        
        # Hang Tags (always visible)
        hang_tags_qty = st.number_input(
            "Hang Tags Quantity",
            min_value=0,
            value=0,
            step=50,
            help=f"Daily goal: {HANG_TAG_DAILY_RATE} tags"
        )
        
        # Toggle for stickers
        include_stickers = st.checkbox(
            "➕ Add Stickers",
            value=st.session_state.include_stickers
        )
        
        stickers_qty = 0
        if include_stickers:
            st.session_state.include_stickers = True
            stickers_qty = st.number_input(
                "Stickers Quantity",
                min_value=0,
                value=0,
                step=100,
                help=f"Daily goal: {STICKER_DAILY_RATE} stickers"
            )
        
        submitted = st.form_submit_button("💾 Submit Production", use_container_width=True)
        
        if submitted:
            # Validation
            if hang_tags_qty == 0 and stickers_qty == 0:
                st.error("❌ Please enter at least one quantity (Hang Tags or Stickers)")
            else:
                # Get IDs
                employee_id = employees_df[employees_df["employee_name"] == employee_name]["id"].values[0]
                customer_id = customers_df[customers_df["customer_name"] == customer_name]["id"].values[0]
                
                # Submit
                submit_tagging_production(
                    production_date,
                    employee_id,
                    customer_id,
                    hang_tags_qty,
                    stickers_qty
                )
                
                st.session_state.tagging_submitted = True
                st.rerun()


def tagging_production_analytics_page():
    st.header("Tagging Production Analytics")
    
    # Date range selector
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input(
            "Start Date",
            value=date.today() - timedelta(days=7)
        )
    with col2:
        end_date = st.date_input(
            "End Date",
            value=date.today()
        )
    
    # Get data
    df = get_tagging_production_data(start_date, end_date)
    
    if df.empty:
        st.info("📭 No production data found for this date range.")
        return
    
    # Convert date
    df['production_date'] = pd.to_datetime(df['production_date'])
    
    # Calculate totals and goals
    total_hang_tags = df['hang_tags_qty'].sum()
    total_stickers = df['stickers_qty'].sum()
    
    # Count unique employees per day per type
    hang_tag_days = df[df['hang_tags_qty'] > 0].groupby('production_date').size().sum()
    sticker_days = df[df['stickers_qty'] > 0].groupby('production_date').size().sum()
    
    hang_tag_goal = hang_tag_days * HANG_TAG_DAILY_RATE
    sticker_goal = sticker_days * STICKER_DAILY_RATE
    
    # Key Metrics
    st.markdown("### 📊 Key Metrics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Hang Tags", f"{total_hang_tags:,}")
        if hang_tag_goal > 0:
            pct = (total_hang_tags / hang_tag_goal) * 100
            st.caption(f"Goal: {hang_tag_goal:,} ({pct:.1f}%)")
    
    with col2:
        st.metric("Total Stickers", f"{total_stickers:,}")
        if sticker_goal > 0:
            pct = (total_stickers / sticker_goal) * 100
            st.caption(f"Goal: {sticker_goal:,} ({pct:.1f}%)")
    
    with col3:
        unique_employees = df['employee_name'].nunique()
        st.metric("Active Employees", unique_employees)
    
    with col4:
        total_entries = len(df)
        st.metric("Total Entries", total_entries)
    
    st.markdown("---")
    
    # Top Performers
    st.markdown("### 🏆 Top Performers")
    
    performer_df = df.groupby('employee_name').agg({
        'hang_tags_qty': 'sum',
        'stickers_qty': 'sum'
    }).reset_index()
    
    performer_df['total_production'] = performer_df['hang_tags_qty'] + performer_df['stickers_qty']
    performer_df = performer_df.sort_values('total_production', ascending=False)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Hang Tags Leaders")
        hang_leaders = performer_df.nlargest(5, 'hang_tags_qty')[['employee_name', 'hang_tags_qty']]
        hang_leaders.columns = ['Employee', 'Hang Tags']
        st.dataframe(hang_leaders, use_container_width=True, hide_index=True)
    
    with col2:
        st.markdown("#### Stickers Leaders")
        stick_leaders = performer_df.nlargest(5, 'stickers_qty')[['employee_name', 'stickers_qty']]
        stick_leaders.columns = ['Employee', 'Stickers']
        st.dataframe(stick_leaders, use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    # Daily Production Chart
    st.markdown("### 📈 Daily Production Trend")
    
    daily = df.groupby('production_date').agg({
        'hang_tags_qty': 'sum',
        'stickers_qty': 'sum'
    }).reset_index()
    
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        x=daily['production_date'],
        y=daily['hang_tags_qty'],
        name='Hang Tags',
        marker_color='lightblue'
    ))
    
    fig.add_trace(go.Bar(
        x=daily['production_date'],
        y=daily['stickers_qty'],
        name='Stickers',
        marker_color='lightgreen'
    ))
    
    fig.update_layout(
        title="Daily Production by Type",
        xaxis_title="Date",
        yaxis_title="Quantity",
        barmode='group',
        hovermode='x unified'
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("---")
    
    # Production by Customer
    st.markdown("### 👥 Production by Customer")
    
    customer_df = df.groupby('customer_name').agg({
        'hang_tags_qty': 'sum',
        'stickers_qty': 'sum'
    }).reset_index()
    
    fig = px.bar(
        customer_df,
        x='customer_name',
        y=['hang_tags_qty', 'stickers_qty'],
        title="Production Volume by Customer",
        labels={'value': 'Quantity', 'customer_name': 'Customer'},
        barmode='group'
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("---")
    
    # Raw Data Table
    st.markdown("### 📋 All Production Records")
    
    display_df = df.copy()
    display_df['production_date'] = display_df['production_date'].dt.strftime('%Y-%m-%d')
    display_df = display_df[['production_date', 'employee_name', 'customer_name', 'hang_tags_qty', 'stickers_qty']]
    display_df.columns = ['Date', 'Employee', 'Customer', 'Hang Tags', 'Stickers']
    
    st.dataframe(display_df, use_container_width=True, hide_index=True)


def tagging_management_page():
    st.header("Tagging Production Management")
    
    tab1, tab2 = st.tabs(["➕ Add Employee", "➕ Add Customer"])
    
    with tab1:
        st.markdown("### Add New Employee")
        
        new_employee = st.text_input("Employee Name", placeholder="First Name + Last Initial (e.g., Jay K)")
        
        if st.button("➕ Add Employee", type="primary"):
            if not new_employee:
                st.error("❌ Employee name cannot be empty!")
            else:
                try:
                    add_tagging_employee(new_employee)
                    st.success(f"✅ Employee '{new_employee}' added successfully!")
                    st.balloons()
                except Exception as e:
                    st.error(f"❌ Error: {e}")
        
        st.markdown("---")
        st.markdown("### Current Employees")
        
        employees_df = get_tagging_employees()
        st.dataframe(employees_df[['employee_name']], use_container_width=True, hide_index=True)
    
    with tab2:
        st.markdown("### Add New Customer")
        
        new_customer = st.text_input("Customer Name", placeholder="e.g., New Customer LLC")
        
        if st.button("➕ Add Customer", type="primary"):
            if not new_customer:
                st.error("❌ Customer name cannot be empty!")
            else:
                try:
                    add_tagging_customer(new_customer)
                    st.success(f"✅ Customer '{new_customer}' added successfully!")
                    st.balloons()
                except Exception as e:
                    st.error(f"❌ Error: {e}")
        
        st.markdown("---")
        st.markdown("### Current Customers")
        
        customers_df = get_tagging_customers()
        st.dataframe(customers_df[['customer_name']], use_container_width=True, hide_index=True)


# =============================================================================
# MAIN APP
# =============================================================================

def main():
    st.set_page_config(
        page_title="SilverScreen Operations Dashboard",
        page_icon="🏭",
        layout="wide"
    )
    
    # Initialize DB
    init_db()
    load_default_tagging_data()
    
    # Sidebar
    with st.sidebar:
        try:
            st.image("silverscreen_logo.png", use_column_width=True)
        except:
            st.markdown("### 🏭 SilverScreen")
        
        st.markdown("---")
        st.markdown("### Navigation")
        
        menu = st.radio(
            "",
            [
                "🏷️ Tagging Production",
                "📊 Tagging Analytics",
                "⚙️ Tagging Management",
                "📦 Receiving (Original)",
            ],
            label_visibility="collapsed"
        )
    
    # Header
    st.markdown("<h1 style='text-align:center;'>SilverScreen Operations Dashboard</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center; font-size:14px; color:gray;'>Silverscreen Decoration & Fulfillment®</p>", unsafe_allow_html=True)
    st.markdown("---")
    
    # Route to pages
    if menu == "🏷️ Tagging Production":
        tagging_production_submission_page()
    
    elif menu == "📊 Tagging Analytics":
        tagging_production_analytics_page()
    
    elif menu == "⚙️ Tagging Management":
        tagging_management_page()
    
    elif menu == "📦 Receiving (Original)":
        st.info("Your original receiving app goes here - I left this placeholder for your existing code")


if __name__ == "__main__":
    main()
