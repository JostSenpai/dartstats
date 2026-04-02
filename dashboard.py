import sqlite3
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import re
import json
import time
import asyncio
import sys
import os
from playwright.sync_api import sync_playwright
from database import save_pristine_match

# --- WINDOWS ASYNCIO FIX ---
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# --- THEME ENGINE ---
SETTINGS_FILE = "ui_settings.json"

THEME_PROFILES = {
    "Autodarts (Default)": {
        "primary": "#3B82F6", "secondary": "#8B5CF6", "accent": "#F43F5E",
        "bg_clear": "rgba(0,0,0,0)", "grid_line": "rgba(255,255,255,0.05)", 
        "text_main": "#F8FAFC", "text_muted": "#94A3B8",
        "darts": {"1": "#00E5FF", "2": "#FF007F", "3": "#00E676"},
        "toml": 'base="dark"\nprimaryColor="#3B82F6"\nbackgroundColor="#0F172A"\nsecondaryBackgroundColor="#1E293B"\ntextColor="#F8FAFC"'
    },
    "Midnight OLED": {
        "primary": "#00E5FF", "secondary": "#B537F2", "accent": "#FF007F",
        "bg_clear": "rgba(0,0,0,0)", "grid_line": "rgba(255,255,255,0.05)", 
        "text_main": "#FFFFFF", "text_muted": "#6B7280",
        "darts": {"1": "#00E5FF", "2": "#FF007F", "3": "#00E676"},
        "toml": 'base="dark"\nprimaryColor="#00E5FF"\nbackgroundColor="#000000"\nsecondaryBackgroundColor="#09090B"\ntextColor="#FFFFFF"'
    },
    "Light Mode": {
        "primary": "#2563EB", "secondary": "#4F46E5", "accent": "#E11D48",
        "bg_clear": "rgba(255,255,255,0)", "grid_line": "rgba(0,0,0,0.1)", 
        "text_main": "#0F172A", "text_muted": "#64748B",
        "darts": {"1": "#0284C7", "2": "#BE123C", "3": "#15803D"},
        "toml": 'base="light"\nprimaryColor="#2563EB"\nbackgroundColor="#FFFFFF"\nsecondaryBackgroundColor="#F1F5F9"\ntextColor="#0F172A"'
    }
}

def load_theme_preference():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f).get("theme", "Autodarts (Default)")
    return "Autodarts (Default)"

current_theme_name = load_theme_preference()
THEME = THEME_PROFILES[current_theme_name]
DART_COLORS = THEME["darts"]

os.makedirs(".streamlit", exist_ok=True)
config_path = ".streamlit/config.toml"
expected_toml = f"[theme]\n{THEME['toml']}"
needs_update = True
if os.path.exists(config_path):
    with open(config_path, "r") as f:
        if f.read() == expected_toml: needs_update = False
if needs_update:
    with open(config_path, "w") as f:
        f.write(expected_toml)

# --- STYLING & CONFIG ---
st.set_page_config(page_title="Autodarts Analytics", page_icon="🎯", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
        .stSelectbox>div>div>div, .stRadio label, .stCheckbox label, button { cursor: pointer !important; }
        label { cursor: default !important; }
        .ad-metric {
            background-color: rgba(255, 255, 255, 0.03);
            border-radius: 8px;
            padding: 15px;
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }
        .ad-metric h3 { margin: 0; font-size: 14px; color: #94A3B8; font-weight: normal; }
        .ad-metric h2 { margin: 5px 0 0 0; font-size: 28px; color: #F8FAFC; }
    </style>
""", unsafe_allow_html=True)

def apply_minimalist_theme(fig):
    fig.update_layout(
        paper_bgcolor=THEME["bg_clear"], plot_bgcolor=THEME["bg_clear"],
        font=dict(color=THEME["text_main"], family="sans-serif"),
        margin=dict(l=20, r=20, t=40, b=20),
        hoverlabel=dict(bgcolor="#1E293B" if "dark" in THEME["toml"] else "#F8FAFC", font_size=14)
    )
    fig.update_xaxes(showgrid=False, zeroline=False, title_font=dict(color=THEME["text_muted"]))
    fig.update_yaxes(showgrid=True, gridcolor=THEME["grid_line"], zeroline=False, title_font=dict(color=THEME["text_muted"]))
    return fig

# --- DATA LOADING ---
@st.cache_data(show_spinner=False)
def load_data():
    conn = sqlite3.connect("dartstats.db")
    try:
        # Dynamically attempt to load variant and base_score if they exist in the DB
        try:
            matches_df = pd.read_sql_query("SELECT m.created_at, m.duration, m.variant, m.base_score, ms.* FROM match_stats ms JOIN matches m ON ms.match_id = m.id", conn)
        except Exception:
            # Safe fallback if user has an older schema
            matches_df = pd.read_sql_query("SELECT m.created_at, m.duration, ms.* FROM match_stats ms JOIN matches m ON ms.match_id = m.id", conn)
            matches_df['variant'] = 'X01'
            matches_df['base_score'] = 501

        legs_df = pd.read_sql_query("SELECT l.created_at, l.leg_number, l.match_id, ls.* FROM leg_stats ls JOIN legs l ON ls.leg_id = l.id", conn)
        throws_df = pd.read_sql_query("""
            SELECT th.dart_number, th.coords_x, th.coords_y, (th.segment_number * th.multiplier) as dart_score, 
                   th.multiplier, th.segment_number, t.player_name, l.match_id, l.leg_number, m.created_at
            FROM throws th JOIN turns t ON th.turn_id = t.id JOIN legs l ON t.leg_id = l.id JOIN matches m ON l.match_id = m.id
            WHERE th.coords_x IS NOT NULL
        """, conn)
        starters_df = pd.read_sql_query("SELECT leg_id, player_name as starter_name FROM (SELECT leg_id, player_name, ROW_NUMBER() OVER(PARTITION BY leg_id ORDER BY id ASC) as rn FROM turns) WHERE rn = 1", conn)
        
        try:
            turns_df = pd.read_sql_query("SELECT id, leg_id, player_name, round_number, points_left as turn_score FROM turns", conn)
        except Exception:
            turns_df = pd.read_sql_query("SELECT id, leg_id, player_name, round_number, score as turn_score FROM turns", conn)
            
        all_players_df = pd.read_sql_query("SELECT match_id, player_name FROM match_stats", conn)
            
    except Exception:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    finally:
        conn.close()

    if not matches_df.empty:
        matches_df['created_at'] = pd.to_datetime(matches_df['created_at'])
        matches_df['date'] = matches_df['created_at'].dt.date
        matches_df['hour'] = matches_df['created_at'].dt.hour
        legs_df['created_at'] = pd.to_datetime(legs_df['created_at'])
        throws_df['created_at'] = pd.to_datetime(throws_df['created_at'])
        throws_df['date'] = throws_df['created_at'].dt.date

        legs_df['leg_number'] = legs_df['leg_number'].astype(int) + 1
        throws_df['leg_number'] = throws_df['leg_number'].astype(int) + 1
        throws_df['dart_number'] = throws_df['dart_number'].astype(int) + 1

        def parse_duration(d):
            if pd.isna(d): return 0
            d_str, secs = str(d).lower(), 0
            hours = re.findall(r'(\d+)h', d_str)
            if hours: secs += int(hours[0]) * 3600
            mins = re.findall(r'(\d+)m(?!s)', d_str) 
            if mins: secs += int(mins[0]) * 60
            seconds = re.findall(r'(\d+)s', d_str)
            if seconds: secs += int(seconds[0])
            return secs
        matches_df['duration_sec'] = matches_df['duration'].apply(parse_duration)
    return matches_df, legs_df, throws_df, starters_df, turns_df, all_players_df

matches, legs, throws, starters, turns, all_players = load_data()

# --- SIDEBAR NAVIGATION & FILTERS ---
with st.sidebar:
    st.markdown("### 🎯 **Autodarts Analytics**")
    
    selected_player = None
    if not matches.empty:
        players = matches['player_name'].unique().tolist()
        selected_player = st.selectbox("Player Select", players, label_visibility="collapsed")
    else:
        st.warning("No data found. Import matches!")
        
    st.markdown("---")
    page = st.radio("Navigation", [
        "📊 AD+ Overview",
        "📍 Alignment & Grouping",
        "📈 Progression Trends",
        "🔋 Match Context",
        "⚙️ Database Manager",
        "🎨 Appearance"
    ], label_visibility="collapsed")
    
    if selected_player:
        st.markdown("---")
        st.markdown("### 🎛️ Data Filters")
        
        p_matches_raw = matches[matches['player_name'] == selected_player].copy()
        match_opponents = {}
        for mid in p_matches_raw['match_id'].unique():
            players_in_match = all_players[all_players['match_id'] == mid]['player_name'].tolist()
            opponents = [p for p in players_in_match if p != selected_player]
            match_opponents[mid] = ", ".join(opponents) if opponents else "Solo"
            
        p_matches_raw['Opponent'] = p_matches_raw['match_id'].map(match_opponents)
        
        all_opponents = sorted(p_matches_raw['Opponent'].unique().tolist())
        exclude_opponents = st.multiselect("Exclude Opponents", all_opponents, placeholder="e.g. Solo")
        
        all_days = sorted(p_matches_raw['date'].unique().tolist(), reverse=True)
        exclude_days = st.multiselect("Exclude Days", all_days, placeholder="Select days...")
        
        st.markdown("---")
        
    if st.button("🔄 Sync Local Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# --- PREPARE FILTERED PLAYER DATA ---
if selected_player:
    p_matches = p_matches_raw.copy()
    if exclude_opponents:
        p_matches = p_matches[~p_matches['Opponent'].isin(exclude_opponents)]
    if exclude_days:
        p_matches = p_matches[~p_matches['date'].isin(exclude_days)]

    valid_mids = p_matches['match_id'].unique()
    p_legs = legs[legs['player_name'] == selected_player].copy()
    p_legs = p_legs[p_legs['match_id'].isin(valid_mids)]
    
    p_throws = throws[throws['player_name'] == selected_player].copy()
    p_throws = p_throws[p_throws['match_id'].isin(valid_mids)]
    
    valid_lids = p_legs['leg_id'].unique()
    p_turns = turns[turns['player_name'] == selected_player].copy()
    p_turns = p_turns[p_turns['leg_id'].isin(valid_lids)]

    p_legs = p_legs.merge(starters, on='leg_id', how='left')
    p_legs['throw_order'] = np.where(p_legs['starter_name'] == selected_player, 'Started', 'Went Second')

    sorted_matches = p_matches.sort_values('created_at').reset_index(drop=True)
    match_labels = {'Overall': 'Overall'}
    for idx, row in sorted_matches.iterrows():
        match_labels[row['match_id']] = f"Match {idx + 1} ({row['date']})"


# ==========================================================
# PAGE 0: AD+ OVERVIEW (NOW WITH VARIANT TABS!)
# ==========================================================
if selected_player and page == "📊 AD+ Overview":
    
    # Create the AD+ Style Tabs
    tab_x01, tab_cricket, tab_countup, tab_rc, tab_killer = st.tabs(["X01", "Cricket", "Count Up", "Random Checkout", "Killer"])

    # ------------------ X01 TAB ------------------
    with tab_x01:
        # Step 1: Isolate only X01 Matches
        t_matches = p_matches.copy()
        if 'variant' in t_matches.columns:
            t_matches = t_matches[t_matches['variant'].astype(str).str.upper() == 'X01']

        # Step 2: Base Score Filter Menu (501, 301, 121, etc.)
        if 'base_score' in t_matches.columns:
            available_scores = [int(x) for x in t_matches['base_score'].dropna().unique()]
            available_scores = sorted(available_scores, reverse=True)
            if available_scores:
                col_filt, _ = st.columns([1, 4])
                sel_score = col_filt.selectbox("🎯 Target Base Score", ["All"] + available_scores)
                if sel_score != "All":
                    t_matches = t_matches[t_matches['base_score'] == sel_score]

        # Step 3: Cascade X01 filters down to legs, throws, and turns
        valid_t_mids = t_matches['match_id'].unique()
        t_legs = p_legs[p_legs['match_id'].isin(valid_t_mids)]
        t_throws = p_throws[p_throws['match_id'].isin(valid_t_mids)]
        valid_t_lids = t_legs['leg_id'].unique()
        t_turns = p_turns[p_turns['leg_id'].isin(valid_t_lids)]

        if t_matches.empty:
            st.info("No X01 data available for the selected filters.")
        else:
            # --- RENDER THE X01 AD+ METRICS ---
            total_darts = len(t_throws)
            total_matches = len(t_matches)
            playtime_hours = t_matches['duration_sec'].sum() / 3600
            distance_km = (total_darts * 2.37) / 1000 
            
            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f'<div class="ad-metric"><h3>Total Darts (X01)</h3><h2>{total_darts:,}</h2></div>', unsafe_allow_html=True)
            c2.markdown(f'<div class="ad-metric"><h3>Matches Played</h3><h2>{total_matches:,}</h2></div>', unsafe_allow_html=True)
            c3.markdown(f'<div class="ad-metric"><h3>Total Playtime</h3><h2>{playtime_hours:.1f}h</h2></div>', unsafe_allow_html=True)
            c4.markdown(f'<div class="ad-metric"><h3>Distance Walked</h3><h2>{distance_km:.2f}km</h2></div>', unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)

            colA, colB = st.columns(2)
            with colA:
                darts_day = t_throws.groupby('date').size().reset_index(name='darts')
                fig_vol1 = px.bar(darts_day, x='date', y='darts', title="Darts Thrown per Day")
                fig_vol1.update_traces(marker_color=THEME["primary"])
                fig_vol1.update_xaxes(type='category', title="")
                st.plotly_chart(apply_minimalist_theme(fig_vol1), use_container_width=True)
            with colB:
                time_day = t_matches.groupby('date')['duration_sec'].sum().reset_index()
                time_day['mins'] = time_day['duration_sec'] / 60
                fig_vol2 = px.bar(time_day, x='date', y='mins', title="Playtime per Day (Mins)")
                fig_vol2.update_traces(marker_color=THEME["secondary"])
                fig_vol2.update_xaxes(type='category', title="")
                st.plotly_chart(apply_minimalist_theme(fig_vol2), use_container_width=True)

            best_avg = t_matches['average'].max() if not t_matches.empty else 0
            best_leg = t_legs['darts_thrown'].min() if 'darts_thrown' in t_legs.columns and not t_legs.empty else "N/A"
            total_180s = len(t_turns[t_turns['turn_score'] == 180])
            overall_avg = t_matches["average"].mean() if not t_matches.empty else 0
            
            st.markdown("<br>", unsafe_allow_html=True)
            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f'<div class="ad-metric"><h3>Best Average</h3><h2>{best_avg:.2f}</h2></div>', unsafe_allow_html=True)
            c2.markdown(f'<div class="ad-metric"><h3>Best Leg</h3><h2>{best_leg} Darts</h2></div>', unsafe_allow_html=True)
            c3.markdown(f'<div class="ad-metric"><h3>Overall Avg</h3><h2>{overall_avg:.2f}</h2></div>', unsafe_allow_html=True)
            c4.markdown(f'<div class="ad-metric"><h3>Total 180s</h3><h2>{total_180s}</h2></div>', unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)

            colC, colD = st.columns(2)
            with colC:
                st.markdown("### Scoring Power")
                t_sub60 = len(t_turns[t_turns['turn_score'] < 60])
                t60 = len(t_turns[(t_turns['turn_score'] >= 60) & (t_turns['turn_score'] < 100)])
                t100 = len(t_turns[(t_turns['turn_score'] >= 100) & (t_turns['turn_score'] < 140)])
                t140 = len(t_turns[(t_turns['turn_score'] >= 140) & (t_turns['turn_score'] < 170)])
                t170 = len(t_turns[(t_turns['turn_score'] >= 170) & (t_turns['turn_score'] < 180)])
                
                score_df = pd.DataFrame({
                    'Category': ['< 60', '60+', '100+', '140+', '170+', '180'],
                    'Count': [t_sub60, t60, t100, t140, t170, total_180s]
                })
                fig_score = px.bar(score_df, x='Count', y='Category', orientation='h', text='Count')
                fig_score.update_traces(marker_color=THEME["primary"])
                fig_score.update_layout(yaxis=dict(autorange="reversed"), height=350, margin=dict(l=0, r=20, t=10, b=0))
                st.plotly_chart(apply_minimalist_theme(fig_score), use_container_width=True)

            with colD:
                st.markdown("### Checkout Percentage")
                chart_df = t_matches.sort_values('created_at').reset_index(drop=True)
                chart_df['co_trend'] = chart_df['checkout_percent'].rolling(window=5, min_periods=1).mean()
                
                fig_co = go.Figure()
                fig_co.add_trace(go.Scatter(x=chart_df['created_at'], y=chart_df['checkout_percent'], mode='lines', name="Raw %", line=dict(color=THEME["primary"], width=1, dash='dot'), opacity=0.4))
                fig_co.add_trace(go.Scatter(x=chart_df['created_at'], y=chart_df['co_trend'], mode='lines', name="Fitted Curve", line=dict(color=THEME["accent"], width=3, shape='spline')))
                fig_co.update_layout(yaxis_tickformat='.0%', height=350, margin=dict(l=0, r=20, t=10, b=0), showlegend=False)
                st.plotly_chart(apply_minimalist_theme(fig_co), use_container_width=True)

            st.markdown("<br>", unsafe_allow_html=True)
            colE, colF = st.columns(2)
            with colE:
                st.markdown("### Top 10 Legs")
                if 'darts_thrown' in t_legs.columns and not t_legs.empty:
                    top_legs = t_legs[t_legs['darts_thrown'] > 0].nsmallest(10, 'darts_thrown')[['darts_thrown', 'average', 'created_at']]
                    top_legs.columns = ['Darts', 'Avg', 'Date']
                    top_legs['Avg'] = top_legs['Avg'].round(2)
                    top_legs['Date'] = top_legs['Date'].dt.strftime('%Y-%m-%d')
                    st.dataframe(top_legs.reset_index(drop=True), use_container_width=True)
                else:
                    st.info("Leg details not fully populated yet.")

            with colF:
                st.markdown("### Top 10 Matches (By Average)")
                if not t_matches.empty:
                    top_matches = t_matches.nlargest(10, 'average')[['date', 'Opponent', 'average', 'first9_average']]
                    top_matches.columns = ['Date', 'Opponent', 'Average', 'First 9']
                    top_matches['Average'] = top_matches['Average'].round(2)
                    top_matches['First 9'] = top_matches['First 9'].round(2)
                    st.dataframe(top_matches.reset_index(drop=True), use_container_width=True)

    # ------------------ OTHER TABS ------------------
    with tab_cricket:
        st.info("🏏 Cricket detailed analytics will be unlocked in a future feature update! Stick to X01 for now.")
    with tab_countup:
        st.info("📈 Count Up analytics will be unlocked in a future feature update!")
    with tab_rc:
        st.info("🎯 Random Checkout analytics will be unlocked in a future feature update!")
    with tab_killer:
        st.info("💀 Killer analytics will be unlocked in a future feature update!")


# ==========================================================
# PAGE 1: ALIGNMENT & GROUPING
# ==========================================================
elif selected_player and page == "📍 Alignment & Grouping":
    st.markdown(f"## 📍 Alignment Analysis: **{selected_player}**")
    
    c1, c2, c3, c4 = st.columns(4)
    all_days = ['Overall'] + sorted(p_matches['date'].unique().tolist(), reverse=True)
    sel_day = c1.selectbox("📅 Day", all_days)
    
    avail_matches = p_matches[p_matches['date'] == sel_day] if sel_day != 'Overall' else p_matches
    match_list = ['Overall'] + avail_matches['match_id'].tolist()
    
    sel_match = c2.selectbox("🏆 Match", match_list, format_func=lambda x: match_labels.get(x, x))
    avail_legs = ['Overall'] + sorted(p_legs['leg_number'].unique().tolist())
    sel_leg = c3.selectbox("🎯 Leg Number", avail_legs)
    sel_dart = c4.selectbox("📍 Dart Number", ['Overall', 1, 2, 3])
    
    h_throws = p_throws.copy()
    if sel_day != 'Overall': h_throws = h_throws[h_throws['date'] == sel_day]
    if sel_match != 'Overall': h_throws = h_throws[h_throws['match_id'] == sel_match]
    if sel_leg != 'Overall': h_throws = h_throws[h_throws['leg_number'] == sel_leg]
    if sel_dart != 'Overall': h_throws = h_throws[h_throws['dart_number'] == sel_dart]

    if not h_throws.empty:
        h_throws['dart_number'] = h_throws['dart_number'].astype(str)
        fig_pro = go.Figure()

        r_db_out, r_db_in = 1.0, 162/170
        r_tr_out, r_tr_in = 107/170, 99/170
        r_bull_out, r_bull_in = 15.9/170, 6.35/170
        
        schematic_shapes = []
        ring_color = "rgba(0,0,0,0.15)" if "light" in THEME["toml"] else "rgba(255, 255, 255, 0.08)"
        
        for r in [r_db_out, r_db_in, r_tr_out, r_tr_in, r_bull_out, r_bull_in]:
            schematic_shapes.append(dict(type="circle", xref="x", yref="y", x0=-r, y0=-r, x1=r, y1=r, line=dict(color=ring_color, width=1)))
        for i in range(20):
            angle_rad = np.radians(9 + (18 * i))
            schematic_shapes.append(dict(type="line", xref="x", yref="y", x0=r_bull_out*np.cos(angle_rad), y0=r_bull_out*np.sin(angle_rad), x1=r_db_out*np.cos(angle_rad), y1=r_db_out*np.sin(angle_rad), line=dict(color=ring_color, width=1)))

        cross_color = "rgba(0,0,0,0.3)" if "light" in THEME["toml"] else "rgba(255, 255, 255, 0.3)"
        crosshair_style = dict(width=1, color=cross_color, dash="dot")
        schematic_shapes.append(dict(type="line", xref="x", yref="y", x0=-1.1, y0=0, x1=1.1, y1=0, line=crosshair_style))
        schematic_shapes.append(dict(type="line", xref="x", yref="y", x0=0, y0=-1.1, x1=0, y1=1.1, line=crosshair_style))

        for dart_num in sorted(h_throws['dart_number'].unique()):
            df_subset = h_throws[h_throws['dart_number'] == dart_num]
            fig_pro.add_trace(go.Scattergl(
                x=df_subset['coords_x'], y=df_subset['coords_y'],
                mode='markers', name=f"Dart {dart_num}",
                marker=dict(size=5, color=DART_COLORS.get(dart_num, THEME["primary"]), opacity=0.4, line=dict(width=0)),
                text=df_subset['dart_score'],
                hovertemplate="<b>Score: %{text}</b><br>X: %{x:.2f} | Y: %{y:.2f}<extra></extra>"
            ))

        fig_pro.update_layout(
            paper_bgcolor=THEME["bg_clear"], plot_bgcolor=THEME["bg_clear"], font=dict(color=THEME["text_main"]),
            shapes=schematic_shapes, autosize=True, height=750, margin=dict(l=0, r=0, t=30, b=0),
            xaxis=dict(range=[-1.2, 1.2], constrain="domain", showgrid=False, zeroline=False, visible=False),
            yaxis=dict(range=[-1.2, 1.2], scaleanchor="x", scaleratio=1, showgrid=False, zeroline=False, visible=False),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5)
        )
        st.plotly_chart(fig_pro, use_container_width=True)
    else:
        st.info("No darts found for these filters.")


# ==========================================================
# PAGE 2: PROGRESSION TRENDS
# ==========================================================
elif selected_player and page == "📈 Progression Trends":
    st.markdown(f"## 📈 Progression Trends: **{selected_player}**")
    
    chart_df = p_matches.sort_values('created_at').reset_index(drop=True)
    chart_df['avg_trend'] = chart_df['average'].rolling(window=5, min_periods=1).mean()
    chart_df['first9_trend'] = chart_df['first9_average'].rolling(window=5, min_periods=1).mean()

    fig_avg = go.Figure()
    fig_avg.add_trace(go.Scatter(x=chart_df['created_at'], y=chart_df['average'], mode='lines', name="3-Dart (Raw)", line=dict(color=THEME["primary"], width=1, dash='dot'), opacity=0.4))
    fig_avg.add_trace(go.Scatter(x=chart_df['created_at'], y=chart_df['first9_average'], mode='lines', name="First 9 (Raw)", line=dict(color=THEME["secondary"], width=1, dash='dot'), opacity=0.4))
    fig_avg.add_trace(go.Scatter(x=chart_df['created_at'], y=chart_df['avg_trend'], mode='lines', name="3-Dart (Fitted Curve)", line=dict(color=THEME["primary"], width=4, shape='spline')))
    fig_avg.add_trace(go.Scatter(x=chart_df['created_at'], y=chart_df['first9_trend'], mode='lines', name="First 9 (Fitted Curve)", line=dict(color=THEME["secondary"], width=4, shape='spline')))
    
    fig_avg.update_layout(title="Averages Over Time (Smoothed)")
    st.plotly_chart(apply_minimalist_theme(fig_avg), use_container_width=True)
    
    col1, col2 = st.columns(2)
    with col1:
        dart_avg = p_throws.groupby('dart_number')['dart_score'].mean().reset_index()
        dart_avg['dart_score'] = dart_avg['dart_score'] * 3 
        dart_avg['dart_number'] = dart_avg['dart_number'].astype(str)
        fig_darts = px.bar(dart_avg, x='dart_number', y='dart_score', text_auto='.2f', color='dart_number', color_discrete_map=DART_COLORS)
        fig_darts.update_traces(showlegend=False)
        fig_darts.update_layout(title="Pace per Dart (x3)")
        st.plotly_chart(apply_minimalist_theme(fig_darts), use_container_width=True)
        
    with col2:
        leg_num_avg = p_legs.groupby('leg_number')['average'].mean().reset_index()
        fig_leg_num = px.bar(leg_num_avg, x='leg_number', y='average', text_auto='.1f')
        fig_leg_num.update_traces(marker_color=THEME["secondary"])
        fig_leg_num.update_xaxes(type='category')
        fig_leg_num.update_layout(title="Average by Leg Number")
        st.plotly_chart(apply_minimalist_theme(fig_leg_num), use_container_width=True)


# ==========================================================
# PAGE 3: MATCH CONTEXT
# ==========================================================
elif selected_player and page == "🔋 Match Context":
    st.markdown(f"## 🔋 Match Context: **{selected_player}**")
    fig_dur = px.scatter(p_matches, x='duration_sec', y='average', trendline="ols")
    fig_dur.update_traces(marker=dict(color=THEME["accent"], size=8, opacity=0.7))
    fig_dur.update_layout(title="Fatigue Check (Avg vs Match Duration in Secs)")
    st.plotly_chart(apply_minimalist_theme(fig_dur), use_container_width=True)
    
    col3, col4 = st.columns(2)
    with col3:
        starter_avg = p_legs.groupby('throw_order')['average'].mean().reset_index()
        fig_start = px.bar(starter_avg, x='throw_order', y='average', text_auto='.1f', color='throw_order', color_discrete_map={"Started": THEME["primary"], "Went Second": THEME["text_muted"]})
        fig_start.update_layout(title="Avg: Started vs Went Second", showlegend=False)
        st.plotly_chart(apply_minimalist_theme(fig_start), use_container_width=True)
        
    with col4:
        hour_avg = p_matches.groupby('hour')['average'].mean().reset_index()
        fig_hour = px.bar(hour_avg, x='hour', y='average', text_auto='.1f')
        fig_hour.update_traces(marker_color=THEME["secondary"])
        fig_hour.update_layout(title="Average by Time of Day (Hour)")
        fig_hour.update_xaxes(type='category')
        st.plotly_chart(apply_minimalist_theme(fig_hour), use_container_width=True)


# ==========================================================
# PAGE 4: DATABASE MANAGER 
# ==========================================================
elif page == "⚙️ Database Manager":
    st.markdown("## ⚙️ Database Manager")
    
    st.markdown("### 📥 Bulk History Importer")
    st.markdown("Scan your online Autodarts account and safely download all missing match history directly into your SQLite vault.")
    
    if "scraped_ids" not in st.session_state:
        st.session_state.scraped_ids = None

    if st.button("🔍 1. Scan Autodarts Account for Matches", use_container_width=True):
        debug_log = st.empty()
        with st.spinner("Running paginated Playwright scraper (This may take a minute)..."):
            try:
                with open("config.json", "r") as f:
                    config = json.load(f)
                email = config.get("autodarts_email")
                pwd = config.get("autodarts_password")
                
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.goto("https://play.autodarts.io/")
                    page.wait_for_timeout(2000)
                    page.fill('input[type="email"], input[name="username"]', email)
                    page.fill('input[type="password"], input[name="password"]', pwd)
                    page.keyboard.press("Enter")
                    page.wait_for_selector('a[href="/history/matches"]', timeout=15000)
                    page.wait_for_timeout(2000)
                    page.click('a[href="/history/matches"]')
                    
                    try:
                        page.wait_for_selector('a[href*="/matches/"]', timeout=15000)
                    except Exception:
                        pass
                    
                    all_ids = set()
                    page_num = 1
                    max_pages = 100 
                    
                    while page_num <= max_pages:
                        debug_log.info(f"Extracting matches from Page {page_num}...")
                        hrefs = page.evaluate("Array.from(document.querySelectorAll('a')).map(a => a.href)")
                        for href in hrefs:
                            if href:
                                match = re.search(r'/matches/([a-f0-9\-]{30,})', href)
                                if match: 
                                    all_ids.add(match.group(1))
                        
                        clicked_next = page.evaluate('''() => {
                            const btns = Array.from(document.querySelectorAll('button'));
                            const nextBtn = btns.find(b => {
                                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                                const text = b.textContent.trim().toLowerCase();
                                const html = b.innerHTML.toLowerCase();
                                return aria.includes('next') || text === '>' || text === 'next' || text.includes('more') || text.includes('load') || html.includes('chevron-right') || html.includes('angle-right');
                            });
                            if (nextBtn && !nextBtn.disabled && !nextBtn.hasAttribute('data-disabled')) {
                                nextBtn.click();
                                return true;
                            }
                            return false;
                        }''')
                        
                        if clicked_next:
                            page.wait_for_load_state("networkidle", timeout=10000)
                            page.wait_for_timeout(2500)
                            page_num += 1
                        else:
                            break
                    
                    st.session_state.scraped_ids = list(all_ids)
                    browser.close()
                    debug_log.empty()
                    
                    if len(st.session_state.scraped_ids) == 0:
                        st.error("🚨 Found 0 matches!")
                    else:
                        st.success(f"✅ Successfully scraped {len(st.session_state.scraped_ids)} total matches!")
                        
            except Exception as e:
                st.error(f"❌ Scraper crashed with error: {e}")

    if st.session_state.scraped_ids:
        st.markdown("### 2. Select Matches to Import")
        existing_ids = matches['match_id'].tolist() if not matches.empty else []
        df = pd.DataFrame({"Match ID": st.session_state.scraped_ids})
        df["Already Saved"] = df["Match ID"].isin(existing_ids)
        df["Import?"] = ~df["Already Saved"]
        
        edited_df = st.data_editor(df, disabled=["Match ID", "Already Saved"], hide_index=True, use_container_width=True)
        
        if st.button("🚀 3. Start Bulk Import", use_container_width=True):
            to_import = edited_df[edited_df["Import?"]]["Match ID"].tolist()
            if not to_import:
                st.warning("No new matches selected for import!")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()
                try:
                    with open("config.json", "r") as f:
                        config = json.load(f)
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        page = browser.new_page()
                        
                        page.goto("https://play.autodarts.io/")
                        page.wait_for_timeout(2000)
                        page.fill('input[type="email"], input[name="username"]', config.get("autodarts_email"))
                        page.fill('input[type="password"], input[name="password"]', config.get("autodarts_password"))
                        page.keyboard.press("Enter")
                        page.wait_for_selector('a[href="/history/matches"]', timeout=15000)
                        
                        for i, mid in enumerate(to_import):
                            status_text.text(f"Intercepting pristine math for Match {i+1} of {len(to_import)}...")
                            captured_data = []
                            def intercept(response, match_uuid=mid):
                                if match_uuid in response.url and response.status in [200, 304]:
                                    try:
                                        data = response.json()
                                        if isinstance(data, dict) and "games" in data:
                                            captured_data.append(data)
                                    except: pass
                            page.on("response", intercept)
                            page.goto(f"https://play.autodarts.io/history/matches/{mid}")
                            page.wait_for_load_state("networkidle", timeout=15000)
                            page.wait_for_timeout(2500)
                            
                            if captured_data:
                                save_pristine_match(captured_data[0])
                                
                            page.remove_listener("response", intercept)
                            progress_bar.progress((i + 1) / len(to_import))
                            
                        browser.close()
                    status_text.text(f"✅ Vaulted {len(to_import)} new matches into the database!")
                    time.sleep(2)
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Import process failed: {e}")

    st.markdown("---")
    st.markdown("### 🗑️ Delete Local Matches")
    st.markdown("Permanently erase specific matches (like warmups or glitches) from your local database. **This cannot be undone.**")
    
    if selected_player and not p_matches_raw.empty:
        del_df = p_matches_raw[['match_id', 'date', 'Opponent', 'average', 'duration']].copy()
        del_df['average'] = del_df['average'].round(2)
        del_df['Delete?'] = False
        del_df = del_df[['Delete?', 'date', 'Opponent', 'average', 'duration', 'match_id']] 
        
        edited_del = st.data_editor(del_df, hide_index=True, disabled=["date", "Opponent", "average", "duration", "match_id"], use_container_width=True)
        to_delete = edited_del[edited_del['Delete?']]['match_id'].tolist()
        
        if st.button("🚨 Permanently Delete Selected Matches", type="primary"):
            if not to_delete:
                st.warning("No matches selected for deletion.")
            else:
                with st.spinner("Erasing matches from SQLite vault..."):
                    conn = sqlite3.connect("dartstats.db")
                    c = conn.cursor()
                    for mid in to_delete:
                        c.execute("SELECT id FROM legs WHERE match_id = ?", (mid,))
                        lids = [r[0] for r in c.fetchall()]
                        for lid in lids:
                            c.execute("SELECT id FROM turns WHERE leg_id = ?", (lid,))
                            tids = [r[0] for r in c.fetchall()]
                            for tid in tids:
                                c.execute("DELETE FROM throws WHERE turn_id = ?", (tid,))
                            c.execute("DELETE FROM turns WHERE leg_id = ?", (lid,))
                            c.execute("DELETE FROM leg_stats WHERE leg_id = ?", (lid,))
                        c.execute("DELETE FROM legs WHERE match_id = ?", (mid,))
                        c.execute("DELETE FROM match_stats WHERE match_id = ?", (mid,))
                        c.execute("DELETE FROM matches WHERE id = ?", (mid,))
                    conn.commit()
                    conn.close()
                st.success(f"Permanently deleted {len(to_delete)} matches!")
                time.sleep(1)
                st.cache_data.clear()
                st.rerun()


# ==========================================================
# PAGE 5: APPEARANCE SETTINGS
# ==========================================================
elif page == "🎨 Appearance":
    st.markdown("## 🎨 Appearance Settings")
    st.markdown("Customize the look and feel of your analytics dashboard. Changes are saved permanently.")
    
    new_theme = st.selectbox("Select Theme", list(THEME_PROFILES.keys()), index=list(THEME_PROFILES.keys()).index(current_theme_name))
    
    if st.button("💾 Apply Theme", use_container_width=True):
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"theme": new_theme}, f)
        expected_toml = f"[theme]\n{THEME_PROFILES[new_theme]['toml']}"
        with open(config_path, "w") as f:
            f.write(expected_toml)
        st.success(f"Theme changed to {new_theme}! Refreshing...")
        time.sleep(1)
        st.rerun()