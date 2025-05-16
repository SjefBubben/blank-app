import streamlit as st
import requests
import base64
import pandas as pd
import plotly.express as px
from operator import itemgetter
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from io import StringIO
from dateutil.parser import parse
import logging
import os
from DataInput import fetch_all_sheets_data, fetch_games_within_last_48_hours, fetch_konsum_data_for_game, save_konsum_data, save_game_data

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Constants
GAME_ID_KEY = "game_id"
MAP_NAME_KEY = "map_name"
GAME_FINISHED_AT_KEY = "game_finished_at"
SCORES_KEY = "scores"
MATCH_RESULT_KEY = "match_result"

# API Endpoints (configurable via environment variables)
PROFILE_API = os.getenv("LEETIFY_PROFILE_API", "https://api.cs-prod.leetify.com/api/profile/id/")
GAMES_API = os.getenv("LEETIFY_GAMES_API", "https://api.cs-prod.leetify.com/api/games/")

# List of SteamIDs to fetch games from
STEAM_IDS = ["76561197983741618", "76561198048455133", "76561198021131347"]

# Player Name Mapping
NAME_MAPPING = {
    "JimmyJimbob": "Jeprizz", "Jimmy": "Jeprizz", "Kåre": "Torgrizz", "Kaare": "Torgrizz",
    "Fakeface": "Birkle", "Killthem26": "Birkle", "Lars Olaf": "Tobrizz", "tobbelobben": "Tobrizz",
    "Bøghild": "Borgle", "Nish": "Sandrizz", "Nishinosan": "Sandrizz", "Zohan": "Jorizz", "johlyn": "Jorizz"
}
ALLOWED_PLAYERS = set(NAME_MAPPING.values())

def initialize_session_state() -> None:
    """Initialize Streamlit session state with cached data."""
    if 'initialized' not in st.session_state:
        st.session_state['initialized'] = True
        st.session_state['games_df'] = None
        st.session_state['konsum_df'] = None
        st.session_state['cached_games'] = []
        st.session_state['cached_konsum'] = {}
        # Load Sheets data
        games_df, konsum_df = fetch_all_sheets_data()
        st.session_state['games_df'] = games_df
        st.session_state['konsum_df'] = konsum_df
        st.session_state['cached_games'] = fetch_games_within_last_48_hours()
        for game in st.session_state['cached_games']:
            st.session_state['cached_konsum'][game[GAME_ID_KEY]] = fetch_konsum_data_for_game(game[GAME_ID_KEY])

def refresh_all() -> None:
    """Refresh all cached data from Sheets and Leetify API."""
    games_df, konsum_df = fetch_all_sheets_data()
    st.session_state['games_df'] = games_df
    st.session_state['konsum_df'] = konsum_df
    st.session_state['cached_games'] = fetch_games_within_last_48_hours()
    st.session_state['cached_konsum'] = {}
    for game in st.session_state['cached_games']:
        st.session_state['cached_konsum'][game[GAME_ID_KEY]] = fetch_konsum_data_for_game(game[GAME_ID_KEY])
    fetch_new_games(days=2)
    st.session_state['cached_games'] = fetch_games_within_last_48_hours()
    st.success("Data refreshed!")

def get_cached_games(days: int = 2) -> List[Dict]:
    """Retrieve cached games within the specified timeframe."""
    return fetch_games_within_last_48_hours(days)

def get_cached_konsum(game_id: str) -> Dict:
    """Retrieve cached konsum data for a specific game."""
    return st.session_state['cached_konsum'].get(game_id, fetch_konsum_data_for_game(game_id) or {})

def fetch_profile(steam_id: str) -> Optional[Dict]:
    """Fetch player profile from Leetify API."""
    try:
        response = requests.get(PROFILE_API + steam_id, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Failed to fetch profile for Steam ID {steam_id}: {e}")
        return None

def fetch_game_details(game_id: str) -> Optional[Dict]:
    """Fetch game details from Leetify API."""
    try:
        response = requests.get(GAMES_API + game_id, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Failed to fetch game details for game {game_id}: {e}")
        return None

def parse_game_data(game: Dict) -> Optional[Dict]:
    """Parse raw game data from Leetify API."""
    try:
        finished_at = parse(game.get("gameFinishedAt", ""))
        return {
            GAME_ID_KEY: game.get("gameId"),
            MAP_NAME_KEY: game.get("mapName", "Unknown"),
            MATCH_RESULT_KEY: game.get("matchResult", "Unknown"),
            SCORES_KEY: game.get("scores", [0, 0]),
            GAME_FINISHED_AT_KEY: finished_at
        }
    except ValueError as e:
        logging.error(f"Error parsing game data for game {game.get('gameId')}: {e}")
        return None

def fetch_new_games(days: int = 2) -> List[Dict]:
    """Fetch new games from Leetify API within the specified timeframe."""
    new_games = []
    now = datetime.utcnow()
    
    existing_game_ids = (
        set(st.session_state['games_df'][GAME_ID_KEY])
        if 'games_df' in st.session_state and isinstance(st.session_state['games_df'], pd.DataFrame) and not st.session_state['games_df'].empty
        else set()
    )
    
    for steam_id in STEAM_IDS:
        profile_data = fetch_profile(steam_id)
        if not profile_data:
            continue
        
        for game in profile_data.get("games", []):
            game_id = game.get("gameId")
            if game_id not in existing_game_ids and game_id not in {g[GAME_ID_KEY] for g in new_games}:
                parsed_game = parse_game_data(game)
                if parsed_game and parsed_game[GAME_FINISHED_AT_KEY] > now - timedelta(days=days):
                    new_games.append(parsed_game)
                    existing_game_ids.add(game_id)
    
    for game in new_games:
        save_game_data(
            game[GAME_ID_KEY],
            game[MAP_NAME_KEY],
            game[MATCH_RESULT_KEY],
            game[SCORES_KEY][0],
            game[SCORES_KEY][1],
            game[GAME_FINISHED_AT_KEY].strftime("%Y-%m-%d %H:%M:%S")
        )
    
    return new_games

def get_player_stat(player: Dict, stat_key: str) -> float:
    """Extract a specific stat from player data."""
    return player.get(stat_key, 0)

def home_page() -> None:
    """Render the home page with game statistics."""
    days = st.number_input("Days back", min_value=1, max_value=15, value=2)
    games = sorted(get_cached_games(days), key=lambda x: x[GAME_FINISHED_AT_KEY], reverse=True)

    if not games:
        st.warning("No games found across all profiles.")
        return

    game_options = [f"{g.get(MAP_NAME_KEY, 'Unknown')} ({g[GAME_FINISHED_AT_KEY].strftime('%d.%m.%y %H:%M')}) - {g[GAME_ID_KEY]}" for g in games]
    selected_game = st.selectbox("Pick a game", game_options)
    game_id = selected_game.split(" - ")[-1]
    game_data = next((g for g in games if g[GAME_ID_KEY] == game_id), None)

    if game_data:
        details = fetch_game_details(game_id)
        if details:
            players = [
                {
                    "name": NAME_MAPPING.get(p["name"], p["name"]),
                    "reactionTime": p.get("reactionTime", 0),
                    "tradeKillAttemptsPercentage": p.get("tradeKillAttemptsPercentage", 0),
                    "utilityOnDeathAvg": p.get("utilityOnDeathAvg", 0),
                    "hltvRating": p.get("hltvRating", 0)
                }
                for p in details.get("playerStats", []) if NAME_MAPPING.get(p["name"], p["name"]) in ALLOWED_PLAYERS
            ]
            if players:
                players.sort(key=itemgetter("reactionTime"))
                min_rt = min(p["reactionTime"] for p in players)
                max_rt = max(p["reactionTime"] for p in players)

                best_trade = max(p["tradeKillAttemptsPercentage"] * 100 for p in players)
                worst_trade = min(p["tradeKillAttemptsPercentage"] * 100 for p in players)

                top_players = [p for p in players if p["reactionTime"] == min_rt]
                low_players = [p for p in players if p["reactionTime"] == max_rt]

                best_trade_players = [p for p in players if p["tradeKillAttemptsPercentage"] * 100 == best_trade]
                worst_trade_players = [p for p in players if p["tradeKillAttemptsPercentage"] * 100 == worst_trade]

                worst_util = max(p.get("utilityOnDeathAvg", 0) for p in players)
                best_hltv = max(p.get("hltvRating", 0) for p in players)

                worst_util_players = [p for p in players if p.get("utilityOnDeathAvg", 0) == worst_util]
                best_hltv_players = [p for p in players if p.get("hltvRating", 0) == best_hltv]

                col1, col2 = st.columns([1, 1], gap="small")
                col3, col4 = st.columns([1, 1], gap="small")

                with col1:
                    st.markdown(
                        f"""
                        <div style="padding: 15px; background-color: #388E3C; color: white; border-radius: 10px; text-align: center; border: 1px solid black; margin: 5px;">
                            <h3>🔥 Reaction Time</h3>
                            <h4>💪 Gooner: {', '.join(p['name'] for p in top_players)} ({min_rt}s)</h4>
                            <h4>🍺 Pils-bitch: {', '.join(p['name'] for p in low_players)} ({max_rt}s)</h4>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                with col2:
                    st.markdown(
                        f"""
                        <div style="padding: 15px; background-color: #1976D2; color: white; border-radius: 10px; text-align: center; border: 1px solid black; margin: 5px;">
                            <h3>🎯 Trade Kill Attempts</h3>
                            <h4>✅ Rizzler: {', '.join(p['name'] for p in best_trade_players)} ({best_trade:.1f}%)</h4>
                            <h4>❌ Baiterbot: {', '.join(p['name'] for p in worst_trade_players)} ({worst_trade:.1f}%)</h4>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                with col3:
                    st.markdown(
                        f"""
                        <div style="padding: 15px; background-color: #D32F2F; color: white; border-radius: 10px; text-align: center; border: 1px solid black; margin: 5px;">
                            <h3>💣 Utility on Death</h3>
                            <h4>🔥 McRizzler: {', '.join(p['name'] for p in worst_util_players)} ({worst_util:.2f})</h4>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                with col4:
                    st.markdown(
                        f"""
                        <div style="padding: 15px; background-color: #388E3C; color: white; border-radius: 10px; text-align: center; border: 1px solid black; margin: 5px;">
                            <h3>🏆 Best HLTV Rating</h3>
                            <h4>⭐ OhioMaster: {', '.join(p['name'] for p in best_hltv_players)} ({best_hltv:.2f})</h4>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

    st.write(f"Total games across all profiles: {len(games)}")

def input_data_page() -> None:
    """Render the input data page for entering konsum data."""
    st.header("Input BubbeData")
    days = st.number_input("Days back", min_value=1, max_value=10, value=2)
    games = sorted(get_cached_games(days), key=lambda x: x.get(GAME_FINISHED_AT_KEY, datetime.min), reverse=True)

    if not games:
        st.warning("No games found in the selected timeframe.")
        return

    for game in games:
        details = fetch_game_details(game.get(GAME_ID_KEY))
        if not details:
            st.write(f"Skipping game {game.get(GAME_ID_KEY, 'unknown')} - no details available.")
            continue

        map_name = game.get(MAP_NAME_KEY, "Unknown")
        match_result = game.get(MATCH_RESULT_KEY, "Unknown")
        scores = game.get(SCORES_KEY, [0, 0])
        game_finished_at = game.get(GAME_FINISHED_AT_KEY, datetime.now())
        
        if isinstance(game_finished_at, str):
            try:
                game_finished_at = parse(game_finished_at)
            except ValueError:
                game_finished_at = datetime.now()

        label = f"{map_name} - {match_result} ({scores[0]}:{scores[1]}) - {game_finished_at.strftime('%d.%m.%y %H:%M')}"
        with st.expander(label):
            konsum = st.session_state['cached_konsum'].get(game[GAME_ID_KEY], fetch_konsum_data_for_game(game[GAME_ID_KEY]) or {})
            st.session_state['cached_konsum'][game[GAME_ID_KEY]] = konsum

            for p in details.get("playerStats", []):
                name = NAME_MAPPING.get(p["name"], p["name"])
                if name in ALLOWED_PLAYERS:
                    st.write(f"{name} - K/D: {p['kdRatio']}, ADR: {p['dpr']}, HLTV: {p['hltvRating']}")
                    prev_beer = konsum.get(name, {}).get("beer", 0)
                    prev_water = konsum.get(name, {}).get("water", 0)
                    beer = st.number_input(f"Beers for {name}", min_value=0, value=prev_beer, key=f"beer-{name}-{game[GAME_ID_KEY]}")
                    water = st.number_input(f"Water for {name}", min_value=0, value=prev_water, key=f"water-{name}-{game[GAME_ID_KEY]}")
                    if beer != prev_beer or water != prev_water:
                        save_konsum_data(game[GAME_ID_KEY], name, beer, water)
                        st.session_state['cached_konsum'][game[GAME_ID_KEY]][name] = {"beer": beer, "water": water}
                        st.success(f"Updated {name}: {beer} beers, {water} water")

STAT_MAP = {
    "K/D Ratio": "kdRatio", "ADR": "dpr", "HLTV Rating": "hltvRating", "Reaction Time": "reactionTime",
    "Enemies Flashed": "flashbangThrown", "2k Kills": "multi2k", "3k Kills": "multi3k"
}

def stats_page() -> None:
    """Render the stats page with player statistics visualization."""
    st.header("Stats")
    days = st.number_input("Days back", min_value=1, max_value=7, value=2)
    stat_options = list(STAT_MAP.keys()) + ["Beer", "Water"]
    selected_stat = st.selectbox("Stat to plot", stat_options)
    stat_key = STAT_MAP.get(selected_stat, selected_stat.lower())

    with st.spinner("Loading stats..."):
        games = get_cached_games(days)
        stats_data = []
        player_stats = {name: {'kd': [], 'rt': [], 'trade': []} for name in ALLOWED_PLAYERS}

        for game in games:
            details = fetch_game_details(game[GAME_ID_KEY])
            konsum = get_cached_konsum(game[GAME_ID_KEY])
            game_label = f"{game[MAP_NAME_KEY]} ({game[GAME_FINISHED_AT_KEY].strftime('%d.%m.%y %H:%M')})"

            for p in details.get("playerStats", []):
                name = NAME_MAPPING.get(p["name"], p["name"])
                if name in ALLOWED_PLAYERS:
                    value = konsum.get(name, {}).get(stat_key, 0) if stat_key in ["beer", "water"] else p.get(stat_key, 0)
                    stats_data.append({"Game": game_label, "Player": name, "Value": value})
                    player_stats[name]['kd'].append(p.get("kdRatio", 0))
                    player_stats[name]['rt'].append(p.get("reactionTime", 0))
                    player_stats[name]['trade'].append(p.get("tradeKillAttemptsPercentage", 0) * 100)

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

        st.markdown(
            f"""
            <div style="padding: 10px; border: 1px solid #f0f0f0; border-radius: 5px; margin-bottom: 10px;">
                <h4>Best Average Stats Across Games</h4>
                <p>Best avg KD: {best_kd[0]} ({best_kd[1]:.2f})</p>
                <p>Best avg Reaction Time: {best_rt[0]} ({best_rt[1]:.2f}s)</p>
                <p>Best avg Trade Attempts: {best_trade[0]} ({best_trade[1]:.1f}%)</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        if stats_data:
            df = pd.DataFrame(stats_data)
            fig = px.bar(df, x="Player", y="Value", color="Game", barmode="group", title=f"{selected_stat} per Player")
            st.plotly_chart(fig)
            if st.button("Download All Stats as CSV"):
                Download_Game_Stats(days)

def Download_Game_Stats(days: int) -> None:
    """Download all game statistics as a CSV file."""
    try:
        all_game_data = []
        with st.spinner("Henter game data..."):
            games = sorted(get_cached_games(days), key=lambda game: game[GAME_FINISHED_AT_KEY], reverse=True)

            for game in games:
                game_id = game[GAME_ID_KEY]
                map_name = game[MAP_NAME_KEY]
                game_details = fetch_game_details(game_id)
                konsum_data = get_cached_konsum(game_id)

                for player in game_details.get("playerStats", []):
                    raw_name = player["name"]
                    mapped_name = NAME_MAPPING.get(raw_name, raw_name)
                    
                    if mapped_name in ALLOWED_PLAYERS:
                        player_data = {
                            "Game": map_name,
                            "Player": mapped_name,
                            "Date": game[GAME_FINISHED_AT_KEY].strftime("%Y-%m-%d %H:%M"),
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
    except Exception as e:
        st.error(f"Error downloading stats: {e}")

def motivation_page() -> None:
    """Render the motivation page with an embedded YouTube video."""
    st.header("Get skibid going!")
    st.markdown(
        """
        <iframe width="560" height="315" src="https://www.youtube.com/embed/6dMjCa0nqK0" 
        frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
        allowfullscreen></iframe>
        """,
        unsafe_allow_html=True
    )

def img_to_base64(img_path: str) -> str:
    """Convert an image to base64 string."""
    try:
        with open(img_path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode()
    except FileNotFoundError:
        logging.error(f"Image file not found: {img_path}")
        return ""

def main() -> None:
    """Main function to render the Streamlit app."""
    img_base64 = img_to_base64("bubblogo2.png")
    st.markdown(
        f"""
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
        """,
        unsafe_allow_html=True
    )

    initialize_session_state()

    if st.button("🔄 Refresh Data"):
        refresh_all()

    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ("🏠 Home", "📝 Input", "📊 Stats", "🚽 Motivation"))

    if page == "🏠 Home":
        home_page()
    elif page == "📝 Input":
        input_data_page()
    elif page == "📊 Stats":
        stats_page()
    elif page == "🚽 Motivation":
        motivation_page()

if __name__ == "__main__":
    main()