import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from operator import itemgetter
from datetime import datetime, timedelta
from io import StringIO
from DataInout import fetch_games_within_last_48_hours, fetch_konsum_data_for_game, save_konsum_data, save_game_data

# API Endpoints
PROFILE_API = "https://api.cs-prod.leetify.com/api/profile/id/"
GAMES_API = "https://api.cs-prod.leetify.com/api/games/"

# List of SteamIDs to fetch games from
STEAM_IDS = ["76561197983741618", "76561198048455133", "76561198021131347"]

# Player Name Mapping (unchanged)
NAME_MAPPING = {
    "JimmyJimbob": "Jeprizz", "Jimmy": "Jeprizz", "Kåre": "Torgrizz", "Kaare": "Torgrizz",
    "Fakeface": "Birkle", "Killthem26": "Birkle", "Lars Olaf": "Tobrizz", "tobbelobben": "Tobrizz",
    "Bøghild": "Borgle", "Nish": "Sandrizz", "Nishinosan": "Sandrizz", "Zohan": "Jorizz", "johlyn": "Jorizz"
}
ALLOWED_PLAYERS = set(NAME_MAPPING.values())

# Fetch Functions
def fetch_profile(steam_id):
    try:
        response = requests.get(PROFILE_API + steam_id, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None

def fetch_game_details(game_id):
    try:
        response = requests.get(GAMES_API + game_id, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None

def fetch_new_games(days=2):
    saved_games = fetch_games_within_last_48_hours(days)
    saved_game_ids = {g["game_id"] for g in saved_games}
    new_games = []
    games_to_fetch = set()
    now = datetime.utcnow()

    for steam_id in STEAM_IDS:
        profile_data = fetch_profile(steam_id)
        if not profile_data:
            continue

        for game in profile_data.get("games", []):
            game_id = game.get("gameId")
            if game_id not in saved_game_ids and game_id not in {g["game_id"] for g in new_games}:
                try:
                    finished_at = datetime.strptime(game["gameFinishedAt"], "%Y-%m-%dT%H:%M:%S.%fZ")
                    if finished_at > now - timedelta(days=days):
                        finished_at_str = finished_at.strftime("%Y-%m-%d %H:%M:%S")
                        new_games.append({
                            "game_id": game_id,
                            "map_name": game.get("mapName", "Unknown"),  # Mapping API's mapName to map_name
                            "match_result": game.get("matchResult", "Unknown"),
                            "scores": game.get("scores", [0, 0]),
                            "game_finished_at": finished_at
                        })
                        games_to_fetch.add(game_id)
                except (ValueError, KeyError):
                    continue

    for game in new_games:
        save_game_data(
            game["game_id"],
            game["map_name"],
            game["match_result"],
            game["scores"][0],
            game["scores"][1],
            game["game_finished_at"].strftime("%Y-%m-%d %H:%M:%S")
        )

    game_details = {gid: fetch_game_details(gid) for gid in games_to_fetch if fetch_game_details(gid)}
    for game in new_games:
        game["details"] = game_details.get(game["game_id"], {})

    return new_games

# Rest of the functions (get_cached_games, get_cached_konsum, etc.) remain unchanged unless further customization is needed

@st.cache_data(ttl=300)
def get_cached_games(days=2):
    return fetch_games_within_last_48_hours(days)

@st.cache_data(ttl=300)
def get_cached_konsum(game_id):
    return fetch_konsum_data_for_game(game_id) or {}

# Stat Mapping and Helper
stat_display_mapping = {
    "K/D Ratio": "kdRatio", "ADR (Average Damage per Round)": "dpr", "HLTV Rating": "hltvRating",
    "Enemies Flashed": "flashbangThrown", "Friends Flashed": "flashbangHitFoe", "Avg. Unused Utility": "utilityOnDeathAvg",
    "Trade Kill Opportunities": "tradeKillOpportunities", "Trade Kill Attempts": "tradeKillAttempts",
    "Trade Kill Success": "tradeKillsSucceeded", "2k Kills": "multi2k", "3k Kills": "multi3k",
    "4k Kills": "multi4k", "5k Kills": "multi5k", "Flashbang Leading to Kill": "flashbangLeadingToKill",
    "Reaction Time": "reactionTime", "HE Grenades Thrown": "heThrown", "Molotovs Thrown": "molotovThrown",
    "Smokes Thrown": "smokeThrown"
}

def get_player_stat(player, stat_key):
    return player.get(stat_key, 0)

# Home Page (No Session State)
def home_page():
    days = st.number_input("Days back", min_value=1, max_value=15, value=2)
    with st.spinner("Fetching games from all profiles..."):
        new_games = fetch_new_games(days)
        games = sorted(get_cached_games(days), key=lambda x: x["game_finished_at"], reverse=True)

    if not games:
        st.warning("No games found across all profiles.")
        return

    game_options = [f"{g.get('map_name', 'Unknown')} ({g['game_finished_at'].strftime('%d.%m.%y %H:%M')}) - {g['game_id']}" for g in games]
    selected_game = st.selectbox("Pick a game", game_options)
    game_id = selected_game.split(" - ")[-1]
    game_data = next((g for g in games if g["game_id"] == game_id), None)

    if game_data:
        details = fetch_game_details(game_id)
        if details:
            players = [
                {"name": NAME_MAPPING.get(p["name"], p["name"]), "reactionTime": p.get("reactionTime", 0),
                 "tradeKillAttemptsPercentage": p.get("tradeKillAttemptsPercentage", 0),
                 "utilityOnDeathAvg": p.get("utilityOnDeathAvg", 0),
                 "hltvRating": p.get("hltvRating", 0)}
                for p in details.get("playerStats", []) if NAME_MAPPING.get(p["name"], p["name"]) in ALLOWED_PLAYERS
            ]
            if players:
                players.sort(key=itemgetter("reactionTime"))
                min_rt = min(p["reactionTime"] for p in players)
                max_rt = max(p["reactionTime"] for p in players)

                best_trade = max(p["tradeKillAttemptsPercentage"]*100 for p in players)
                worst_trade = min(p["tradeKillAttemptsPercentage"]*100 for p in players)

                top_players = [p for p in players if p["reactionTime"] == min_rt]
                low_players = [p for p in players if p["reactionTime"] == max_rt]

                best_trade_players = [p for p in players if p["tradeKillAttemptsPercentage"] * 100 == best_trade]
                worst_trade_players = [p for p in players if p["tradeKillAttemptsPercentage"] * 100 == worst_trade]

                worst_util = max(p.get("utilityOnDeathAvg", 0) for p in players)  # High is bad
                best_hltv = max(p.get("hltvRating", 0) for p in players)  # High is good

                worst_util_players = [p for p in players if p.get("utilityOnDeathAvg",0) == worst_util]
                best_hltv_players = [p for p in players if p.get("hltvRating",0) == best_hltv]

                col1, col2 = st.columns(2)

                with col1:
                    st.markdown(f"""
                        <div style="padding: 15px; background-color: #4CAF50; color: white; border-radius: 10px; text-align: center;">
                            <h3>🔥 Reaction Time</h3>
                            <h4>💪 Gooner: {', '.join(p['name'] for p in top_players)} ({min_rt}s)</h4>
                            <h4>🍺 Pils-bitch: {', '.join(p['name'] for p in low_players)} ({max_rt}s)</h4>
                        </div>
                    """, unsafe_allow_html=True)

                with col2:
                    st.markdown(f"""
                        <div style="padding: 15px; background-color: #2196F3; color: white; border-radius: 10px; text-align: center;">
                            <h3>🎯 Trade Kill Attempts</h3>
                            <h4>✅ Rizzler: {', '.join(p['name'] for p in best_trade_players)} ({best_trade:.1f}%)</h4>
                            <h4>❌ Baiterbot: {', '.join(p['name'] for p in worst_trade_players)} ({worst_trade:.1f}%)</h4>
                        </div>
                    """, unsafe_allow_html=True)

                col3, col4 = st.columns(2)

                with col3:
                    st.markdown(f"""
                        <div style="padding: 15px; background-color: #F44336; color: white; border-radius: 10px; text-align: center;">
                            <h3>💣 Utility on Death</h3>
                            <h4>🔥 McRizzler: {', '.join(p['name'] for p in worst_util_players)} ({worst_util:.2f})</h4>
                        </div>
                    """, unsafe_allow_html=True)

                with col4:
                    st.markdown(f"""
                        <div style="padding: 15px; background-color: #4CAF50; color: white; border-radius: 10px; text-align: center;">
                            <h3>🏆 Best HLTV Rating</h3>
                            <h4>⭐ OhioMaster: {', '.join(p['name'] for p in best_hltv_players)} ({best_hltv:.2f})</h4>
                        </div>
                    """, unsafe_allow_html=True)

    if new_games:
        st.subheader("New Games")
        for g in new_games:
            st.write(f"{g['map_name']} - {g['match_result'].capitalize()} ({g['scores'][0]}:{g['scores'][1]}) - ID: {g['game_id']}")
    
    st.write(f"Total games across all profiles: {len(games)}")

# Input Data Page
def input_data_page():
    st.header("Input BubbeData")
    days = st.number_input("Days back", min_value=1, max_value=10, value=2)
    games = sorted(get_cached_games(days), key=lambda x: x.get("game_finished_at", datetime.min), reverse=True)

    if not games:
        st.warning("No games found in the selected timeframe.")
        return

    for game in games:
        

        details = fetch_game_details(game.get("game_id"))
        if not details:
            st.write(f"Skipping game {game.get('game_id', 'unknown')} - no details available.")
            continue

        # Safely access game data with defaults
        map_name = game.get("map_name", "Unknown")
        match_result = game.get("match_result", "Unknown")
        scores = [game["score_team1"], game["score_team2"]]
        game_finished_at = game.get("game_finished_at")
        
        # Ensure game_finished_at is a datetime object
        if isinstance(game_finished_at, str):
            try:
                game_finished_at = datetime.strptime(game_finished_at, "%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                game_finished_at = datetime.now()  # Fallback to now if parsing fails
        elif not isinstance(game_finished_at, datetime):
            game_finished_at = datetime.now()  # Fallback if not a datetime

        label = f"{map_name} - {match_result} ({scores[0]}:{scores[1]}) - {game_finished_at.strftime('%d.%m.%y %H:%M')}"
        with st.expander(label):
            konsum = st.session_state.get(game["game_id"], fetch_konsum_data_for_game(game["game_id"]) or {})
            st.session_state[game["game_id"]] = konsum

            for p in details.get("playerStats", []):
                name = NAME_MAPPING.get(p["name"], p["name"])
                if name in ALLOWED_PLAYERS:
                    st.write(f"{name} - K/D: {p['kdRatio']}, ADR: {p['dpr']}, HLTV: {p['hltvRating']}")
                    prev_beer = konsum.get(name, {}).get("beer", 0)
                    prev_water = konsum.get(name, {}).get("water", 0)
                    beer = st.number_input(f"Beers for {name}", min_value=0, value=prev_beer, key=f"beer-{name}-{game['game_id']}")
                    water = st.number_input(f"Water for {name}", min_value=0, value=prev_water, key=f"water-{name}-{game['game_id']}")
                    if beer != prev_beer or water != prev_water:
                        save_konsum_data(game["game_id"], name, beer, water)
                        st.session_state[game["game_id"]][name] = {"beer": beer, "water": water}
                        st.success(f"Updated {name}: {beer} beers, {water} water")

# Stats Page
STAT_MAP = {
    "K/D Ratio": "kdRatio", "ADR": "dpr", "HLTV Rating": "hltvRating", "Reaction Time": "reactionTime",
    "Enemies Flashed": "flashbangThrown", "2k Kills": "multi2k", "3k Kills": "multi3k"
}

def stats_page():
    st.header("Stats")
    days = st.number_input("Days back", min_value=1, max_value=7, value=2)
    stat_options = list(STAT_MAP.keys()) + ["Beer", "Water"]
    selected_stat = st.selectbox("Stat to plot", stat_options)
    stat_key = STAT_MAP.get(selected_stat, selected_stat.lower())

    with st.spinner("Loading stats..."):
        games = sorted(get_cached_games(days), key=lambda x: x["game_finished_at"])
        stats_data = []

        for game in games:
            details = fetch_game_details(game["game_id"])
            konsum = get_cached_konsum(game["game_id"])
            game_label = f"{game['map_name']} ({game['game_finished_at'].strftime('%d.%m.%y %H:%M')})"

            for p in details.get("playerStats", []):
                name = NAME_MAPPING.get(p["name"], p["name"])
                if name in ALLOWED_PLAYERS:
                    value = konsum.get(name, {}).get(stat_key, 0) if stat_key in ["beer", "water"] else p.get(stat_key, 0)
                    stats_data.append({"Game": game_label, "Player": name, "Value": value})

        if stats_data:
            df = pd.DataFrame(stats_data)
            fig = px.bar(df, x="Player", y="Value", color="Game", barmode="group", title=f"{selected_stat} per Player")
            st.plotly_chart(fig)
            if st.button("Download All Stats as CSV"):
                Download_Game_Stats(days)

def Download_Game_Stats(days):
    try:
        all_game_data = []

        with st.spinner("Henter game data..."):
            games_in_memory = sorted(get_cached_games(days), key=lambda game: game["game_finished_at"], reverse=True)

            for game in games_in_memory:
                game_id = game["game_id"]
                map_name = game["map_name"]
                game_details = fetch_game_details(game_id)
                konsum_data = get_cached_konsum(game_id)  # Fetch beer & water data

                for player in game_details.get("playerStats", []):
                    raw_name = player["name"]
                    mapped_name = NAME_MAPPING.get(raw_name, raw_name)
                    
                    if mapped_name in ALLOWED_PLAYERS:
                        player_data = {
                            "Game": map_name,
                            "Player": mapped_name,
                            "Date": game["game_finished_at"].strftime("%Y-%m-%d %H:%M"),
                        }

                        # Add all game stats
                        for display_name, stat_key in stat_display_mapping.items():
                            player_data[display_name] = get_player_stat(player, stat_key)

                        # Add Beer & Water
                        player_data["Beer"] = konsum_data.get(mapped_name, {}).get("beer", 0)
                        player_data["Water"] = konsum_data.get(mapped_name, {}).get("water", 0)

                        all_game_data.append(player_data)

        if all_game_data:
            df_full = pd.DataFrame(all_game_data)
            csv_buffer = StringIO()
            df_full.to_csv(csv_buffer, index=False)
            csv_data = csv_buffer.getvalue()

            st.download_button(
                label="Klikk her for å laste ned CSV fil",
                data=csv_data,
                file_name="all_game_stats.csv",
                mime="text/csv"
            )
    except Exception as e:
        st.error(f"Error downloading stats: {e}")

# Motivation Page
def motivation_page():
    st.header("Get skibid going!")
    st.markdown("""
        <iframe width="560" height="315" src="https://www.youtube.com/embed/6dMjCa0nqK0" 
        frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
        allowfullscreen></iframe>
    """, unsafe_allow_html=True)

# Main UI
st.image("bubblogo2.png", width=80)
st.markdown("<h1 style='text-align: center;'>Bubberne Gaming</h1>", unsafe_allow_html=True)

nav = st.columns(4)
with nav[0]:
    if st.button("🏠 Home", use_container_width=True):
        st.session_state.page = "home"
with nav[1]:
    if st.button("📝 Input", use_container_width=True):
        st.session_state.page = "input"
with nav[2]:
    if st.button("📊 Stats", use_container_width=True):
        st.session_state.page = "stats"
with nav[3]:
    if st.button("🚽 Motivation", use_container_width=True):
        st.session_state.page = "motivation"

if "page" not in st.session_state:
    st.session_state.page = "home"

if st.session_state.page == "home":
    home_page()
elif st.session_state.page == "input":
    input_data_page()
elif st.session_state.page == "stats":
    stats_page()
elif st.session_state.page == "motivation":
    motivation_page()
