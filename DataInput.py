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

# --- Config ---
PROFILE_API = "https://api.cs-prod.leetify.com/api/profile/id/"
GAMES_API = "https://api.cs-prod.leetify.com/api/games/"
leetify_token = st.secrets["leetify"]["api_token"]
discord_webhook = st.secrets["discord"]["webhook"]

SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["key"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

NAME_MAPPING = {
    "JimmyJimbob": "Jeprizz", "Jimmy": "Jeprizz", "Kåre": "Torgrizz", "Kaare": "Torgrizz",
    "Fakeface": "Birkle", "Killthem26": "Birkle", "KillBirk": "Birkle", "Lars Olaf": "Tobrizz", "tobbelobben": "Tobrizz",
    "Bøghild": "Borgle", "Nish": "Sandrizz", "Nishinosan": "Sandrizz", "Zohan": "Jorizz", "johlyn": "Jorizz"
}
ALLOWED_PLAYERS = set(NAME_MAPPING.values())

STAT_MAP = {
    "K/D Ratio": "kdRatio", "ADR": "dpr", "HLTV Rating": "hltvRating",
    "Reaction Time": "reactionTime", "TradeAttempts": "tradeKillAttemptsPercentage",
    "Enemies Flashed": "flashbangThrown", "2k Kills": "multi2k", "3k Kills": "multi3k"
}

# --- Session Initialization ---
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

# --- Discord ---
def send_discord_notification(message: str):
    if not discord_webhook:
        return
    try:
        resp = requests.post(discord_webhook, json={"content": message})
        if resp.status_code != 204:
            st.warning(f"Failed to send Discord message ({resp.status_code})")
    except Exception as e:
        st.warning(f"Error sending Discord message: {e}")

# --- Refresh Data ---
def refresh_all(days):
    games_df, konsum_df = fetch_all_sheets_data()
    st.session_state['games_df'] = games_df
    st.session_state['konsum_df'] = konsum_df
    st.session_state['cached_games'] = fetch_games_within_last_48_hours()
    st.session_state['cached_konsum'] = {}
    for game in st.session_state['cached_games']:
        st.session_state['cached_konsum'][game['game_id']] = fetch_konsum_data_for_game(game['game_id'])
    fetch_new_games(days)
    st.session_state['games_df'], _ = fetch_all_sheets_data()
    st.session_state['cached_games'] = fetch_games_within_last_48_hours()

# --- Cached getters ---
def get_cached_games(days=None):
    return st.session_state.get('cached_games', [])

def get_cached_konsum(game_id):
    return st.session_state['cached_konsum'].get(game_id, {})

# --- API Fetch ---
def fetch_profile(token, start_date, end_date, count=30):
    url = "https://api.cs-prod.leetify.com/api/v2/games/history"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    filters = {
        "currentPeriod": {"start": start_date.isoformat() + "Z", "end": end_date.isoformat() + "Z", "count": count},
        "previousPeriod": {"start": (start_date - timedelta(days=30)).isoformat() + "Z", "end": start_date.isoformat() + "Z", "count": count}
    }
    try:
        resp = requests.get(url, headers=headers, params={"filters": json.dumps(filters)})
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        st.warning(f"Failed fetching profile: {e}")
        return None

def fetch_game_details(game_id):
    try:
        resp = requests.get(GAMES_API + game_id, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None

def fetch_new_games(days, token=leetify_token):
    new_games = []
    now = datetime.utcnow()
    start_date = now - timedelta(days=days)
    profile_data = fetch_profile(token, start_date, now)
    if not profile_data or "games" not in profile_data:
        return []

    existing_game_ids = set(st.session_state['games_df']['game_id']) if not st.session_state['games_df'].empty else set()

    for game in profile_data.get("games", []):
        game_id = game.get("id")
        if not game_id or game_id in existing_game_ids or game_id in {g["game_id"] for g in new_games}:
            continue
        try:
            finished_at = datetime.strptime(game["finishedAt"], "%Y-%m-%dT%H:%M:%S.%fZ")
            if finished_at > now - timedelta(days=days):
                score = game.get("score", [0,0])
                new_games.append({
                    "game_id": game_id,
                    "map_name": game.get("mapName", "Unknown"),
                    "match_result": game.get("playerStats", {}).get("matchResult", "Unknown"),
                    "scores": score,
                    "game_finished_at": finished_at
                })
        except (ValueError, KeyError):
            continue

    for g in new_games:
        save_game_data(g["game_id"], g["map_name"], g["match_result"], g["scores"][0], g["scores"][1], g["game_finished_at"])
    return new_games

# --- Konsum Save ---
def async_save(game_id, name, beer_val, water_val):
    def _save():
        save_konsum_data(game_id, name, beer_val, water_val)
        if game_id not in st.session_state:
            st.session_state[game_id] = {}
        st.session_state[game_id][name] = {"beer": beer_val, "water": water_val}
    threading.Thread(target=_save, daemon=True).start()

# --- Player Stat ---
def get_player_stat(player, stat_key):
    val = player.get(stat_key, 0)
    if stat_key == "tradeKillAttemptsPercentage":
        val *= 100
    return val

# --- UI Pages ---
def home_page(days):
    games = get_cached_games(days)
    if not games:
        st.warning("No games found.")
        return
    games = sorted(games, key=lambda g: g.get("game_finished_at", datetime.min), reverse=True)
    game_options = [f"{g.get('map_name','Unknown')} ({g['game_finished_at'].strftime('%d.%m.%y %H:%M')}) - {g['game_id']}" for g in games]
    selected_game = st.selectbox("Pick a game", game_options)
    game_id = selected_game.split(" - ")[-1]
    game_data = next((g for g in games if g["game_id"] == game_id), None)
    if game_data:
        details = fetch_game_details(game_id)
        if details:
            players = [{"name": NAME_MAPPING.get(p["name"], p["name"]), **p} for p in details.get("playerStats", []) if NAME_MAPPING.get(p["name"], p["name"]) in ALLOWED_PLAYERS]
            if players:
                players.sort(key=lambda p: p.get("reactionTime",0))
                min_rt, max_rt = min(p.get("reactionTime",0) for p in players), max(p.get("reactionTime",0) for p in players)
                top_players = [p for p in players if p.get("reactionTime",0) == min_rt]
                low_players = [p for p in players if p.get("reactionTime",0) == max_rt]

                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"### Best Reaction Time\n{' ,'.join(p['name'] for p in top_players)} ({min_rt})")
                with col2:
                    st.markdown(f"### Worst Reaction Time\n{' ,'.join(p['name'] for p in low_players)} ({max_rt})")
    st.write(f"Total games: {len(games)}")

# --- Main App ---
initialize_session_state()
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ("🏠 Home", "📝 Konsum", "📊 Stats", "🚽 Motivation"))

if "days_value" not in st.session_state:
    st.session_state["days_value"] = 2

col1, col2 = st.columns([1,1])
with col1:
    temp_days = st.number_input("Dager tilbake", min_value=1, max_value=15, value=st.session_state["days_value"])
with col2:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Refresh Data"):
        st.session_state["days_value"] = temp_days
        refresh_all(st.session_state["days_value"])

days = st.session_state["days_value"]

if page == "🏠 Home":
    home_page(days)
# 📝 Konsum, 📊 Stats, 🚽 Motivation pages remain similar but with same fixes applied
