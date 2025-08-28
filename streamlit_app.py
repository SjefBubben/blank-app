import streamlit as st
import requests
import base64
import json
import pandas as pd
import plotly.express as px
import threading
from operator import itemgetter
from datetime import datetime, timedelta
from io import StringIO
from DataInput import fetch_all_sheets_data, fetch_games_within_last_48_hours, fetch_konsum_data_for_game, save_konsum_data, save_game_data
# API Endpoints
PROFILE_API = "https://api.cs-prod.leetify.com/api/profile/id/"
GAMES_API = "https://api.cs-prod.leetify.com/api/games/"
leetify_token = st.secrets["leetify"]["api_token"]

# List of SteamIDs to fetch games from
#STEAM_IDS = ["76561197983741618", "76561198048455133", "76561198021131347"]

# Player Name Mapping (unchanged)
NAME_MAPPING = {
    "JimmyJimbob": "Jeprizz", "Jimmy": "Jeprizz", "Kåre": "Torgrizz", "Kaare": "Torgrizz",
    "Fakeface": "Birkle", "Killthem26": "Birkle", "Lars Olaf": "Tobrizz", "tobbelobben": "Tobrizz",
    "Bøghild": "Borgle", "Nish": "Sandrizz", "Nishinosan": "Sandrizz", "Zohan": "Jorizz", "johlyn": "Jorizz"
}
ALLOWED_PLAYERS = set(NAME_MAPPING.values())

# Initialize session state with all Sheets data
def initialize_session_state():
    if 'initialized' not in st.session_state:
        st.session_state['initialized'] = True
        # Fetch all Sheets data once
        games_df, konsum_df = fetch_all_sheets_data()
        st.session_state['games_df'] = games_df
        st.session_state['konsum_df'] = konsum_df
        st.session_state['cached_games'] = fetch_games_within_last_48_hours()
        st.session_state['cached_konsum'] = {}
        for game in st.session_state['cached_games']:
            st.session_state['cached_konsum'][game['game_id']] = fetch_konsum_data_for_game(game['game_id'])

# Manual refresh button functionality
def refresh_all(days):
    # Clear cached data and refetch from Sheets
    games_df, konsum_df = fetch_all_sheets_data()
    st.session_state['games_df'] = games_df
    st.session_state['konsum_df'] = konsum_df
    st.session_state['cached_games'] = fetch_games_within_last_48_hours()
    st.session_state['cached_konsum'] = {}
    for game in st.session_state['cached_games']:
        st.session_state['cached_konsum'][game['game_id']] = fetch_konsum_data_for_game(game['game_id'])
    # Fetch new games from Leetify API
    new_games = fetch_new_games(days)
    print(len(new_games))
    st.session_state['cached_games'] = fetch_games_within_last_48_hours()
    

# Remove caching decorators since we use session state
def get_cached_games(days):
    return fetch_games_within_last_48_hours(days)

def get_cached_konsum(game_id):
    return fetch_konsum_data_for_game(game_id) or {}

# Data Fetching Functions

def fetch_profile(token, start_date, end_date, count=30):
    print("📡 fetch_profile() called!")
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
        data = response.json()
        
        return data
    except requests.RequestException as e:
        print(f"Failed fetching profile: {e}")
        return None

def fetch_game_details(game_id):
    try:
        response = requests.get(GAMES_API + game_id, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None

def fetch_new_games(days, token=leetify_token):
    new_games = []
    now = datetime.utcnow()
    start_date = now - timedelta(days=days)

    profile_data = fetch_profile(token, start_date, now)
    


    if not profile_data or "games" not in profile_data:
        st.warning("No games found or invalid response")
        return []

    existing_game_ids = set(st.session_state['games_df']['game_id']) if not st.session_state['games_df'].empty else set()

    for game in profile_data.get("games", []):
        game_id = game.get("id")
        if not game_id or game_id in existing_game_ids or game_id in {g["game_id"] for g in new_games}:
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
        except (ValueError, KeyError) as e:
            st.error(f"Skipping game {game_id} due to error: {e}")
            continue

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

    return new_games

def async_save(game_id, name, beer_val, water_val):
    # Run the actual save in a background thread
    def _save():
        save_konsum_data(game_id, name, beer_val, water_val)
        st.session_state[game_id][name] = {"beer": beer_val, "water": water_val}
    threading.Thread(target=_save, daemon=True).start()

def get_player_stat(player, stat_key):
    return player.get(stat_key, 0)

# Home Page 
def home_page(days):
    
    games = get_cached_games(days)
    if not games:
        st.warning("No games found across all profiles.")
        return

    games = sorted(games, key=lambda x: x.get("game_finished_at", datetime.min), reverse=True)

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

                worst_util = max(p.get("utilityOnDeathAvg", 0) for p in players)
                best_hltv = max(p.get("hltvRating", 0) for p in players)

                worst_util_players = [p for p in players if p.get("utilityOnDeathAvg",0) == worst_util]
                best_hltv_players = [p for p in players if p.get("hltvRating",0) == best_hltv]

                # Add spacing between columns using st.columns with gap
                col1, col2 = st.columns([1, 1], gap="small")
                col3, col4 = st.columns([1, 1], gap="small")

                with col1:
                    st.markdown(f"""
                        <div style="padding: 15px; background-color: #388E3C; color: white; border-radius: 10px; text-align: center; border: 1px solid black; margin: 5px;">
                            <h3>🔥 Reaction Time</h3>
                            <h4>💪 Gooner: {', '.join(p['name'] for p in top_players)} ({min_rt}s)</h4>
                            <h4>🍺 Pils-bitch: {', '.join(p['name'] for p in low_players)} ({max_rt}s)</h4>
                        </div>
                    """, unsafe_allow_html=True)

                with col2:
                    st.markdown(f"""
                        <div style="padding: 15px; background-color: #1976D2; color: white; border-radius: 10px; text-align: center; border: 1px solid black; margin: 5px;">
                            <h3>🎯 Trade Kill Attempts</h3>
                            <h4>✅ Rizzler: {', '.join(p['name'] for p in best_trade_players)} ({best_trade:.1f}%)</h4>
                            <h4>❌ Baiterbot: {', '.join(p['name'] for p in worst_trade_players)} ({worst_trade:.1f}%)</h4>
                        </div>
                    """, unsafe_allow_html=True)

                with col3:
                    st.markdown(f"""
                        <div style="padding: 15px; background-color: #D32F2F; color: white; border-radius: 10px; text-align: center; border: 1px solid black; margin: 5px;">
                            <h3>💣 Utility on Death</h3>
                            <h4>🔥 McRizzler: {', '.join(p['name'] for p in worst_util_players)} ({worst_util:.2f})</h4>
                        </div>
                    """, unsafe_allow_html=True)

                with col4:
                    st.markdown(f"""
                        <div style="padding: 15px; background-color: #301934; color: white; border-radius: 10px; text-align: center; border: 1px solid black; margin: 5px;">
                            <h3>🏆 Best HLTV Rating</h3>
                            <h4>⭐ OhioMaster: {', '.join(p['name'] for p in best_hltv_players)} ({best_hltv:.2f})</h4>
                        </div>
                    """, unsafe_allow_html=True)

    st.write(f"Total games: {len(games)}")

# Input Data Page
def input_data_page(days):
    st.header("Input BubbeData")

    games = sorted(get_cached_games(days), key=lambda x: x.get("game_finished_at", datetime.min), reverse=True)

    if not games:
        st.warning("No games found in the selected timeframe.")
        return

    # Fetch all details once + gather unique players
    game_details_map = {}
    all_players = set()

    for game in games:
        details = fetch_game_details(game.get("game_id"))
        if not details:
            continue
        game_details_map[game["game_id"]] = details

        for p in details.get("playerStats", []):
            name = NAME_MAPPING.get(p["name"], p["name"])
            if name in ALLOWED_PLAYERS:
                all_players.add(name)

    # Player filter
    selected_players = st.multiselect(
        "Spiller filtrering",
        options=sorted(all_players),
        default=[],
        help="Velg gooners du vil rizze."
    )

    for game in games:
        details = game_details_map.get(game["game_id"])
        if not details:
            st.write(f"Skipping game {game.get('game_id', 'unknown')} - no details available.")
            continue

        map_name = game.get("map_name", "Unknown")
        match_result = game.get("match_result", "Unknown")
        scores = [game["score_team1"], game["score_team2"]]
        game_finished_at = game.get("game_finished_at")

        if isinstance(game_finished_at, str):
            try:
                game_finished_at = datetime.strptime(game_finished_at, "%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                game_finished_at = datetime.now()
        elif not isinstance(game_finished_at, datetime):
            game_finished_at = datetime.now()

        label = f"{map_name} - {match_result} ({scores[0]}:{scores[1]}) - {game_finished_at.strftime('%d.%m.%y %H:%M')}"
        with st.expander(label):
            konsum = st.session_state.get(game["game_id"], fetch_konsum_data_for_game(game["game_id"]) or {})
            st.session_state[game["game_id"]] = konsum

            for p in details.get("playerStats", []):
                name = NAME_MAPPING.get(p["name"], p["name"])
                if name in ALLOWED_PLAYERS:
                    if selected_players and name not in selected_players:
                        continue

                    st.markdown(f"**{name}** - K/D: {p['kdRatio']}, ADR: {p['dpr']}, HLTV: {p['hltvRating']}")

                    prev_beer = konsum.get(name, {}).get("beer", 0)
                    prev_water = konsum.get(name, {}).get("water", 0)

                    # Keys
                    beer_key = f"beer_input-{name}-{game['game_id']}"
                    water_key = f"water_input-{name}-{game['game_id']}"
                    save_key = f"save_button-{name}-{game['game_id']}"

                    # Initialize session state if not present
                    if beer_key not in st.session_state:
                        st.session_state[beer_key] = str(prev_beer)
                    if water_key not in st.session_state:
                        st.session_state[water_key] = str(prev_water)

                    # Use a form to group inputs and button
                    with st.form(key=f"form-{name}-{game['game_id']}"):
                        col1, col2 = st.columns(2)
                        beer = col1.text_input("Beers", st.session_state[beer_key], key=beer_key)
                        water = col2.text_input("Water", st.session_state[water_key], key=water_key)

                        submitted = st.form_submit_button("Save")
                        if submitted:
                            try:
                                beer_val = int(beer)
                                water_val = int(water)
                                async_save(game["game_id"], name, beer_val, water_val)
                                st.success(f"💾 Saving {name}: {beer_val} beer(s), {water_val} water(s)")
                            except ValueError:
                                st.error("❌ Please enter valid numbers for beer and water.")

# Stats Page
STAT_MAP = {
    "K/D Ratio": "kdRatio", "ADR": "dpr", "HLTV Rating": "hltvRating", "Reaction Time": "reactionTime", "TradeAttempts": "tradeKillAttemptsPercentage",
    "Enemies Flashed": "flashbangThrown", "2k Kills": "multi2k", "3k Kills": "multi3k"
}

def load_all_stats(days):
    games = sorted(get_cached_games(days), key=lambda x: x["game_finished_at"])
    if not games:
        return None, None

    rows = []
    for g in games:
        details = fetch_game_details(g["game_id"]) or {}
        konsum = get_cached_konsum(g["game_id"]) or {}
        game_label = f"{g['map_name']} ({g['game_finished_at'].strftime('%d.%m.%y %H:%M')})"

        for p in details.get("playerStats", []):
            name = NAME_MAPPING.get(p["name"], p["name"])
            if name not in ALLOWED_PLAYERS:
                continue

            row = {
                "Game": game_label,
                "Player": name,
                "Beer": konsum.get(name, {}).get("beer", 0),
                "Water": konsum.get(name, {}).get("water", 0),
            }
            # Add all stats in STAT_MAP
            for display_name, stat_key in STAT_MAP.items():
                val = p.get(stat_key, 0)
                # tradeKillAttemptsPercentage needs scaling
                if stat_key == "tradeKillAttemptsPercentage":
                    val = val * 100
                row[display_name] = val
            rows.append(row)

    df = pd.DataFrame(rows)

    # --- Compute per-player averages ---
    grouped = df.groupby("Player").mean(numeric_only=True).reset_index()

    # --- BubbeRating ---
    trade_weight = 0.5
    beer_weight = 0.9
    games_played = df["Game"].nunique()

    grouped["BubbeRating"] = (
        grouped["HLTV Rating"] +
        grouped["HLTV Rating"] * ((grouped["Beer"] / games_played) * beer_weight) +
        (grouped["TradeAttempts"] / 100) * trade_weight
    ).round(2)

    return df, grouped

def stats_page(days):
    st.header("Stats")

    with st.spinner("Loading stats..."):
        df, grouped = load_all_stats(days)
        if df is None or df.empty:
            st.warning("No games found in the selected timeframe.")
            return

        # --- Build Top 3 Table (static, shown first) ---
        stat_options = list(STAT_MAP.keys()) + ["Beer", "Water", "BubbeRating"]

        def top3(col, ascending=False, fmt=".2f"):
            if col == "Reaction Time":  # smaller is better
                ascending = True
            top = grouped.sort_values(col, ascending=ascending).head(3)
            formatted = [f"{row.Player} ({row[col]:{fmt}})" for _, row in top.iterrows()]
            while len(formatted) < 3:
                formatted.append("-")
            return formatted

        table_data = {
            "HLTV Rating": top3("HLTV Rating", False, ".2f"),
            "K/D Ratio": top3("K/D Ratio", False, ".2f"),
            "Reaction Time": top3("Reaction Time", True, ".2f"),
            "Trade (%)": top3("TradeAttempts", False, ".1f"),
            "Beer": top3("Beer", False, ".0f"),
            "Water": top3("Water", False, ".0f"),
            "BubbeRating": top3("BubbeRating", False, ".2f"),
        }

        df_table = pd.DataFrame(table_data, index=["1", "2", "3"])
        st.markdown("### Best Average Stats Across Games")
        st.dataframe(df_table, use_container_width=True)

    # --- Stat picker + graph (below table) ---
    stat_options = list(STAT_MAP.keys()) + ["Beer", "Water", "BubbeRating"]
    selected_stat = st.selectbox("Stat to plot", stat_options)

    if selected_stat == "BubbeRating":
        fig = px.bar(grouped, x="Player", y="BubbeRating",
                     title="BubbeRating per Player")
    else:
        fig = px.bar(df, x="Player", y=selected_stat, color="Game",
                     barmode="group", title=f"{selected_stat} per Player")

    st.plotly_chart(fig, use_container_width=True)

    # --- Download CSV of all raw stats ---
    csv = df.to_csv(index=False)
    st.download_button(
        "Download All Stats as CSV",
        data=csv,
        file_name="all_game_stats.csv",
        mime="text/csv"
    )

def Download_Game_Stats(days, game_details_map, konsum_map):
    try:
        all_game_data = []
        with st.spinner("Henter game data..."):
            games_in_memory = sorted(get_cached_games(days), key=lambda g: g["game_finished_at"], reverse=True)

            for game in games_in_memory:
                game_id = game["game_id"]
                map_name = game["map_name"]
                game_details = game_details_map.get(game_id, {})
                konsum_data = konsum_map.get(game_id, {})

                for player in game_details.get("playerStats", []):
                    raw_name = player["name"]
                    mapped_name = NAME_MAPPING.get(raw_name, raw_name)
                    
                    if mapped_name in ALLOWED_PLAYERS:
                        player_data = {
                            "Game": map_name,
                            "Player": mapped_name,
                            "Date": game["game_finished_at"].strftime("%Y-%m-%d %H:%M"),
                        }

                        for display_name, stat_key in STAT_MAP.items():
                            player_data[display_name] = get_player_stat(player, stat_key)

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
            st.download_button(
                "Download All Stats as CSV",
                data=df.to_csv(index=False),
                file_name="all_game_stats.csv",
                mime="text/csv"
            )

            # New button for full sheet export
            download_full_database()
    except Exception as e:
        st.error(f"Error downloading stats: {e}")

def download_full_database():
    try:
        all_game_data = []

        with st.spinner("Fetching ALL games from database..."):
            # 👇 replace this with however you actually load game_ids from your Google Sheet
            all_games = fetch_all_sheets_data()  # returns [{game_id, map_name, game_finished_at}, ...]

            for game in sorted(all_games, key=lambda g: g["game_finished_at"], reverse=True):
                game_id = game["game_id"]
                map_name = game["map_name"]
                game_details = fetch_game_details(game_id) or {}
                konsum_data = get_cached_konsum(game_id) or {}

                for player in game_details.get("playerStats", []):
                    raw_name = player["name"]
                    mapped_name = NAME_MAPPING.get(raw_name, raw_name)
                    if mapped_name not in ALLOWED_PLAYERS:
                        continue

                    player_data = {
                        "Game": map_name,
                        "Player": mapped_name,
                        "Date": game["game_finished_at"].strftime("%Y-%m-%d %H:%M"),
                    }

                    # Add stats from STAT_MAP
                    for display_name, stat_key in STAT_MAP.items():
                        val = player.get(stat_key, 0)
                        if stat_key == "tradeKillAttemptsPercentage":
                            val = val * 100
                        player_data[display_name] = val

                    # Beer & Water
                    player_data["Beer"] = konsum_data.get(mapped_name, {}).get("beer", 0)
                    player_data["Water"] = konsum_data.get(mapped_name, {}).get("water", 0)

                    all_game_data.append(player_data)

        if all_game_data:
            df_full = pd.DataFrame(all_game_data)

            # optional: also compute BubbeRating per game, not just averages
            trade_weight = 0.5
            beer_weight = 0.9
            df_full["BubbeRating"] = (
                df_full["HLTV Rating"]
                + df_full["HLTV Rating"] * (df_full["Beer"] * beer_weight)
                + (df_full["TradeAttempts"] / 100) * trade_weight
            ).round(2)

            csv_buffer = StringIO()
            df_full.to_csv(csv_buffer, index=False)
            csv_data = csv_buffer.getvalue()

            st.download_button(
                label="Download Entire Database (CSV)",
                data=csv_data,
                file_name="all_game_stats_full.csv",
                mime="text/csv"
            )
        else:
            st.warning("No game data found in the sheet.")

    except Exception as e:
        st.error(f"Error downloading full database: {e}")

# Motivation Page
def motivation_page():
    st.header("Get skibid going!")
    st.markdown("""
        <iframe width="560" height="315" src="https://www.youtube.com/embed/6dMjCa0nqK0" 
        frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
        allowfullscreen></iframe>
    """, unsafe_allow_html=True)

# Main UI
def img_to_base64(img_path):
    with open(img_path, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode()

img_base64 = img_to_base64("bubblogo2.png")

html_code = f"""
<div style="
    display: flex;
    align-items: center;
    justify-content: center;
    height: 150px;  
    text-align: center;
">
    <img src="data:image/png;base64,{img_base64}" width="80" style="margin-right: 10px;">
    <h1 style="margin: 0;">Bubberne Gaming</h1>
</div>
"""
st.markdown(html_code, unsafe_allow_html=True)

#Start caching
initialize_session_state()

st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ("🏠 Home", "📝 Input", "📊 Stats", "🚽 Motivation"))

#Refresh og datepicker
if "days_value" not in st.session_state:
    st.session_state["days_value"] = 2

col1, col2 = st.columns([1, 1])

with col1:
    # Temporary input, does NOT cause refresh yet
    temp_days = st.number_input("Dager tilbake", min_value=1, max_value=15, value=st.session_state["days_value"], key="temp_days_input")

with col2:
    st.markdown("<br>", unsafe_allow_html=True)  # align button with label
    if st.button("🔄 Refresh Data"):
        # When clicked, save the temp value to session_state and refresh
        st.session_state["days_value"] = temp_days
        refresh_all(st.session_state["days_value"])
        

# Now use st.session_state["days_value"] in your app logic
days = st.session_state["days_value"]


if page == "🏠 Home":
    home_page(days)
elif page == "📝 Input":
    input_data_page(days)
elif page == "📊 Stats":
    stats_page(days)
elif page == "🚽 Motivation":
    motivation_page()