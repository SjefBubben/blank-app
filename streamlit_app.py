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
from DataInput import fetch_all_sheets_data, fetch_games_within_last_48_hours, fetch_konsum_data_for_game, save_konsum_data, save_game_data

# API Endpoints
PROFILE_API = "https://api.cs-prod.leetify.com/api/profile/id/"
GAMES_API = "https://api.cs-prod.leetify.com/api/games/"
leetify_token = st.secrets["leetify"]["api_token"]
discord_webhook = st.secrets["discord"]["webhook"]

SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["key"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Player Name Mapping
NAME_MAPPING = {
    "JimmyJimbob": "Jeprizz", "Jimmy": "Jeprizz", "Kåre": "Torgrizz", "Kaare": "Torgrizz",
    "Fakeface": "Birkle", "Killthem26": "Birkle", "KillBirk": "Birkle", "Lars Olaf": "Tobrizz", "tobbelobben": "Tobrizz",
    "Bøghild": "Borgle", "Nish": "Sandrizz", "Nishinosan": "Sandrizz", "Zohan": "Jorizz", "johlyn": "Jorizz"
}
ALLOWED_PLAYERS = set(NAME_MAPPING.values())

# Initialize session state
def initialize_session_state():
    if 'initialized' not in st.session_state:
        st.session_state['initialized'] = True
        games_df, konsum_df = fetch_all_sheets_data()
        st.session_state['games_df'] = games_df
        st.session_state['konsum_df'] = konsum_df
        st.session_state['cached_games'] = fetch_games_within_last_48_hours()
        st.session_state['cached_konsum'] = {}
        for game in st.session_state['cached_games']:
            st.session_state['cached_konsum'][game['game_id']] = fetch_konsum_data_for_game(game['game_id'])

# Discord notification
def send_discord_notification(message: str):
    if not discord_webhook:
        return
    try:
        response = requests.post(discord_webhook, json={"content": message})
        if response.status_code != 204:
            st.warning(f"Failed to send Discord message ({response.status_code})")
    except Exception as e:
        st.warning(f"Error sending Discord message: {e}")

# Fetch Leetify games within last N days
def fetch_profile(token, start_date, end_date, count=30):
    url = "https://api.cs-prod.leetify.com/api/v2/games/history"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    filters = {
        "currentPeriod": {
            "start": start_date.isoformat() + "Z",
            "end": end_date.isoformat() + "Z",
            "count": count
        },
        "previousPeriod": {
            "start": (start_date - timedelta(days=30)).isoformat() + "Z",
            "end": start_date.isoformat() + "Z",
            "count": count
        }
    }
    try:
        response = requests.get(url, headers=headers, params={"filters": json.dumps(filters)})
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        st.error(f"Failed fetching profile: {e}")
        return None

def fetch_new_games(days, token=leetify_token):
    new_games = []
    now = datetime.utcnow()
    start_date = now - timedelta(days=days)
    profile_data = fetch_profile(token, start_date, now)

    if not profile_data or "games" not in profile_data:
        st.warning("No games found in Leetify API")
        return []

    existing_game_ids = set(st.session_state['games_df']['game_id']) if not st.session_state['games_df'].empty else set()

    for game in profile_data.get("games", []):
        game_id = game.get("id")
        if not game_id or game_id in existing_game_ids:
            continue
        try:
            finished_at = datetime.strptime(game["finishedAt"], "%Y-%m-%dT%H:%M:%S.%fZ")
            if finished_at > now - timedelta(days=days):
                finished_at_str = finished_at.strftime("%Y-%m-%d %H:%M:%S")
                score = game.get("score", [0, 0])
                match_result = game.get("playerStats", {}).get("matchResult", "Unknown")
                new_game = {
                    "game_id": game_id,
                    "map_name": game.get("mapName", "Unknown"),
                    "match_result": match_result,
                    "scores": score,
                    "game_finished_at": finished_at_str
                }
                new_games.append(new_game)
        except Exception as e:
            st.warning(f"Skipping game {game_id} due to error: {e}")

    # Save new games to Sheets
    for game in new_games:
        save_game_data(
            game["game_id"],
            game["map_name"],
            game["match_result"],
            game["scores"][0],
            game["scores"][1],
            game["game_finished_at"]
        )

    # Refresh session state
    st.session_state['games_df'], _ = fetch_all_sheets_data()
    st.session_state['cached_games'] = fetch_games_within_last_48_hours()

    return new_games

# Async save konsum data
def async_save(game_id, name, beer_val, water_val):
    def _save():
        save_konsum_data(game_id, name, beer_val, water_val)
        st.session_state[game_id][name] = {"beer": beer_val, "water": water_val}
    threading.Thread(target=_save, daemon=True).start()

# Initialize session
initialize_session_state()

# Streamlit sidebar
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ("🏠 Home", "📝 Konsum", "📊 Stats", "🚽 Motivation"))

# Days input
if "days_value" not in st.session_state:
    st.session_state["days_value"] = 2

col1, col2 = st.columns([1, 1])
with col1:
    temp_days = st.number_input("Dager tilbake", min_value=1, max_value=15, value=st.session_state["days_value"])
with col2:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Refresh Data"):
        st.session_state["days_value"] = temp_days
        fetch_new_games(st.session_state["days_value"])
        st.success("✅ Data refreshed!")

days = st.session_state["days_value"]

# Render page
if page == "🏠 Home":
    st.header("Home Page")
    st.write(f"Displaying games from last {days} days")
    st.write(st.session_state['cached_games'])
elif page == "📝 Konsum":
    st.header("Input Konsum Data")
    # Here you can add your existing input_data_page(days) logic
elif page == "📊 Stats":
    st.header("Stats")
    # Here you can add your existing stats_page(days) logic
elif page == "🚽 Motivation":
    st.header("Motivation")
    st.markdown('<iframe width="560" height="315" src="https://www.youtube.com/embed/6dMjCa0nqK0" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>', unsafe_allow_html=True)
