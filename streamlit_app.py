import streamlit as st
import time
import requests
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from io import StringIO
from DataInout import fetch_games_within_last_48_hours, fetch_konsum_data_for_game, save_konsum_data, save_game_data

# Base API URLs
PROFILE_API = "https://api.cs-prod.leetify.com/api/profile/id/"
GAMES_API = "https://api.cs-prod.leetify.com/api/games/"

# User's Steam ID
STEAM_ID = "76561197983741618"

# Allowed player names
ALLOWED_PLAYERS = {"Jimmy", "Kåre", "Fakeface", "Lars Olaf", "Bøghild", "Nish", "Zohan"}

# Fetch profile data
def fetch_profile(steam_id):
    response = requests.get(PROFILE_API + steam_id)
    if response.status_code == 200:
        return response.json()
    return None

# Fetch game details
def fetch_game_details(game_id):
    response = requests.get(GAMES_API + game_id)
    if response.status_code == 200:
        return response.json()
    return None

# Fetch new games and filter by the last 48 hours
def fetch_new_games():
    games_in_db = fetch_games_within_last_48_hours()  # Fetch games already saved in the last 48 hours
    saved_game_ids = {game['game_id'] for game in games_in_db}  # Set of known game IDs

    profile_data = fetch_profile(STEAM_ID)
    if not profile_data:
        return []

    games_from_api = profile_data.get("games", [])
    new_games = []
    games_needing_stats = []  # For games that need detailed stats

    current_time = datetime.utcnow()  # Get the current UTC time

    for game in games_from_api:
        game_id = game.get("gameId")
        if game_id not in saved_game_ids:
            game_finished_at_str = game.get("gameFinishedAt")
            if game_finished_at_str:
                game_finished_at = datetime.strptime(game_finished_at_str, "%Y-%m-%dT%H:%M:%S.%fZ")

                # Only consider the game if it finished within the last 48 hours
                if game_finished_at > current_time - timedelta(hours=48):
                    new_games.append({
                        "game_id": game_id,
                        "map_name": game.get("mapName", "Unknown Map"),
                        "match_result": game.get("matchResult", "Unknown Result"),
                        "scores": game.get("scores", [0, 0]),
                        "game_finished_at": game_finished_at_str
                    })
                    games_needing_stats.append(game_id)

    if not new_games:
        return []

    for game in new_games:
        save_game_data(
            game["game_id"],
            game["map_name"],
            game["match_result"],
            game["scores"][0],
            game["scores"][1],
            game["game_finished_at"]
        )

    # Fetch game details for each individual game_id
    game_stats_batch = {}
    for game_id in games_needing_stats:
        game_details = fetch_game_details(game_id)
        if game_details:
            game_stats_batch[game_id] = game_details

    # Now, assign the detailed stats to each game
    for game in new_games:
        game["details"] = game_stats_batch.get(game["game_id"], {})

    return new_games
@st.cache_data(ttl=5 * 5)
def get_cached_games():
    games_in_memory = fetch_games_within_last_48_hours()
    return games_in_memory
# **Home Page**
def home_page():
    st.header("Welcome to Bubberne Gaming")

    try:
        with st.spinner("Checking for new games..."):
            time.sleep(2)
            new_games = fetch_new_games()  # Only fetch games from the last 48 hours

        games_in_memory = get_cached_games()

        if new_games:
            st.write("### Nye bubbegames")
            for new_game in new_games:
                game_id = new_game["game_id"]
                map_name = new_game["map_name"]
                match_result = new_game["match_result"]
                scores = new_game["scores"]
                st.write(f"**{map_name} - {match_result.capitalize()} ({scores[0]}:{scores[1]})**")
                st.write(f"Game ID: {game_id}")

            st.write(f"### Total Bubbegames lagret (Siste 48 timer): {len(games_in_memory)}")
        else:
            st.write("### Ingen nye bubbegames funnet.")
            st.write(f"Total Bubbegames lagret (Siste 48 timer): {len(games_in_memory)}")
    except Exception as e:
        st.error(f"An error occurred while fetching new games: {e}")

# Function to refresh data manually
def refresh_data():
    st.session_state["games_data"] = get_cached_games()

def input_data_page():
    st.header("Input BubbeData")

    # Add a refresh button at the top
    if st.button("Refresh Data from Sheets"):
        refresh_data()
        st.experimental_rerun()

    try:
        # Load games only if not already in session state
        if "games_data" not in st.session_state:
            st.session_state["games_data"] = get_cached_games()

        # Sort games by newest first
        games_in_memory = sorted(st.session_state["games_data"], key=lambda game: game["game_finished_at"], reverse=True)

        for game in games_in_memory:
            game_id = game["game_id"]
            map_name = game["map_name"]
            match_result = game["match_result"]
            game_finished_at = game["game_finished_at"]
            scores = [game["score_team1"], game["score_team2"]]

            game_details = fetch_game_details(game_id)

            match_time = game_finished_at.strftime("%d.%m.%y %H:%M")

            # Store konsum data in session state to prevent reloading
            if game_id not in st.session_state:
                st.session_state[game_id] = fetch_konsum_data_for_game(game_id) or {}

            konsum_data = st.session_state[game_id]

            with st.expander(f"{map_name} - {match_result.capitalize()} ({scores[0]}:{scores[1]}) - {match_time}"):

                st.write("### Player Stats")
                for player in game_details.get("playerStats", []):
                    if player["name"] in ALLOWED_PLAYERS:
                        st.write(f"**{player['name']}** - K/d: {player['kdRatio']}, ADR: {player['dpr']}, HLTV Rating: {player['hltvRating']}")

                        previous_beer = konsum_data.get(player["name"], {}).get('beer', 0)
                        previous_water = konsum_data.get(player["name"], {}).get('water', 0)

                        # Input fields for beer and water
                        beers = st.number_input(f"How many pils på {player['name']}?", min_value=0, value=previous_beer, step=1, key=f"{player['name']}-beer-{game_id}")
                        water = st.number_input(f"How mye hydrering på {player['name']}?", min_value=0, value=previous_water, step=1, key=f"{player['name']}-water-{game_id}")

                        # Save data only if values change
                        if beers != previous_beer or water != previous_water:
                            save_konsum_data(game_id, player["name"], beers, water)
                            st.session_state[game_id][player["name"]] = {'beer': beers, 'water': water}
                            st.success(f"Data for {player['name']} updated: {beers} Beers, {water} Glasses of Water")

    except Exception as e:
        st.error(f"An error occurred while processing game data: {e}")

@st.cache_data(ttl=2 * 2)
def get_cached_konsum(game_id):
    konsum_in_memory = fetch_konsum_data_for_game(game_id)
    return konsum_in_memory

    # Mapping from display names to API keys
stat_display_mapping = {
    "ADR (Average Damage per Round)": "dpr",  # "adr" is the display name, "dpr" is the key in the API response
    "HLTV Rating": "hltvRating",
    "Enemies Flashed": "flashbangThrown",
    "Friends Flashed": "flashbangHitFoe",
    "Avg. Unused Utility": "utilityOnDeathAvg",
    "Trade Kill Opportunities": "tradeKillOpportunities",
    "Trade Kill Attempts": "tradeKillAttempts",
    "Trade Kill Success": "tradeKillsSucceeded",
    "2k Kills": "multi2k",
    "3k Kills": "multi3k",
    "4k Kills": "multi4k",
    "5k Kills": "multi5k",
    "Flashbang Leading to Kill": "flashbangLeadingToKill",
    "Reaction Time": "reactionTime",
    "HE Grenades Thrown": "heThrown",
    "Molotovs Thrown": "molotovThrown",
    "Smokes Thrown": "smokeThrown"
}

# Reverse mapping for stat names
reverse_mapping = {v: k for k, v in stat_display_mapping.items()}

# Function to safely get the player stat (checking if stat exists in the player dictionary)
def get_player_stat(player, stat_key):
    return player.get(stat_key, 0)  # Return 0 if the stat is not found

# **Bar Chart Page**
def Stats():
    st.header("Game Stats Bar Chart")

    try:
        # User selects the stat for visualization
        stat_options = list(stat_display_mapping.keys()) + ["Beer", "Water"]
        selected_stat_display_name = st.selectbox("Select a stat to display in the bar chart:", stat_options)

        # Get actual stat key from the selected display name
        selected_stat = stat_display_mapping.get(selected_stat_display_name, selected_stat_display_name.lower())

        all_game_data = []  # Stores full dataset for CSV export
        player_stats = []  # Stores data for charting

        with st.spinner("Fetching games and stats..."):

            games_in_memory = sorted(get_cached_games(), key=lambda game: game["game_finished_at"], reverse=True)

            for game in games_in_memory:
                game_id = game["game_id"]
                map_name = game["map_name"]
                game_details = fetch_game_details(game_id)
                konsum_data = get_cached_konsum(game_id)  # Fetch beer & water data

                for player in game_details.get("playerStats", []):
                    if player["name"] in ALLOWED_PLAYERS:
                        # Prepare a full stats dictionary for CSV
                        player_data = {
                            "Game": map_name,
                            "Player": player["name"],
                            "Date": game["game_finished_at"].strftime("%Y-%m-%d %H:%M"),
                        }

                        # Add all stat_display_mapping stats
                        for display_name, stat_key in stat_display_mapping.items():
                            player_data[display_name] = get_player_stat(player, stat_key)

                        # Add beer & water consumption
                        player_data["Beer"] = konsum_data.get(player["name"], {}).get("beer", 0)
                        player_data["Water"] = konsum_data.get(player["name"], {}).get("water", 0)

                        all_game_data.append(player_data)  # Store for CSV export

                        # Prepare data for the bar chart
                        if selected_stat in player_data:
                            player_stats.append({
                                "Game": map_name,
                                "Player": player["name"],
                                "Stat Type": selected_stat_display_name,
                                "Stat Value": player_data[selected_stat],
                            })

        if player_stats:
            # Convert stats to DataFrame for charting
            df_chart = pd.DataFrame(player_stats)

            # Plot bar chart
            fig = px.bar(df_chart, x="Player", y="Stat Value", color="Game", barmode="group",
                         title=f"{selected_stat_display_name} per Player in Recent Games")
            st.plotly_chart(fig)

        # Convert full game stats to CSV
        df_full = pd.DataFrame(all_game_data)
        csv_buffer = StringIO()
        df_full.to_csv(csv_buffer, index=False)
        csv_data = csv_buffer.getvalue()

        # CSV download button for all stats
        st.download_button(
            label="Download Full Game Stats CSV",
            data=csv_data,
            file_name="all_game_stats.csv",
            mime="text/csv"
        )

    except Exception as e:
        st.error(f"An error occurred while generating the bar chart: {e}")

# **Navigation**
navigation = st.radio("Navigate to:", ("Home", "Input Data", "Stats"))

if navigation == "Home":
    home_page()
elif navigation == "Input Data":
    input_data_page()
elif navigation == "Stats":
    Stats()