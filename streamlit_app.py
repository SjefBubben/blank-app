import streamlit as st
import requests
import base64
import json
import pandas as pd
import plotly.express as px
from operator import itemgetter
from datetime import datetime, timedelta
from io import StringIO
from DataInput import fetch_all_sheets_data, fetch_games_within_last_48_hours, fetch_konsum_data_for_game, save_konsum_data, save_game_data
from tenacity import retry, stop_after_attempt, wait_fixed

# API Endpoints
PROFILE_API = "https://api.cs-prod.leetify.com/api/profile/id/"
GAMES_API = "https://api.cs-prod.leetify.com/api/games/"
leetify_token = st.secrets["leetify"]["api_token"]

# Player Name Mapping
NAME_MAPPING = {
    "JimmyJimbob": "Jeprizz", "Jimmy": "Jeprizz", "Kåre": "Torgrizz", "Kaare": "Torgrizz",
    "Fakeface": "Birkle", "Killthem26": "Birkle", "Lars Olaf": "Tobrizz", "tobbelobben": "Tobrizz",
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
        st.session_state['game_details_cache'] = {}  # Cache for game details
        st.session_state['cached_konsum'] = {}

# Manual refresh button functionality
def refresh_all(days):
    games_df, konsum_df = fetch_all_sheets_data()
    st.session_state['games_df'] = games_df
    st.session_state['konsum_df'] = konsum_df
    st.session_state['cached_games'] = fetch_games_within_last_48_hours()
    st.session_state['game_details_cache'].clear()
    st.session_state['cached_konsum'].clear()
    new_games = fetch_new_games(days)
    st.session_state['cached_games'] = fetch_games_within_last_48_hours()
    st.success(f"Data refreshed! Found {len(new_games)} new games.")

# Data Fetching Functions
@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
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
    response = requests.get(url, headers=headers, params={"filters": json.dumps(filters)})
    response.raise_for_status()
    return response.json()

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def fetch_game_details(game_id):
    if game_id in st.session_state['game_details_cache']:
        return st.session_state['game_details_cache'][game_id]
    response = requests.get(GAMES_API + game_id, timeout=10)
    response.raise_for_status()
    data = response.json()
    st.session_state['game_details_cache'][game_id] = data
    return data

def fetch_new_games(days, token=leetify_token):
    if days < 1 or days > 15:
        st.error("Days must be between 1 and 15.")
        return []
    
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
                    "score_team1": score[0],
                    "score_team2": score[1],
                    "game_finished_at": finished_at_str
                }

                new_games.append(new_game)
                save_game_data(
                    game_id, new_game["map_name"], match_result,
                    score[0], score[1], finished_at_str
                )
        except (ValueError, KeyError) as e:
            st.error(f"Skipping game {game_id} due to error: {e}")
            continue

    return new_games

def get_player_stat(player, stat_key):
    return player.get(stat_key, 0)

# Home Page 
def home_page(days):
    games = fetch_games_within_last_48_hours(days)
    if not games:
        st.warning("No games found.")
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
                {
                    "name": NAME_MAPPING.get(p["name"], p["name"]),
                    "reactionTime": get_player_stat(p, "reactionTime"),
                    "tradeKillAttemptsPercentage": get_player_stat(p, "tradeKillAttemptsPercentage"),
                    "utilityOnDeathAvg": get_player_stat(p, "utilityOnDeathAvg"),
                    "hltvRating": get_player_stat(p, "hltvRating")
                }
                for p in details.get("playerStats", []) if NAME_MAPPING.get(p["name"], p["name"]) in ALLOWED_PLAYERS
            ]
            if players:
                players.sort(key=itemgetter("reactionTime"))
                min_rt = min(p["reactionTime"] for p in players)
                max_rt = max(p["reactionTime"] for p in players)
                best_trade = max(p["tradeKillAttemptsPercentage"] * 100 for p in players)
                worst_trade = min(p["tradeKillAttemptsPercentage"] * 100 for p in players)
                worst_util = max(p.get("utilityOnDeathAvg", 0) for p in players)
                best_hltv = max(p.get("hltvRating", 0) for p in players)

                col1, col2 = st.columns([1, 1], gap="small")
                col3, col4 = st.columns([1, 1], gap="small")

                with col1:
                    st.markdown(f"""
                        <div style="padding: 15px; background-color: #388E3C; color: white; border-radius: 10px; text-align: center; border: 1px solid black; margin: 5px;">
                            <h3>🔥 Reaction Time</h3>
                            <h4>💪 Gooner: {', '.join(p['name'] for p in players if p['reactionTime'] == min_rt)} ({min_rt}s)</h4>
                            <h4>🍺 Pils-bitch: {', '.join(p['name'] for p in players if p['reactionTime'] == max_rt)} ({max_rt}s)</h4>
                        </div>
                    """, unsafe_allow_html=True)

                with col2:
                    st.markdown(f"""
                        <div style="padding: 15px; background-color: #1976D2; color: white; border-radius: 10px; text-align: center; border: 1px solid black; margin: 5px;">
                            <h3>🎯 Trade Kill Attempts</h3>
                            <h4>✅ Rizzler: {', '.join(p['name'] for p in players if p['tradeKillAttemptsPercentage'] * 100 == best_trade)} ({best_trade:.1f}%)</h4>
                            <h4>❌ Baiterbot: {', '.join(p['name'] for p in players if p['tradeKillAttemptsPercentage'] * 100 == worst_trade)} ({worst_trade:.1f}%)</h4>
                        </div>
                    """, unsafe_allow_html=True)

                with col3:
                    st.markdown(f"""
                        <div style="padding: 15px; background-color: #D32F2F; color: white; border-radius: 10px; text-align: center; border: 1px solid black; margin: 5px;">
                            <h3>💣 Utility on Death</h3>
                            <h4>🔥 McRizzler: {', '.join(p['name'] for p in players if p['utilityOnDeathAvg'] == worst_util)} ({worst_util:.2f})</h4>
                        </div>
                    """, unsafe_allow_html=True)

                with col4:
                    st.markdown(f"""
                        <div style="padding: 15px; background-color: #388E3C; color: white; border-radius: 10px; text-align: center; border: 1px solid black; margin: 5px;">
                            <h3>🏆 Best HLTV Rating</h3>
                            <h4>⭐ OhioMaster: {', '.join(p['name'] for p in players if p['hltvRating'] == best_hltv)} ({best_hltv:.2f})</h4>
                        </div>
                    """, unsafe_allow_html=True)

    st.write(f"Total games: {len(games)}")

# Input Data Page
def input_data_page(days):
    st.header("Input BubbeData")
    games = sorted(fetch_games_within_last_48_hours(days), key=lambda x: x.get("game_finished_at", datetime.min), reverse=True)
    if not games:
        st.warning("No games found.")
        return

    for game in games:
        details = fetch_game_details(game["game_id"])
        if not details:
            st.write(f"Skipping game {game.get('game_id', 'unknown')} - no details available.")
            continue

        map_name = game.get("map_name", "Unknown")
        match_result = game.get("match_result", "Unknown")
        scores = [game["score_team1"], game["score_team2"]]
        game_finished_at = pd.to_datetime(game.get("game_finished_at"), errors='coerce') or datetime.now()

        label = f"{map_name} - {match_result} ({scores[0]}:{scores[1]}) - {game_finished_at.strftime('%d.%m.%y %H:%M')}"
        with st.expander(label):
            konsum = st.session_state['cached_konsum'].get(game["game_id"], fetch_konsum_data_for_game(game["game_id"]))
            st.session_state['cached_konsum'][game["game_id"]] = konsum

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
                        st.session_state['cached_konsum'][game["game_id"]][name] = {"beer": beer, "water": water}
                        st.success(f"Updated {name}: {beer} beers, {water} water")

# Stats Page
STAT_MAP = {
    "K/D Ratio": "kdRatio", "ADR": "dpr", "HLTV Rating": "hltvRating", "Reaction Time": "reactionTime",
    "Enemies Flashed": "flashbangThrown", "2k Kills": "multi2k", "3k Kills": "multi3k"
}

def stats_page(days):
    st.header("Stats")
    stat_options = list(STAT_MAP.keys()) + ["Beer", "Water"]
    selected_stat = st.selectbox("Stat to plot", stat_options)
    stat_key = STAT_MAP.get(selected_stat, selected_stat.lower())

    with st.spinner("Loading stats..."):
        games = sorted(fetch_games_within_last_48_hours(days), key=lambda x: x["game_finished_at"])
        if not games:
            st.warning("No games found.")
            return

        stats_data = []
        player_stats = {name: {'kd': [], 'rt': [], 'trade': []} for name in ALLOWED_PLAYERS}

        for game in games:
            details = fetch_game_details(game["game_id"])
            konsum = fetch_konsum_data_for_game(game["game_id"])
            game_label = f"{game['map_name']} ({game['game_finished_at'].strftime('%d.%m.%y %H:%M')})"

            for p in details.get("playerStats", []):
                name = NAME_MAPPING.get(p["name"], p["name"])
                if name in ALLOWED_PLAYERS:
                    value = konsum.get(name, {}).get(stat_key, 0) if stat_key in ["beer", "water"] else get_player_stat(p, stat_key)
                    stats_data.append({"Game": game_label, "Player": name, "Value": value})
                    player_stats[name]['kd'].append(get_player_stat(p, "kdRatio"))
                    player_stats[name]['rt'].append(get_player_stat(p, "reactionTime"))
                    player_stats[name]['trade'].append(get_player_stat(p, "tradeKillAttemptsPercentage") * 100)

        avg_stats = {}
        for name in player_stats:
            kd_list = [x for x in player_stats[name]['kd'] if x > 0]
            rt_list = [x for x in player_stats[name]['rt'] if x > 0]
            trade_list = [x for x in player_stats[name]['trade'] if x > 0]
            avg_stats[name] = {
                'kd': sum(kd_list) / len(kd_list) if kd_list else 0,
                'rt': sum(rt_list) / len(rt_list) if rt_list else float('inf'),
                'trade': sum(trade_list) / len(trade_list) if trade_list else 0
            }

        best_kd = max((name, stats['kd']) for name, stats in avg_stats.items() if stats['kd'] > 0)
        best_rt = min((name, stats['rt']) for name, stats in avg_stats.items() if stats['rt'] < float('inf'))
        best_trade = max((name, stats['trade']) for name, stats in avg_stats.items() if stats['trade'] > 0)

        st.markdown(f"""
            <div style="padding: 10px; border: 1px solid #f0f0f0; border-radius: 5px; margin-bottom: 10px;">
                <h4>Best Average Stats Across Games</h4>
                <p>Best avg KD: {best_kd[0]} ({best_kd[1]:.2f})</p>
                <p>Best avg Reaction Time: {best_rt[0]} ({best_rt[1]:.2f}s)</p>
                <p>Best avg Trade Attempts: {best_trade[0]} ({best_trade[1]:.1f}%)</p>
            </div>
        """, unsafe_allow_html=True)

        if stats_data:
            df = pd.DataFrame(stats_data)
            fig = px.bar(df, x="Player", y="Value", color="Game", barmode="group", title=f"{selected_stat} per Player")
            st.plotly_chart(fig)
            if st.button("Download All Stats as CSV"):
                Download_Game_Stats(days)

def Download_Game_Stats(days):
    try:
        all_game_data = []
        games = sorted(fetch_games_within_last_48_hours(days), key=lambda game: game["game_finished_at"], reverse=True)

        for game in games:
            game_id = game["game_id"]
            map_name = game["map_name"]
            game_details = fetch_game_details(game_id)
            konsum_data = fetch_konsum_data_for_game(game_id)

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
            csv_data = df_full.to_csv(index=False)
            st.download_button(
                label="Download CSV",
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
def img_to_base64(img_path):
    with open(img_path, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode()

img_base64 = img_to_base64("bubblogo2.png")
html_code = f"""
<div style="display: flex; align-items: center; justify-content: center; height: 150px; text-align: center;">
    <img src="data:image/png;base64,{img_base64}" width="80" style="margin-right: 10px;">
    <h1 style="margin: 0;">Bubberne Gaming</h1>
</div>
"""

st.markdown(html_code, unsafe_allow_html=True)
initialize_session_state()
st.sidebar.title("Navigation")
days = st.sidebar.number_input("Days back", min_value=1, max_value=15, value=2)
page = st.sidebar.radio("Go to", ("🏠 Home", "📝 Input", "📊 Stats", "🚽 Motivation"))

if st.button("🔄 Refresh Data"):
    refresh_all(days)

if page == "🏠 Home":
    home_page(days)
elif page == "📝 Input":
    input_data_page(days)
elif page == "📊 Stats":
    stats_page(days)
elif page == "🚽 Motivation":
    motivation_page()