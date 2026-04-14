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

def hex_to_rgba(hex_code, alpha):
    hex_code = hex_code.lstrip('#')
    if len(hex_code) == 6:
        r = int(hex_code[0:2], 16)
        g = int(hex_code[2:4], 16)
        b = int(hex_code[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"
    return f"rgba(255,255,255,{alpha})"

THEME_PROFILES = {
    "Autodarts (Default)": {
        "primary": "#3B82F6", "secondary": "#8B5CF6", "accent": "#F43F5E",
        "bg_clear": "rgba(0,0,0,0)", "card_bg": "rgba(255, 255, 255, 0.03)", "grid_line": "rgba(255,255,255,0.05)", 
        "text_main": "#F8FAFC", "text_muted": "#94A3B8",
        "darts": {"1": "#00E5FF", "2": "#FF007F", "3": "#00E676"},
        "toml": 'base="dark"\nprimaryColor="#3B82F6"\nbackgroundColor="#0F172A"\nsecondaryBackgroundColor="#1E293B"\ntextColor="#F8FAFC"'
    },
    "Midnight Neon": {
        "primary": "#6366F1", "secondary": "#8B5CF6", "accent": "#06B6D4",
        "bg_clear": "rgba(0,0,0,0)", "card_bg": "#1E1E1E", "grid_line": "rgba(255,255,255,0.05)", 
        "text_main": "#FFFFFF", "text_muted": "#B3B3B3",
        "darts": {"1": "#06B6D4", "2": "#FF007F", "3": "#00E676"},
        "toml": 'base="dark"\nprimaryColor="#6366F1"\nbackgroundColor="#121212"\nsecondaryBackgroundColor="#1A1A1A"\ntextColor="#FFFFFF"'
    },
    "Nordic Slate": {
        "primary": "#38BDF8", "secondary": "#64748B", "accent": "#38BDF8",
        "bg_clear": "rgba(0,0,0,0)", "card_bg": "#1E293B", "grid_line": "rgba(255,255,255,0.05)", 
        "text_main": "#F8FAFC", "text_muted": "#94A3B8",
        "darts": {"1": "#38BDF8", "2": "#F43F5E", "3": "#10B981"},
        "toml": 'base="dark"\nprimaryColor="#38BDF8"\nbackgroundColor="#0F172A"\nsecondaryBackgroundColor="#1E293B"\ntextColor="#F8FAFC"'
    },
    "Clean Light": {
        "primary": "#14B8A6", "secondary": "#34D399", "accent": "#2563EB",
        "bg_clear": "rgba(255,255,255,0)", "card_bg": "#FFFFFF", "grid_line": "rgba(0,0,0,0.08)", 
        "text_main": "#1F2937", "text_muted": "#6B7280",
        "darts": {"1": "#2563EB", "2": "#E11D48", "3": "#059669"},
        "toml": 'base="light"\nprimaryColor="#14B8A6"\nbackgroundColor="#F3F4F6"\nsecondaryBackgroundColor="#FFFFFF"\ntextColor="#1F2937"'
    }
}

def load_theme_preference():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f).get("theme", "Autodarts (Default)")
    return "Autodarts (Default)"

current_theme_name = load_theme_preference()
THEME = THEME_PROFILES.get(current_theme_name, THEME_PROFILES["Autodarts (Default)"])
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

st.markdown(f"""
    <style>
        .stSelectbox>div>div>div, .stRadio label, .stCheckbox label, button {{ cursor: pointer !important; }}
        label {{ cursor: default !important; }}
        .ad-metric {{
            background-color: {THEME['card_bg']};
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 15px;
            text-align: center;
            border: 1px solid {THEME['grid_line']};
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
        }}
        .ad-metric h3 {{ margin: 0; font-size: 14px; color: {THEME['text_muted']}; font-weight: normal; }}
        .ad-metric h2 {{ margin: 8px 0 0 0; font-size: 28px; color: {THEME['text_main']}; }}
    </style>
""", unsafe_allow_html=True)

def apply_minimalist_theme(fig):
    fig.update_layout(
        paper_bgcolor=THEME["bg_clear"], plot_bgcolor=THEME["bg_clear"],
        font=dict(color=THEME["text_main"], family="sans-serif"),
        margin=dict(l=20, r=20, t=40, b=20),
        hoverlabel=dict(bgcolor=THEME['card_bg'], font_size=14)
    )
    fig.update_xaxes(showgrid=False, zeroline=False, title_font=dict(color=THEME["text_muted"]))
    fig.update_yaxes(showgrid=True, gridcolor=THEME["grid_line"], zeroline=False, title_font=dict(color=THEME["text_muted"]))
    return fig

# --- SAFE LEGS WON CALCULATOR ---
def calculate_legs_won(df_matches, df_legs):
    for col in ['legs_won', 'legsWon', 'legswon']:
        if col in df_matches.columns:
            return int(df_matches[col].fillna(0).sum())
    if df_legs.empty:
        return 0
    for col in ['won', 'winner', 'is_winner', 'leg_won']:
        if col in df_legs.columns:
            val = len(df_legs[df_legs[col].isin([1, True, '1', 'true', 'True', 'yes', 'Yes'])])
            if val > 0: return val
    for col in ['score_left', 'remaining_score', 'score_remaining', 'points_left']:
        if col in df_legs.columns:
            try:
                val = len(df_legs[df_legs[col].astype(float) == 0])
                if val > 0: return val
            except: pass
    if 'checkout' in df_legs.columns:
        val = len(df_legs[df_legs['checkout'].fillna(0).astype(float) > 0])
        if val > 0: return val
    return 0

# --- DATA LOADING ---
@st.cache_data(show_spinner=False)
def load_data():
    conn = sqlite3.connect("dartstats.db")
    try:
        try:
            matches_df = pd.read_sql_query("SELECT m.created_at, m.duration, m.variant, m.base_score, ms.* FROM match_stats ms JOIN matches m ON ms.match_id = m.id", conn)
        except Exception:
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
        
    if st.button("🔄 Sync Local Data", width="stretch"):
        st.cache_data.clear()
        st.rerun()

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
# PAGE 0: AD+ OVERVIEW
# ==========================================================
if selected_player and page == "📊 AD+ Overview":
    
    tab_x01, tab_cricket, tab_countup, tab_rc = st.tabs(["X01", "Cricket", "Count Up", "Random Checkout"])

    def get_variant_summary(data_frame, variant_name):
        df = data_frame.copy()
        if 'variant' in df.columns:
            df = df[df['variant'].astype(str).str.upper() == variant_name.upper()]
        if df.empty:
            return None, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        
        valid_mids = df['match_id'].unique()
        df_legs = p_legs[p_legs['match_id'].isin(valid_mids)]
        df_throws = p_throws[p_throws['match_id'].isin(valid_mids)]
        valid_lids = df_legs['leg_id'].unique()
        df_turns = p_turns[p_turns['leg_id'].isin(valid_lids)]
        
        legs_won = calculate_legs_won(df, df_legs)
                
        summary = {
            'legs_played': len(df_legs),
            'legs_won': legs_won,
            'total_darts': len(df_throws),
            'playtime_h': df['duration_sec'].sum() / 3600,
            'distance_km': (len(df_throws) * 2.37) / 1000
        }
        return summary, df, df_legs, df_throws, df_turns

    # ------------------ X01 TAB ------------------
    with tab_x01:
        sum_x01, df_x01, df_x01_legs, df_x01_throws, df_x01_turns = get_variant_summary(p_matches, 'X01')

        if not sum_x01:
            st.info("No X01 data available for the selected filters.")
        else:
            if 'base_score' in df_x01.columns:
                available_scores = [int(x) for x in df_x01['base_score'].dropna().unique()]
                available_scores = sorted(available_scores, reverse=True)
                if available_scores:
                    filt_c1, filt_c2 = st.columns([1, 4])
                    sel_score = filt_c1.selectbox("🎯 Target Base Score", ["All"] + available_scores, key='x01_score')
                    if sel_score != "All":
                        df_x01 = df_x01[df_x01['base_score'] == sel_score]
                        
                        valid_t_mids = df_x01['match_id'].unique()
                        df_x01_legs = p_legs[p_legs['match_id'].isin(valid_t_mids)]
                        df_x01_throws = p_throws[p_throws['match_id'].isin(valid_t_mids)]
                        valid_t_lids = df_x01_legs['leg_id'].unique()
                        df_x01_turns = p_turns[p_turns['leg_id'].isin(valid_t_lids)]
                        
                        if df_x01.empty:
                            st.info(f"No X01 data available for the target score {sel_score}.")
                            st.stop()
                        
                        sum_x01['legs_played'] = len(df_x01_legs)
                        sum_x01['legs_won'] = calculate_legs_won(df_x01, df_x01_legs)
                        sum_x01['total_darts'] = len(df_x01_throws)
                        sum_x01['playtime_h'] = df_x01['duration_sec'].sum() / 3600
                        sum_x01['distance_km'] = (len(df_x01_throws) * 2.37) / 1000

            best_avg = df_x01['average'].max() if not df_x01.empty else 0
            best_leg = df_x01_legs['darts_thrown'].min() if 'darts_thrown' in df_x01_legs.columns and not df_x01_legs.empty else "N/A"
            total_180s = len(df_x01_turns[df_x01_turns['turn_score'] == 180])
            overall_avg = df_x01["average"].mean() if not df_x01.empty else 0
            
            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f'<div class="ad-metric"><h3>Total Darts (X01)</h3><h2>{sum_x01["total_darts"]:,}</h2></div>', unsafe_allow_html=True)
            c2.markdown(f'<div class="ad-metric"><h3>Legs played</h3><h2>{sum_x01["legs_played"]} / {sum_x01["legs_won"]} won</h2></div>', unsafe_allow_html=True)
            c3.markdown(f'<div class="ad-metric"><h3>Playtime</h3><h2>{sum_x01["playtime_h"]:.1f}h</h2></div>', unsafe_allow_html=True)
            c4.markdown(f'<div class="ad-metric"><h3>Distance Walked</h3><h2>{sum_x01["distance_km"]:.2f}km</h2></div>', unsafe_allow_html=True)
            
            c5, c6, c7, c8 = st.columns(4)
            c5.markdown(f'<div class="ad-metric"><h3>Best Average</h3><h2>{best_avg:.2f}</h2></div>', unsafe_allow_html=True)
            c6.markdown(f'<div class="ad-metric"><h3>Best Leg</h3><h2>{best_leg} Darts</h2></div>', unsafe_allow_html=True)
            c7.markdown(f'<div class="ad-metric"><h3>Overall Avg</h3><h2>{overall_avg:.2f}</h2></div>', unsafe_allow_html=True)
            c8.markdown(f'<div class="ad-metric"><h3>Total 180s</h3><h2>{total_180s}</h2></div>', unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)

            colA, colB = st.columns(2)
            with colA:
                darts_day = df_x01_throws.groupby('date').size().reset_index(name='darts')
                fig_vol1 = px.bar(darts_day, x='date', y='darts', title="Darts Thrown per Day")
                fig_vol1.update_traces(marker_color=THEME["primary"])
                fig_vol1.update_xaxes(title="") 
                st.plotly_chart(apply_minimalist_theme(fig_vol1), width='stretch')
            with colB:
                time_day = df_x01.groupby('date')['duration_sec'].sum().reset_index()
                time_day['mins'] = time_day['duration_sec'] / 60
                fig_vol2 = px.bar(time_day, x='date', y='mins', title="Playtime per Day (Mins)")
                fig_vol2.update_traces(marker_color=THEME["secondary"])
                fig_vol2.update_xaxes(title="") 
                st.plotly_chart(apply_minimalist_theme(fig_vol2), width='stretch')

            st.markdown("### Performance breakdown")
            overall_ppr = df_x01["average"].mean()
            first9_ppr = df_x01["first9_average"].mean()

            col_detail1, col_detail2 = st.columns(2)
            with col_detail1:
                st.markdown("#### Averaging stats (PPR)")
                detail_df1 = pd.DataFrame([
                    ['Overall Average', f'{overall_ppr:.2f}', f'{best_avg:.2f} (Best)'],
                    ['First 9 Average', f'{first9_ppr:.2f}', f'{df_x01["first9_average"].max():.2f} (Best)']
                ], columns=['Metric', 'Value', 'Context'])
                st.dataframe(detail_df1.reset_index(drop=True), width='stretch', hide_index=True)

                st.markdown("#### Checkout Percentage")
                chart_df = df_x01.sort_values('created_at').reset_index(drop=True)
                chart_df['co_trend'] = chart_df['checkout_percent'].rolling(window=5, min_periods=1).mean()
                
                fig_co = go.Figure()
                fig_co.add_trace(go.Scatter(x=chart_df['created_at'], y=chart_df['checkout_percent'], mode='markers', name="Raw %", marker=dict(color=THEME["primary"], size=5), opacity=0.3))
                fig_co.add_trace(go.Scatter(x=chart_df['created_at'], y=chart_df['co_trend'], mode='lines', name="Fitted Curve", line=dict(color=THEME["accent"], width=3, shape='spline'), fill='tozeroy', fillcolor=hex_to_rgba(THEME['accent'], 0.15)))
                fig_co.update_layout(yaxis_tickformat='.0%', height=250, margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
                fig_co = apply_minimalist_theme(fig_co)
                fig_co.update_xaxes(showgrid=False)
                st.plotly_chart(fig_co, width='stretch')

            with col_detail2:
                st.markdown("#### High scores")
                score_groups = df_x01_turns.groupby('turn_score').size().reset_index(name='count')
                t100 = score_groups[(score_groups['turn_score'] >= 100) & (score_groups['turn_score'] < 140)]['count'].sum()
                t140 = score_groups[(score_groups['turn_score'] >= 140) & (score_groups['turn_score'] < 180)]['count'].sum()
                t171 = score_groups[(score_groups['turn_score'] >= 171) & (score_groups['turn_score'] < 180)]['count'].sum()
                
                score_data = pd.DataFrame({
                    'Category': ['100+', '140+', '171+', '180'],
                    'Total': [t100, t140, t171, total_180s]
                })
                fig_score = px.bar(score_data, x='Total', y='Category', orientation='h', text='Total')
                fig_score.update_traces(marker_color=THEME["primary"], textposition='outside')
                fig_score.update_layout(yaxis=dict(autorange="reversed"), bargap=0.3, height=350, margin=dict(l=0, r=40, t=10, b=0))
                fig_score = apply_minimalist_theme(fig_score)
                fig_score.update_xaxes(showgrid=True)
                fig_score.update_yaxes(showgrid=False)
                st.plotly_chart(fig_score, width='stretch')

            st.markdown("<br>", unsafe_allow_html=True)
            colE, colF = st.columns(2)
            with colE:
                st.markdown("### Top 10 Legs (X01)")
                if 'darts_thrown' in df_x01_legs.columns and not df_x01_legs.empty:
                    top_legs = df_x01_legs[df_x01_legs['darts_thrown'] > 0].nsmallest(10, 'darts_thrown')[['darts_thrown', 'average', 'created_at']]
                    top_legs.columns = ['Darts', 'Avg', 'Date']
                    top_legs['Avg'] = top_legs['Avg'].round(2)
                    top_legs['Date'] = top_legs['Date'].dt.strftime('%Y-%m-%d')
                    st.dataframe(top_legs.reset_index(drop=True), width='stretch', hide_index=True)
                else:
                    st.info("Leg details not fully populated yet.")

            with colF:
                st.markdown("### Top 10 Matches (X01 By Avg)")
                if not df_x01.empty:
                    top_matches = df_x01.nlargest(10, 'average')[['date', 'Opponent', 'average', 'checkout_percent']]
                    top_matches.columns = ['Date', 'Opponent', 'Average', 'Checkout %']
                    top_matches['Average'] = top_matches['Average'].round(2)
                    top_matches['Checkout %'] = (top_matches['Checkout %'] * 100).round(1).astype(str) + '%'
                    st.dataframe(top_matches.reset_index(drop=True), width='stretch', hide_index=True)

    # ------------------ CRICKET TAB ------------------
    with tab_cricket:
        sum_cricket, df_cricket, df_cricket_legs, df_cricket_throws, df_cricket_turns = get_variant_summary(p_matches, 'Cricket')

        if not sum_cricket:
            st.info("No Cricket data available for the selected filters.")
        else:
            cricket_turns = len(df_cricket_turns)
            mask_targets = df_cricket_throws['segment_number'].isin([15, 16, 17, 18, 19, 20, 25])
            target_throws = df_cricket_throws[mask_targets].copy()
            total_marks = target_throws['multiplier'].sum()
            best_mpr_leg = df_cricket_legs['mpr'].max() if 'mpr' in df_cricket_legs.columns else 0
            avg_mpr = (total_marks / cricket_turns if cricket_turns > 0 else 0)

            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f'<div class="ad-metric"><h3>Legs played</h3><h2>{sum_cricket["legs_played"]} / {sum_cricket["legs_won"]} won</h2></div>', unsafe_allow_html=True)
            c2.markdown(f'<div class="ad-metric"><h3>Total Darts (Cricket)</h3><h2>{sum_cricket["total_darts"]:,}</h2></div>', unsafe_allow_html=True)
            c3.markdown(f'<div class="ad-metric"><h3>Overall Avg MPR</h3><h2>{avg_mpr:.2f}</h2></div>', unsafe_allow_html=True)
            c4.markdown(f'<div class="ad-metric"><h3>Best Leg MPR</h3><h2>{best_mpr_leg:.2f}</h2></div>', unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)

            st.markdown("### Performance breakdown")
            detail_col1, detail_col2 = st.columns(2)
            with detail_col1:
                st.markdown("#### Averaging stats (MPR)")
                detail_df1 = pd.DataFrame([
                    ['Detailed Average MPR', f'{avg_mpr:.2f}'],
                    ['Best Leg MPR', f'{best_mpr_leg:.2f}']
                ], columns=['Metric', 'Value'])
                st.dataframe(detail_df1.reset_index(drop=True), width='stretch', hide_index=True)

            with detail_col2:
                st.markdown("#### Total marks")
                if 'marks_5' in df_cricket_legs.columns:
                    mark_data = pd.DataFrame({
                        'Metric': ['5 Marks', '6 Marks', '7 Marks', '8 Marks', '9 Marks', 'White Horse'],
                        'Total': [df_cricket_legs['marks_5'].sum(), df_cricket_legs['marks_6'].sum(),
                                   df_cricket_legs['marks_7'].sum(), df_cricket_legs['marks_8'].sum(),
                                   df_cricket_legs['marks_9'].sum(), df_cricket_legs['white_horse'].sum()],
                        'Per Leg': [(df_cricket_legs['marks_5'].sum() / sum_cricket['legs_played'] if sum_cricket['legs_played'] > 0 else 0),
                                     (df_cricket_legs['marks_6'].sum() / sum_cricket['legs_played'] if sum_cricket['legs_played'] > 0 else 0),
                                     (df_cricket_legs['marks_7'].sum() / sum_cricket['legs_played'] if sum_cricket['legs_played'] > 0 else 0),
                                     (df_cricket_legs['marks_8'].sum() / sum_cricket['legs_played'] if sum_cricket['legs_played'] > 0 else 0),
                                     (df_cricket_legs['marks_9'].sum() / sum_cricket['legs_played'] if sum_cricket['legs_played'] > 0 else 0),
                                     (df_cricket_legs['white_horse'].sum() / sum_cricket['legs_played'] if sum_cricket['legs_played'] > 0 else 0)]
                    })
                    mark_data['Per Leg'] = mark_data['Per Leg'].apply(lambda x: f'{x:.2f}')
                    st.dataframe(mark_data.reset_index(drop=True), width='stretch', hide_index=True)
                else:
                    st.info("Detailed mark statistics are not fully populated yet.")

    # ------------------ COUNT UP TAB ------------------
    with tab_countup:
        sum_cup, df_cup, df_cup_legs, df_cup_throws, df_cup_turns = get_variant_summary(p_matches, 'Count Up')

        if not sum_cup:
            st.info("No Count Up data available for the selected filters.")
        else:
            cup_ppr = df_cup["average"].mean()
            best_ppr = df_cup["average"].max()
            cup_turns_df = df_cup_turns.copy()
            t180s = len(cup_turns_df[cup_turns_df['turn_score'] == 180])
            overall_score = df_cup["first9_average"].mean() 
            
            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f'<div class="ad-metric"><h3>Total Darts (Count Up)</h3><h2>{sum_cup["total_darts"]:,}</h2></div>', unsafe_allow_html=True)
            c2.markdown(f'<div class="ad-metric"><h3>Overall Avg PPR</h3><h2>{cup_ppr:.2f}</h2></div>', unsafe_allow_html=True)
            c3.markdown(f'<div class="ad-metric"><h3>Avg. First 9 PPR</h3><h2>{overall_score:.2f}</h2></div>', unsafe_allow_html=True)
            c4.markdown(f'<div class="ad-metric"><h3>Best Leg PPR</h3><h2>{best_ppr:.2f}</h2></div>', unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)

            st.markdown("### Performance breakdown")
            detail_col1, detail_col2 = st.columns(2)
            with detail_col1:
                st.markdown("#### Averaging stats (PPR)")
                detail_df1 = pd.DataFrame([
                    ['Detailed Average PPR', f'{cup_ppr:.2f}'],
                    ['Best Leg PPR', f'{best_ppr:.2f}'],
                    ['Average First 9 PPR', f'{overall_score:.2f}']
                ], columns=['Metric', 'Value'])
                st.dataframe(detail_df1.reset_index(drop=True), width='stretch', hide_index=True)

            with detail_col2:
                st.markdown("#### High scores")
                score_groups = df_cup_turns.groupby('turn_score').size().reset_index(name='count')
                t100 = score_groups[(score_groups['turn_score'] >= 100) & (score_groups['turn_score'] < 140)]['count'].sum()
                t140 = score_groups[(score_groups['turn_score'] >= 140) & (score_groups['turn_score'] < 180)]['count'].sum()
                t171 = score_groups[(score_groups['turn_score'] >= 171) & (score_groups['turn_score'] < 180)]['count'].sum()
                
                score_data = pd.DataFrame({
                    'Metric': ['100+', '140+', '171+', '180'],
                    'Total': [t100, t140, t171, t180],
                    'Per Leg': [(t100 / sum_cup['legs_played'] if sum_cup['legs_played'] > 0 else 0),
                                 (t140 / sum_cup['legs_played'] if sum_cup['legs_played'] > 0 else 0),
                                 (t171 / sum_cup['legs_played'] if sum_cup['legs_played'] > 0 else 0),
                                 (t180 / sum_cup['legs_played'] if sum_cup['legs_played'] > 0 else 0)]
                })
                score_data['Per Leg'] = score_data['Per Leg'].apply(lambda x: f'{x:.2f}')
                st.dataframe(score_data.reset_index(drop=True), width='stretch', hide_index=True)

    # ------------------ RANDOM CHECKOUT TAB ------------------
    with tab_rc:
        sum_rc, df_rc, df_rc_legs, df_rc_throws, df_rc_turns = get_variant_summary(p_matches, 'RC')

        if not sum_rc:
            st.info("No Random Checkout data available for the selected filters.")
        else:
            avg_darts_thrown = df_rc["first9_average"].mean() 
            avg_checkout_percent = df_rc["checkout_percent"].mean()
            t180s = len(df_rc_turns[df_rc_turns['turn_score'] == 180])

            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f'<div class="ad-metric"><h3>Total Darts (RC)</h3><h2>{sum_rc["total_darts"]:,}</h2></div>', unsafe_allow_html=True)
            c2.markdown(f'<div class="ad-metric"><h3>Overall Avg Checkout %</h3><h2>{avg_checkout_percent:.0%}</h2></div>', unsafe_allow_html=True)
            c3.markdown(f'<div class="ad-metric"><h3>Avg. First 9 PPR</h3><h2>{avg_darts_thrown:.2f}</h2></div>', unsafe_allow_html=True)
            c4.markdown(f'<div class="ad-metric"><h3>Total 180s</h3><h2>{t180s}</h2></div>', unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)

            st.markdown("### Performance breakdown")
            detail_col1, detail_col2 = st.columns(2)
            with detail_col1:
                st.markdown("#### High scores")
                score_groups = df_rc_turns.groupby('turn_score').size().reset_index(name='count')
                t100 = score_groups[(score_groups['turn_score'] >= 100) & (score_groups['turn_score'] < 140)]['count'].sum()
                t140 = score_groups[(score_groups['turn_score'] >= 140) & (score_groups['turn_score'] < 180)]['count'].sum()
                t171 = score_groups[(score_groups['turn_score'] >= 171) & (score_groups['turn_score'] < 180)]['count'].sum()
                
                score_data = pd.DataFrame({
                    'Metric': ['100+', '140+', '171+', '180'],
                    'Total': [t100, t140, t171, t180],
                    'Per Leg': [(t100 / sum_rc['legs_played'] if sum_rc['legs_played'] > 0 else 0),
                                 (t140 / sum_rc['legs_played'] if sum_rc['legs_played'] > 0 else 0),
                                 (t171 / sum_rc['legs_played'] if sum_rc['legs_played'] > 0 else 0),
                                 (t180 / sum_rc['legs_played'] if sum_rc['legs_played'] > 0 else 0)]
                })
                score_data['Per Leg'] = score_data['Per Leg'].apply(lambda x: f'{x:.2f}')
                st.dataframe(score_data.reset_index(drop=True), width='stretch', hide_index=True)

            with detail_col2:
                st.markdown("#### Averaging stats")
                detail_df1 = pd.DataFrame([
                    ['Average Checkout %', f'{avg_checkout_percent:.0%}'],
                    ['Detailed PPR', f'{df_rc["average"].mean():.2f}']
                ], columns=['Metric', 'Value'])
                st.dataframe(detail_df1.reset_index(drop=True), width='stretch', hide_index=True)

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
        ring_color = THEME["grid_line"]
        
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
        st.plotly_chart(fig_pro, width='stretch')
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
    fig_avg.add_trace(go.Scatter(x=chart_df['created_at'], y=chart_df['avg_trend'], mode='lines', name="3-Dart (Fitted Curve)", line=dict(color=THEME["primary"], width=3, shape='spline'), fill='tozeroy', fillcolor=hex_to_rgba(THEME['primary'], 0.1)))
    fig_avg.add_trace(go.Scatter(x=chart_df['created_at'], y=chart_df['first9_trend'], mode='lines', name="First 9 (Fitted Curve)", line=dict(color=THEME["secondary"], width=3, shape='spline')))
    
    fig_avg.update_layout(title="Averages Over Time (Smoothed)")
    st.plotly_chart(apply_minimalist_theme(fig_avg), width='stretch')
    
    col1, col2 = st.columns(2)
    with col1:
        dart_avg = p_throws.groupby('dart_number')['dart_score'].mean().reset_index()
        dart_avg['dart_score'] = dart_avg['dart_score'] * 3 
        dart_avg['dart_number'] = dart_avg['dart_number'].astype(str)
        fig_darts = px.bar(dart_avg, x='dart_number', y='dart_score', text_auto='.2f', color='dart_number', color_discrete_map=DART_COLORS)
        fig_darts.update_traces(showlegend=False)
        fig_darts.update_layout(title="Pace per Dart (x3)")
        st.plotly_chart(apply_minimalist_theme(fig_darts), width='stretch')
        
    with col2:
        leg_num_avg = p_legs.groupby('leg_number')['average'].mean().reset_index()
        fig_leg_num = px.bar(leg_num_avg, x='leg_number', y='average', text_auto='.1f')
        fig_leg_num.update_traces(marker_color=THEME["secondary"])
        fig_leg_num.update_xaxes(type='category')
        fig_leg_num.update_layout(title="Average by Leg Number")
        st.plotly_chart(apply_minimalist_theme(fig_leg_num), width='stretch')


# ==========================================================
# PAGE 3: MATCH CONTEXT
# ==========================================================
elif selected_player and page == "🔋 Match Context":
    st.markdown(f"## 🔋 Match Context: **{selected_player}**")
    fig_dur = px.scatter(p_matches, x='duration_sec', y='average', trendline="ols")
    fig_dur.update_traces(marker=dict(color=THEME["accent"], size=8, opacity=0.7))
    fig_dur.update_layout(title="Fatigue Check (Avg vs Match Duration in Secs)")
    st.plotly_chart(apply_minimalist_theme(fig_dur), width='stretch')
    
    col3, col4 = st.columns(2)
    with col3:
        starter_avg = p_legs.groupby('throw_order')['average'].mean().reset_index()
        fig_start = px.bar(starter_avg, x='throw_order', y='average', text_auto='.1f', color='throw_order', color_discrete_map={"Started": THEME["primary"], "Went Second": THEME["text_muted"]})
        fig_start.update_layout(title="Avg: Started vs Went Second", showlegend=False)
        st.plotly_chart(apply_minimalist_theme(fig_start), width='stretch')
        
    with col4:
        hour_avg = p_matches.groupby('hour')['average'].mean().reset_index()
        fig_hour = px.bar(hour_avg, x='hour', y='average', text_auto='.1f')
        fig_hour.update_traces(marker_color=THEME["secondary"])
        fig_hour.update_layout(title="Average by Time of Day (Hour)")
        fig_hour.update_xaxes(type='category')
        st.plotly_chart(apply_minimalist_theme(fig_hour), width='stretch')


# ==========================================================
# PAGE 4: DATABASE MANAGER 
# ==========================================================
elif page == "⚙️ Database Manager":
    st.markdown("## ⚙️ Database Manager")
    
    st.markdown("### 📥 Bulk History Importer")
    st.markdown("Scan your online Autodarts account and safely download all missing match history directly into your SQLite vault.")
    
    scan_mode = st.radio("Scan Mode", [
        "⚡ Quick Sync (Stops automatically when it reaches a match you already have saved)", 
        "🔍 Full Deep Scan (Scans every single page of your Autodarts history)"
    ])

    if "scraped_ids" not in st.session_state:
        st.session_state.scraped_ids = None

    if st.button("🔍 1. Scan Autodarts Account for Matches", width="stretch"):
        debug_log = st.empty()
        with st.spinner("Running paginated Playwright scraper..."):
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
                    existing_ids = matches['match_id'].tolist() if not matches.empty else []
                    stop_scanning = False
                    
                    while page_num <= max_pages and not stop_scanning:
                        debug_log.info(f"Extracting matches from Page {page_num}...")
                        hrefs = page.evaluate("Array.from(document.querySelectorAll('a')).map(a => a.href)")
                        
                        for href in hrefs:
                            if href:
                                match = re.search(r'/matches/([a-f0-9\-]{30,})', href)
                                if match: 
                                    mid = match.group(1)
                                    if "Quick Sync" in scan_mode and mid in existing_ids:
                                        stop_scanning = True
                                        break
                                    all_ids.add(mid)
                        
                        if stop_scanning:
                            debug_log.info(f"Reached already saved matches. Quick Sync stopped at page {page_num}.")
                            break
                        
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
                        st.error("🚨 Found 0 new matches!")
                    else:
                        st.success(f"✅ Successfully scraped {len(st.session_state.scraped_ids)} matches!")
                        
            except Exception as e:
                st.error(f"❌ Scraper crashed with error: {e}")

    if st.session_state.scraped_ids:
        st.markdown("### Select Matches to Import")
        existing_ids = matches['match_id'].tolist() if not matches.empty else []
        df = pd.DataFrame({"Match ID": st.session_state.scraped_ids})
        df["Already Saved"] = df["Match ID"].isin(existing_ids)
        df["Import?"] = ~df["Already Saved"]
        
        edited_df = st.data_editor(df, disabled=["Match ID", "Already Saved"], hide_index=True, width='stretch')
        
        if st.button("🚀 3. Start Bulk Import", width="stretch"):
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
        
        edited_del = st.data_editor(del_df, hide_index=True, disabled=["date", "Opponent", "average", "duration", "match_id"], width='stretch')
        to_delete = edited_del[edited_del['Delete?']]['match_id'].tolist()
        
        if st.button("🚨 Permanently Delete Selected Matches", type="primary", width="stretch"):
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
    
    if st.button("💾 Apply Theme", width="stretch"):
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"theme": new_theme}, f)
        expected_toml = f"[theme]\n{THEME_PROFILES[new_theme]['toml']}"
        with open(config_path, "w") as f:
            f.write(expected_toml)
        st.success(f"Theme changed to {new_theme}! Refreshing...")
        time.sleep(1)
        st.rerun()
       