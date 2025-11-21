import streamlit as st
import pandas as pd
import plotly.express as px
import os
import sqlite3
from datetime import datetime, timedelta
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Shift Operations Portal V3",
    layout="wide",
    page_icon="🏭",
    initial_sidebar_state="expanded"
)

# --- DATABASE MANAGEMENT (SQLite) ---
DB_FILE = os.path.join("data", "shift_logs.db")

def init_db():
    """Initialize SQLite database with required tables"""
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 1. Reports Table (Header info)
    c.execute('''CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        shift TEXT,
        engineer TEXT,
        team_members TEXT,
        site_condition TEXT,
        radios_charged BOOLEAN,
        phones_working BOOLEAN,
        urgent_notes TEXT,
        other_tasks TEXT,
        submitted_at TEXT
    )''')
    
    # 2. Reactives Table
    c.execute('''CREATE TABLE IF NOT EXISTS reactives (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER,
        asset TEXT,
        time_called TEXT,
        time_back TEXT,
        fault TEXT,
        engineers INTEGER,
        description TEXT,
        downtime REAL,
        status TEXT,
        FOREIGN KEY(report_id) REFERENCES reports(id)
    )''')
    
    # 3. PPMs Table
    c.execute('''CREATE TABLE IF NOT EXISTS ppms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER,
        asset TEXT,
        ppm_id TEXT,
        status TEXT,
        comments TEXT,
        FOREIGN KEY(report_id) REFERENCES reports(id)
    )''')
    
    # 4. Spares Table
    c.execute('''CREATE TABLE IF NOT EXISTS spares (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER,
        art_number TEXT,
        description TEXT,
        location TEXT,
        category TEXT,
        quantity INTEGER,
        decision TEXT,
        FOREIGN KEY(report_id) REFERENCES reports(id)
    )''')
    
    conn.commit()
    conn.close()

# --- DATA LOADING & LOGIC ---
@st.cache_data
def load_master_data():
    # Assets
    assets_file = os.path.join("data", "assets.csv")
    if os.path.exists(assets_file):
        df = pd.read_csv(assets_file)
        assets = df.iloc[:, 0].unique().tolist()
    else:
        assets = ["Conveyor #1", "Palletiser #1", "Forklift #1", "Other"]

    # Spares
    spares_file = os.path.join("data", "spares.csv")
    spares_search = []
    spares_dict = {}
    if os.path.exists(spares_file):
        df = pd.read_csv(spares_file)
        df.columns = [c.strip() for c in df.columns]
        for _, row in df.iterrows():
            val = f"{row.get('Part Number','')} - {row.get('Description','')} - {row.get('Location','')}"
            spares_search.append(val)
            spares_dict[val] = {"ART": row.get('Part Number',''), "Desc": row.get('Description',''), "Loc": row.get('Location','')}
    spares_search.append("Other / Manual Entry")
    
    return assets, spares_search, spares_dict

def check_smart_ppms():
    """Load PPMs from schedule based on today's day"""
    ppm_file = os.path.join("data", "ppm_schedule.csv")
    today_day = datetime.now().strftime("%A") # e.g., "Friday"
    scheduled_ppms = []
    
    if os.path.exists(ppm_file):
        try:
            df = pd.read_csv(ppm_file)
            # Filter for Today OR 'Daily'
            mask = df['Day'].isin([today_day, 'Daily'])
            todays_tasks = df[mask]
            
            for _, row in todays_tasks.iterrows():
                scheduled_ppms.append({
                    "Asset": row['Asset'],
                    "PPM ID": row.get('Task Description', 'Scheduled Task'),
                    "Status": "In Progress", # Default to In Progress
                    "Comments": "Auto-scheduled"
                })
        except Exception:
            pass
    return scheduled_ppms

def check_carry_over_tasks():
    """Query DB for 'In Progress' tasks from previous shifts"""
    conn = sqlite3.connect(DB_FILE)
    # Get tasks that are NOT Complete
    df = pd.read_sql_query("SELECT * FROM reactives WHERE status != 'Complete'", conn)
    conn.close()
    
    carry_over = []
    if not df.empty:
        # In a real app, you might filter to ensure you don't re-import tasks already imported
        # For V3, we just show them
        for _, row in df.iterrows():
            carry_over.append({
                "Asset": row['asset'],
                "Time Called": row['time_called'],
                "Time Back": row['time_back'],
                "Fault": row['fault'],
                "Engineers": row['engineers'],
                "Description": f"[CARRY OVER] {row['description']}",
                "Downtime (min)": row['downtime'],
                "Status": row['status']
            })
    return carry_over

# --- CUSTOM CSS ---
st.markdown("""
    <style>
    .main-header { background-color: #FFD100; padding: 1.5rem; border-radius: 4px; color: #000000; border-bottom: 4px solid #000000; }
    .main-header h1 { color: #000000; margin: 0; font-size: 1.8rem; font-weight: 800; text-transform: uppercase; }
    .section-header { background: #ffffff; padding: 0.75rem 1rem; border-left: 6px solid #FFD100; border-bottom: 1px solid #e0e0e0; margin: 1.5rem 0 1rem 0; }
    .section-header h3 { color: #1A1A1A; margin: 0; font-size: 1.2rem; font-weight: 700; }
    .stMetric { background-color: #ffffff; padding: 1rem; border-left: 5px solid #000000; border-radius: 4px; border: 1px solid #e0e0e0; }
    button[kind="primary"] { color: #000000 !important; border: 1px solid #d4af37; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# --- INITIALIZATION ---
init_db()
ASSETS_LIST, SPARES_SEARCH_LIST, SPARES_DATA_DICT = load_master_data()

def init_session_state():
    if 'reactives' not in st.session_state: st.session_state.reactives = []
    if 'ppms' not in st.session_state: st.session_state.ppms = []
    if 'spares' not in st.session_state: st.session_state.spares = []
    if 'current_user' not in st.session_state: st.session_state.current_user = "John Smith"
    if 'editing_report_id' not in st.session_state: st.session_state.editing_report_id = None
    if 'carry_over_checked' not in st.session_state: st.session_state.carry_over_checked = False
    
    # Spares widgets
    if 'spare_search_box' not in st.session_state: st.session_state.spare_search_box = "Select a part..."
    
    # FIX: Initialize text fields as strings
    for key in ['s_art', 's_desc', 's_loc', 's_cat', 's_dec']:
        if key not in st.session_state: st.session_state[key] = ""

    # FIX: Initialize Quantity as a Number (Integer), NOT a string
    if 's_qty' not in st.session_state or isinstance(st.session_state.s_qty, str):
        st.session_state.s_qty = 1

# --- DB ACTIONS ---
def save_report_to_db(report_data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Check if updating existing or creating new
    if st.session_state.editing_report_id:
        # UPDATE existing report (Simplified: Update header, delete details, re-insert details)
        rid = st.session_state.editing_report_id
        c.execute('''UPDATE reports SET date=?, shift=?, engineer=?, team_members=?, site_condition=?, 
                     radios_charged=?, phones_working=?, urgent_notes=?, other_tasks=?, submitted_at=? WHERE id=?''',
                  (report_data['date'], report_data['shift'], report_data['engineer'], report_data['team_members'],
                   report_data['site_condition'], report_data['radios_charged'], report_data['phones_working'],
                   report_data['urgent_notes'], report_data['other_tasks'], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), rid))
        # Clear old details to re-insert (easiest way to handle edits)
        c.execute("DELETE FROM reactives WHERE report_id=?", (rid,))
        c.execute("DELETE FROM ppms WHERE report_id=?", (rid,))
        c.execute("DELETE FROM spares WHERE report_id=?", (rid,))
    else:
        # INSERT new report
        c.execute('''INSERT INTO reports (date, shift, engineer, team_members, site_condition, radios_charged, phones_working, urgent_notes, other_tasks, submitted_at)
                     VALUES (?,?,?,?,?,?,?,?,?,?)''',
                  (report_data['date'], report_data['shift'], report_data['engineer'], report_data['team_members'],
                   report_data['site_condition'], report_data['radios_charged'], report_data['phones_working'],
                   report_data['urgent_notes'], report_data['other_tasks'], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        rid = c.lastrowid

    # Insert Details
    for r in st.session_state.reactives:
        c.execute("INSERT INTO reactives (report_id, asset, time_called, time_back, fault, engineers, description, downtime, status) VALUES (?,?,?,?,?,?,?,?,?)",
                  (rid, r['Asset'], r['Time Called'], r['Time Back'], r['Fault'], r['Engineers'], r['Description'], r['Downtime (min)'], r.get('Status', 'Complete')))
    
    for p in st.session_state.ppms:
        c.execute("INSERT INTO ppms (report_id, asset, ppm_id, status, comments) VALUES (?,?,?,?,?)",
                  (rid, p['Asset'], p['PPM ID'], p['Status'], p['Comments']))
        
    for s in st.session_state.spares:
        c.execute("INSERT INTO spares (report_id, art_number, description, location, category, quantity, decision) VALUES (?,?,?,?,?,?,?)",
                  (rid, s['ART #'], s['Description'], s['Location'], s['Category'], s['Quantity'], s['Decision']))
    
    conn.commit()
    conn.close()
    return rid

def load_report_for_editing(report_id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Load Header
    r = c.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if not r: return False
    
    # Populate Session State
    st.session_state.editing_report_id = report_id
    # Note: Form fields in Streamlit are tricky to pre-fill from DB triggers without complex state management.
    # For V3, we populate the LISTS which is the most important part.
    
    # Load Reactives
    reactives = c.execute("SELECT * FROM reactives WHERE report_id=?", (report_id,)).fetchall()
    st.session_state.reactives = []
    for row in reactives:
        st.session_state.reactives.append({
            "Asset": row['asset'], "Time Called": row['time_called'], "Time Back": row['time_back'],
            "Fault": row['fault'], "Engineers": row['engineers'], "Description": row['description'],
            "Downtime (min)": row['downtime'], "Status": row['status']
        })

    # Load PPMs
    ppms = c.execute("SELECT * FROM ppms WHERE report_id=?", (report_id,)).fetchall()
    st.session_state.ppms = []
    for row in ppms:
        st.session_state.ppms.append({
            "Asset": row['asset'], "PPM ID": row['ppm_id'], "Status": row['status'], "Comments": row['comments']
        })
        
    # Load Spares
    spares = c.execute("SELECT * FROM spares WHERE report_id=?", (report_id,)).fetchall()
    st.session_state.spares = []
    for row in spares:
        st.session_state.spares.append({
            "ART #": row['art_number'], "Description": row['description'], "Location": row['location'],
            "Category": row['category'], "Quantity": row['quantity'], "Decision": row['decision']
        })
    
    conn.close()
    return True

# --- HELPER FUNCTIONS (PDF/Excel) ---
# (Kept same as V2.3, condensed for brevity)
def calculate_downtime(t1, t2):
    if t1 and t2:
        return (datetime.combine(datetime.today(), t2) - datetime.combine(datetime.today(), t1)).total_seconds() / 60
    return 0

def generate_pdf_report(shift_data, reactives, ppms, spares):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=18)
    elements = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('T', parent=styles['Heading1'], fontSize=24, textColor=colors.black, alignment=TA_CENTER, spaceAfter=20)
    h2_style = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=14, textColor=colors.black, borderWidth=2, borderColor=colors.HexColor('#FFD100'), backColor=colors.HexColor('#f4f4f4'), spaceBefore=10, borderPadding=5)
    
    elements.append(Paragraph(f"SHIFT REPORT #{st.session_state.get('editing_report_id', 'NEW')}", title_style))
    
    # Shift Info
    elements.append(Paragraph("SHIFT DETAILS", h2_style))
    data = [[k, str(v)] for k, v in shift_data.items() if k not in ['reactives','ppms','spares']]
    t = Table(data, colWidths=[2*inch, 4*inch])
    t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 1, colors.grey), ('BACKGROUND', (0,0), (0,-1), colors.whitesmoke)]))
    elements.append(t)
    
    # Reactives
    if reactives:
        elements.append(Paragraph(f"REACTIVE TASKS ({len(reactives)})", h2_style))
        data = [['Asset','Fault','Status','Downtime']] + [[r['Asset'], r['Fault'], r.get('Status',''), str(r.get('Downtime (min)',0))] for r in reactives]
        t = Table(data, colWidths=[2*inch, 1.5*inch, 1*inch, 1*inch])
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.black), ('TEXTCOLOR',(0,0),(-1,0),colors.HexColor('#FFD100')), ('GRID',(0,0),(-1,-1),1,colors.black)]))
        elements.append(t)

    doc.build(elements)
    buffer.seek(0)
    return buffer

# --- PAGE 1: SHIFT LOG ---
def show_shift_log():
    st.markdown('<div class="main-header"><h1>📝 Shift Operations Log (V3)</h1><p>Database Connected • Smart Scheduling • Auto-Carryover</p></div>', unsafe_allow_html=True)

    if st.session_state.editing_report_id:
        st.warning(f"✏️ EDITING REPORT ID: {st.session_state.editing_report_id}")
        if st.button("❌ Cancel Editing"):
            st.session_state.editing_report_id = None
            st.session_state.reactives = []
            st.session_state.ppms = []
            st.session_state.spares = []
            st.rerun()

    # AUTO-LOGIC: Run once per session
    if not st.session_state.carry_over_checked and not st.session_state.editing_report_id:
        # 1. Carry Over
        carry_over = check_carry_over_tasks()
        if carry_over:
            st.session_state.reactives.extend(carry_over)
            st.toast(f"🔄 Imported {len(carry_over)} 'In Progress' tasks from previous shifts!", icon="🔄")
        
        # 2. Smart PPMs
        smart_ppms = check_smart_ppms()
        if smart_ppms:
            st.session_state.ppms.extend(smart_ppms)
            st.toast(f"📅 Scheduled {len(smart_ppms)} PPM tasks for today!", icon="📅")
            
        st.session_state.carry_over_checked = True

    # SECTION A: DETAILS
    st.markdown('<div class="section-header"><h3>👤 Shift Details</h3></div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    with c1: s_date = st.date_input("Date", datetime.now())
    with c2: s_shift = st.selectbox("Shift", ["Day Shift", "Night Shift"])
    with c3: s_eng = st.selectbox("Engineer", ["John Smith", "Sarah Jones", "Liam Peterson"])
    with c4: s_team = st.text_input("Team Members")

    # SECTION B: REACTIVES
    st.markdown('<div class="section-header"><h3>⚠️ Reactives</h3></div>', unsafe_allow_html=True)
    with st.expander("➕ Add Reactive Task", expanded=False):
        c1, c2, c3 = st.columns(3)
        r_asset = c1.selectbox("Asset", ASSETS_LIST)
        r_called = c2.time_input("Time Called")
        r_back = c3.time_input("Time Back")
        c1, c2, c3 = st.columns(3)
        r_fault = c1.selectbox("Fault", ["Electrical", "Mechanical", "Operational", "Other"])
        r_status = c2.selectbox("Status", ["Complete", "In Progress", "Awaiting Parts"])
        r_engs = c3.number_input("Engineers", 1, 5, 1)
        r_desc = st.text_area("Description")
        
        if st.button("Add Reactive"):
            dt = calculate_downtime(r_called, r_back)
            st.session_state.reactives.append({
                "Asset": r_asset, "Time Called": str(r_called), "Time Back": str(r_back),
                "Fault": r_fault, "Status": r_status, "Engineers": r_engs,
                "Description": r_desc, "Downtime (min)": round(dt, 1)
            })
            st.rerun()

    if st.session_state.reactives:
        st.dataframe(pd.DataFrame(st.session_state.reactives))

    # SECTION C: PPMs
    st.markdown('<div class="section-header"><h3>📋 PPMs</h3></div>', unsafe_allow_html=True)
    with st.expander("➕ Add PPM", expanded=False):
        c1, c2 = st.columns(2)
        p_asset = c1.selectbox("Asset", ASSETS_LIST, key="ppm_asset_sel")
        p_id = c2.text_input("Task ID/Desc")
        if st.button("Add PPM"):
            st.session_state.ppms.append({"Asset": p_asset, "PPM ID": p_id, "Status": "Complete", "Comments": ""})
            st.rerun()
            
    if st.session_state.ppms:
        st.dataframe(pd.DataFrame(st.session_state.ppms))

    # SECTION D: SPARES (With Autocomplete)
    st.markdown('<div class="section-header"><h3>🔧 Spares</h3></div>', unsafe_allow_html=True)
    def on_spare_sel():
        sel = st.session_state.spare_search_box
        if sel in SPARES_DATA_DICT:
            d = SPARES_DATA_DICT[sel]
            st.session_state.s_art = d['ART']
            st.session_state.s_desc = d['Desc']
            st.session_state.s_loc = d['Loc']
        elif "Manual" in sel:
             st.session_state.s_art = ""

    with st.expander("➕ Add Spare", expanded=False):
        st.selectbox("Search Part", ["Select..."] + SPARES_SEARCH_LIST, key="spare_search_box", on_change=on_spare_sel)
        c1, c2, c3 = st.columns(3)
        s_art = c1.text_input("ART #", key="s_art")
        s_desc = c2.text_input("Desc", key="s_desc")
        s_loc = c3.text_input("Loc", key="s_loc")
        c1, c2 = st.columns(2)
        s_qty = c1.number_input("Qty", 1, 100, 1, key="s_qty")
        s_dec = c2.selectbox("Decision", ["Used", "Quarantined"], key="s_dec")
        
        if st.button("Add Spare"):
            st.session_state.spares.append({
                "ART #": s_art, "Description": s_desc, "Location": s_loc,
                "Category": "Gen", "Quantity": s_qty, "Decision": s_dec
            })
            st.rerun()

    if st.session_state.spares:
        st.dataframe(pd.DataFrame(st.session_state.spares))

    # SUBMIT
    st.markdown("---")
    if st.button("💾 SAVE TO DATABASE", type="primary", use_container_width=True):
        report_data = {
            "date": str(s_date), "shift": s_shift, "engineer": s_eng, "team_members": s_team,
            "site_condition": "Normal", "radios_charged": True, "phones_working": True,
            "urgent_notes": "N/A", "other_tasks": "N/A"
        }
        rid = save_report_to_db(report_data)
        st.success(f"✅ Report #{rid} Saved/Updated successfully!")
        
        # PDF Gen
        pdf = generate_pdf_report(report_data, st.session_state.reactives, st.session_state.ppms, st.session_state.spares)
        st.download_button("Download PDF", pdf, f"Report_{rid}.pdf", "application/pdf")

# --- PAGE 2: DASHBOARD ---
def show_dashboard():
    st.markdown('<div class="main-header"><h1>📊 Manager Dashboard</h1></div>', unsafe_allow_html=True)
    
    t1, t2, t3 = st.tabs(["Current Shift", "Global Asset History", "Report Browser"])
    
    with t1:
        # Current Session Stats
        c1, c2, c3 = st.columns(3)
        c1.metric("Reactives (Session)", len(st.session_state.reactives))
        c2.metric("PPMs (Session)", len(st.session_state.ppms))
        c3.metric("Spares (Session)", len(st.session_state.spares))
        
        if st.session_state.reactives:
            df = pd.DataFrame(st.session_state.reactives)
            fig = px.pie(df, names='Fault', title='Fault Breakdown', color_discrete_sequence=['#FFD100', '#333333'])
            st.plotly_chart(fig, use_container_width=True)

    with t2:
        st.markdown("### 🔎 Global Asset Search")
        asset_search = st.selectbox("Select Asset to Analyze", ASSETS_LIST)
        
        if asset_search:
            conn = sqlite3.connect(DB_FILE)
            # Join reactives with reports to get dates
            query = """
                SELECT r.date, r.shift, r.engineer, t.fault, t.description, t.downtime, t.status 
                FROM reactives t 
                JOIN reports r ON t.report_id = r.id 
                WHERE t.asset = ? ORDER BY r.date DESC
            """
            df_history = pd.read_sql_query(query, conn, params=(asset_search,))
            conn.close()
            
            if not df_history.empty:
                c1, c2 = st.columns(2)
                c1.metric("Total Breakdowns", len(df_history))
                c2.metric("Total Downtime (All Time)", f"{df_history['downtime'].sum()} mins")
                
                st.dataframe(df_history, use_container_width=True)
            else:
                st.info("No recorded history for this asset in database.")

    with t3:
        st.markdown("### 📂 Report Browser (Edit/View)")
        conn = sqlite3.connect(DB_FILE)
        df_reports = pd.read_sql_query("SELECT id, date, shift, engineer, submitted_at FROM reports ORDER BY id DESC", conn)
        conn.close()
        
        if not df_reports.empty:
            st.dataframe(df_reports, use_container_width=True)
            
            c1, c2 = st.columns(2)
            report_id = c1.number_input("Enter Report ID to Load", min_value=1, step=1)
            if c2.button("📥 Load for Editing"):
                if load_report_for_editing(report_id):
                    st.success(f"Loaded Report #{report_id}. Go to 'Shift Log' to edit.")
                else:
                    st.error("Report ID not found.")

# --- MAIN ---
if __name__ == "__main__":
    init_session_state()
    
    with st.sidebar:
        st.markdown("## 🏭 SO Portal V3")
        page = st.radio("Navigate", ["Shift Log", "Dashboard"])
        st.info("System: SQLite DB Connected")
        
    if page == "Shift Log":
        show_shift_log()
    else:
        show_dashboard()