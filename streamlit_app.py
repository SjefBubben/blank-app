import streamlit as st
import requests
import base64
import json
import pandas as pd
import plotly.express as px
import threading
from supabase import create_client
from operator import itemgetter
from datetime import datetime, timedelta
from io import StringIO
from DataInput import (
    fetch_all_sheets_data,
    fetch_games_within_last_48_hours,
    fetch_konsum_data_for_game,
    save_konsum_data,
    save_game_data
)

# -----------------------
# API & Secrets
# -----------------------
PROFILE_API = "https://api.cs-prod.leetify.com/api/profile/id/"
GAMES_API = "https://api.cs-prod.leetify.com/api/games/"

leetify_token = st.secrets["leetify"]["api_token"]
discord_webhook = st.secrets["discord"]["webhook"]
SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["key"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# -----------------------
# Player Mapping
# -----------------------
NAME_MAPPING = {
    "JimmyJimbob": "Jepprizz", "Jimmy": "Jepprizz",
    "Kåre": "Torgrizz", "Kaare": "Torgrizz",
    "Fakeface": "Birkle", "Killthem26": "Birkle", "Killbirk": "Birkle",
    "Lars Olaf": "Tobrizz", "tobbelobben": "Tobrizz",
    "Bøghild": "Borgle",
    "Nish": "Sandrizz", "Nishinosan": "Sandrizz",
    "Zohan": "Jorizz", "johlyn": "Jorizz"
}
ALLOWED_PLAYERS = set(NAME_MAPPING.values())

# -----------------------
# Supabase Data Fetch
# -----------------------
def fetch_supabase_konsum_data():
    """Fetch all player consumption data from Supabase."""
    try:
        response = supabase.table("entries").select("*").execute()
        if not response.data:
            print("⚠️ No consumption data found in Supabase.")
            return pd.DataFrame()
        df = pd.DataFrame(response.data)
        # Parse datetime
        df['datetime'] = pd.to_datetime(df.get('datetime', pd.Series()), utc=True, errors='coerce')
        # Keep original name column
        df.rename(columns={'name': 'player_name'}, inplace=True)
        return df
    except Exception as e:
        print(f"⚠️ Supabase fetch error: {e}")
        return pd.DataFrame()

# -----------------------
# Map Konsum to Games
# -----------------------
def map_konsum_to_games_and_save(konsum_df, games_df, hours_window=24):
    """Map Supabase konsum entries to the closest previous game and save."""
    if konsum_df.empty or games_df.empty:
        print("⚠️ No konsum or game data to map.")
        return

    # --- Prepare data ---
    games_df = games_df.copy()
    games_df['game_finished_at'] = pd.to_datetime(games_df['game_finished_at'], utc=True, errors='coerce')
    games_df = games_df.dropna(subset=['game_finished_at']).sort_values('game_finished_at')

    konsum_df['datetime'] = pd.to_datetime(konsum_df['datetime'], utc=True, errors='coerce')
    konsum_df = konsum_df.dropna(subset=['datetime'])

    # --- Normalize drink types ---
    def map_drink(x):
        if not isinstance(x, str):
            return None
        x_lower = x.lower()
        if "water" in x_lower:
            return "water"
        elif "beer" in x_lower:
            return "beer"
        return None

    konsum_df['drink_type'] = konsum_df['bgdata'].map(map_drink)
    konsum_df = konsum_df.dropna(subset=['drink_type'])

    # --- Map player names ---
    konsum_df['player_name_mapped'] = konsum_df['player_name'].map(NAME_MAPPING)
    konsum_df['player_name_mapped'] = konsum_df['player_name_mapped'].fillna(konsum_df['player_name'])

    # --- Prepare batch updates ---
    batch_updates = {}
    saved_count = 0
    skipped_count = 0

    for _, row in konsum_df.iterrows():
        player_name = row.get('player_name_mapped')
        drink_type = row.get('drink_type')
        ts = row.get('datetime')
        entry_id = row.get('id')

        if not player_name or pd.isna(ts) or pd.isna(entry_id):
            continue

        # Find closest previous game
        past_games = games_df[games_df['game_finished_at'] <= ts].sort_values('game_finished_at', ascending=False)
        if past_games.empty:
            skipped_count += 1
            continue

        closest_game = past_games.iloc[0]
        game_id = closest_game['game_id']
        game_time = closest_game['game_finished_at']

        if ts - game_time > pd.Timedelta(hours=hours_window):
            skipped_count += 1
            continue

        # Initialize batch entry
        if game_id not in batch_updates:
            batch_updates[game_id] = {}
        if player_name not in batch_updates[game_id]:
            existing = st.session_state['cached_konsum'].get(game_id, {}).get(player_name, {'beer': 0, 'water': 0, 'ids': []})
            existing.setdefault('ids', [])
            batch_updates[game_id][player_name] = existing.copy()

        # Only count if ID not already present
        if entry_id not in batch_updates[game_id][player_name]['ids']:
            batch_updates[game_id][player_name][drink_type] += 1
            batch_updates[game_id][player_name]['ids'].append(entry_id)
            saved_count += 1

    # Save updates
    if batch_updates:
        save_konsum_data(batch_updates)
        for game_id, players in batch_updates.items():
            if game_id not in st.session_state['cached_konsum']:
                st.session_state['cached_konsum'][game_id] = {}
            for player_name, values in players.items():
                st.session_state['cached_konsum'][game_id][player_name] = values

    print(f"✅ Saved {saved_count} new konsum records.")
    print(f"🚫 Skipped {skipped_count} konsum entries.")

# -----------------------
# Session State Initialization
# -----------------------
def initialize_session_state(days=2):
    if 'initialized' not in st.session_state:
        st.session_state['initialized'] = True
        games_df, konsum_df = fetch_all_sheets_data()
        st.session_state['games_df'] = games_df
        st.session_state['konsum_df'] = konsum_df
        cached_games = fetch_games_within_last_48_hours()
        st.session_state['cached_games'] = cached_games
        st.session_state['cached_konsum'] = {}
        for game in cached_games:
            st.session_state['cached_konsum'][game['game_id']] = fetch_konsum_data_for_game(game['game_id'])

# -----------------------
# Discord Notification
# -----------------------
def send_discord_notification(message: str):
    if not discord_webhook:
        return
    try:
        response = requests.post(discord_webhook, json={"content": message})
        if response.status_code != 204:
            st.warning(f"Failed to send Discord message ({response.status_code})")
    except Exception as e:
        st.warning(f"Error sending Discord message: {e}")

# -----------------------
# Remaining functions...
# (refresh_all, fetch_profile, fetch_game_details, home_page, input_data_page,
# stats_page, download_full_database, motivation_page, etc.)
# -----------------------

# -----------------------
# Main UI
# -----------------------
def img_to_base64(img_path):
    with open(img_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

img_base64 = img_to_base64("bubblogo2.png")
st.markdown(f"""
<div style="
display: flex; align-items: center; justify-content: center; height: 150px; text-align: center;">
<img src="data:image/png;base64,{img_base64}" width="80" style="margin-right: 10px;">
<h1 style="margin: 0;">Bubberne Gaming</h1>
</div>
""", unsafe_allow_html=True)

# Start caching
initialize_session_state()

# Sidebar navigation
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ("🏠 Home", "📝 Konsum", "📊 Stats", "🚽 Motivation"))

# Days input
if "days_value" not in st.session_state:
    st.session_state["days_value"] = 2

col1, col2 = st.columns([1, 1])
with col1:
    temp_days = st.number_input("Dager tilbake", min_value=1, max_value=15,
                                value=st.session_state["days_value"], key="temp_days_input")
with col2:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Refresh Data"):
        st.session_state["days_value"] = temp_days
        refresh_all(st.session_state["days_value"])

days = st.session_state["days_value"]

if page == "🏠 Home":
    home_page(days)
elif page == "📝 Konsum":
    input_data_page(days)
elif page == "📊 Stats":
    stats_page(days)
elif page == "🚽 Motivation":
    motivation_page()
