import streamlit as st
import pandas as pd
import plotly.express as px
import sqlite3
import os

# --- CONFIG ---
st.set_page_config(page_title="Manager Dashboard", layout="wide", page_icon="📊")
DB_FILE = os.path.join("data", "shift_logs.db")

# --- DATA LOADING ---
def load_data():
    if not os.path.exists(DB_FILE): return None, None, None
    conn = sqlite3.connect(DB_FILE)
    
    try:
        df_reps = pd.read_sql_query("SELECT * FROM reports", conn)
        df_react = pd.read_sql_query("SELECT r.date, r.shift, r.engineer, t.* FROM reactives t JOIN reports r ON t.report_id = r.id", conn)
        df_spares = pd.read_sql_query("SELECT * FROM spares_inventory", conn)
    except:
        conn.close()
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        
    conn.close()
    return df_reps, df_react, df_spares

# --- UI ---
st.markdown("""<style>.main-header {background-color: #FFD100; padding: 1rem; border-bottom: 3px solid black; color: black;}</style>""", unsafe_allow_html=True)
st.markdown('<div class="main-header"><h1>📊 OPERATIONS DASHBOARD</h1></div>', unsafe_allow_html=True)

df_reports, df_reactives, df_inventory = load_data()

if df_reports is None or df_reports.empty:
    st.warning("No data found. Please submit a shift report first using the Shift Log App.")
    st.stop()

tab1, tab2, tab3, tab4 = st.tabs(["📈 Overview", "🔎 Asset Reliability", "📦 Spares Inventory", "📂 Report Browser"])

# TAB 1: OVERVIEW
with tab1:
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("Total Shift Reports", len(df_reports))
    
    total_dt = df_reactives['downtime'].sum() / 60 if not df_reactives.empty else 0
    kpi2.metric("Total Downtime (Hrs)", f"{total_dt:.2f}")
    kpi3.metric("Reactive Events", len(df_reactives))
    
    # Calculate Availability (Mock calculation based on 12hr shifts)
    total_shift_hours = len(df_reports) * 12
    availability = ((total_shift_hours - total_dt) / total_shift_hours * 100) if total_shift_hours > 0 else 100
    kpi4.metric("Tech Availability %", f"{availability:.1f}%")
    
    if not df_reactives.empty:
        c1, c2 = st.columns(2)
        with c1:
            # Downtime by Asset
            fig = px.bar(df_reactives, x='date', y='downtime', color='asset', title="Daily Downtime by Asset")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            # Pareto of Faults
            fault_counts = df_reactives['fault'].value_counts().reset_index()
            fault_counts.columns = ['Fault Type', 'Count']
            fig2 = px.pie(fault_counts, values='Count', names='Fault Type', title="Common Fault Types", hole=0.4)
            st.plotly_chart(fig2, use_container_width=True)

# TAB 2: ASSET RELIABILITY (Feature 5)
with tab2:
    st.subheader("Asset Failure Analysis")
    assets = sorted(df_reactives['asset'].unique()) if not df_reactives.empty else []
    sel_asset = st.selectbox("Select Asset for Deep Dive", ["All"] + assets)
    
    filt_df = df_reactives if sel_asset == "All" else df_reactives[df_reactives['asset'] == sel_asset]
    
    if not filt_df.empty:
        # Reliability Metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Breakdown Count", len(filt_df))
        
        avg_dt = filt_df['downtime'].mean()
        m2.metric("MTTR (Mean Time To Repair)", f"{avg_dt:.1f} min")
        
        # MTBF Estimate (Days between failures)
        filt_df['date'] = pd.to_datetime(filt_df['date'])
        if len(filt_df) > 1:
            sorted_dates = filt_df['date'].sort_values()
            diffs = sorted_dates.diff().dt.total_seconds() / (3600*24) # in days
            mtbf = diffs.mean()
            m3.metric("MTBF (Est. Days)", f"{mtbf:.1f} days")
        else:
            m3.metric("MTBF", "N/A (Need >1 failure)")

        m4.metric("Total Cost (Est @ £50/hr)", f"£{(filt_df['downtime'].sum()/60)*50:.0f}")

        st.markdown("### 📜 Failure Log")
        st.dataframe(
            filt_df[['date', 'shift', 'engineer', 'fault', 'description', 'downtime', 'engineers']]
            .sort_values('date', ascending=False), 
            use_container_width=True
        )

# TAB 3: SPARES INVENTORY (Feature 6)
with tab3:
    st.subheader("Warehouse Stock Levels")
    
    # KPI Cards for Stock
    low_stock = df_inventory[df_inventory['stock_level'] <= df_inventory['min_stock_level']]
    
    k1, k2 = st.columns(2)
    k1.metric("Total SKUs", len(df_inventory))
    k2.metric("Items Below Min Level", len(low_stock), delta_color="inverse")
    
    if not low_stock.empty:
        st.error(f"⚠️ REORDER ALERT: {len(low_stock)} items are below minimum stock levels!")
        st.dataframe(low_stock, use_container_width=True)
    
    # Full Table with Editor (Manager can update stock)
    st.info("💡 Edit values in the table below to adjust stock levels manually.")
    edited_df = st.data_editor(
        df_inventory, 
        key="inventory_editor",
        column_config={
            "art_number": st.column_config.TextColumn("Art #", disabled=True),
            "stock_level": st.column_config.NumberColumn("Current Stock", min_value=0, format="%d"),
            "min_stock_level": st.column_config.NumberColumn("Min Level", min_value=0, format="%d"),
        },
        use_container_width=True
    )
    
    # Save Changes Button
    if st.button("💾 Update Inventory Database"):
        conn = sqlite3.connect(DB_FILE)
        edited_df.to_sql("spares_inventory", conn, if_exists="replace", index=False)
        conn.close()
        st.success("Inventory updated!")
        st.rerun()

# TAB 4: REPORT BROWSER (Feature 2)
with tab4:
    st.subheader("📁 Historical Shift Reports")
    
    # Filter UI
    c1, c2 = st.columns([1, 3])
    with c1:
        f_eng = st.selectbox("Filter by Engineer", ["All"] + list(df_reports['engineer'].unique()))
        f_shift = st.selectbox("Filter by Shift", ["All", "Day", "Night"])
    
    # Apply Filters
    disp_df = df_reports.copy()
    if f_eng != "All": disp_df = disp_df[disp_df['engineer'] == f_eng]
    if f_shift != "All": disp_df = disp_df[disp_df['shift'] == f_shift]
    
    disp_df['date'] = pd.to_datetime(disp_df['date'])
    
    for idx, row in disp_df.sort_values('id', ascending=False).iterrows():
        with st.expander(f"📄 {row['date'].date()} | {row['shift']} | {row['engineer']} (ID: {row['id']})"):
            c1, c2, c3 = st.columns([2, 1, 1])
            c1.markdown(f"**Handover:** {row['urgent_notes']}")
            c2.markdown(f"""
            **Checks:**
            - Radio: {'✅' if row['radios_charged'] else '❌'}
            - Phones: {'✅' if row['phones_working'] else '❌'}
            - Keys: {'✅' if row['keys_handed'] else '❌'}
            """)
            
            # File Logic
            date_obj = row['date']
            folder = os.path.join("data", "reports", str(date_obj.year), f"{date_obj.month:02d}")
            base_name = f"ShiftReport_{date_obj.strftime('%Y%m%d')}_{row['shift']}_{row['engineer'].replace(' ', '')}"
            
            xls_path = os.path.join(folder, f"{base_name}.xlsx")
            pdf_path = os.path.join(folder, f"{base_name}.pdf")
            
            if os.path.exists(xls_path):
                with open(xls_path, "rb") as f:
                    c3.download_button("📥 Excel", f, f"{base_name}.xlsx", key=f"xl_{row['id']}")
            if os.path.exists(pdf_path):
                with open(pdf_path, "rb") as f:
                    c3.download_button("📥 PDF", f, f"{base_name}.pdf", key=f"pdf_{row['id']}")