import streamlit as st
import time
import requests
import pandas as pd
import plotly.express as px
import time
from operator import itemgetter
from datetime import datetime, timedelta
from io import StringIO
from DataInout import fetch_games_within_last_48_hours, fetch_konsum_data_for_game, save_konsum_data, save_game_data


st.markdown(
    """
    <link rel="icon" href="bubblogo.png" type="image/png">
    """, 
    unsafe_allow_html=True
)

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
@st.cache_data(ttl=10 * 10)
def get_cached_games():
    games_in_memory = fetch_games_within_last_48_hours()
    return games_in_memory
# **Home Page**
def home_page():
    try:
        with st.spinner("Checking for new games..."):
            time.sleep(2)
            new_games = fetch_new_games()  # Only fetch games from the last 48 hours

        games_in_memory = sorted(st.session_state["games_data"], key=lambda game: game["game_finished_at"], reverse=True)

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

        # Extract the highest and lowest rated players in the most recent game
        top_player = None
        low_player = None
        second_low_player = None

        if games_in_memory:  # Ensure there is at least one game
            # Get the most recent game
            latest_game = games_in_memory[0]  # Assuming games_in_memory is sorted by game_finished_at

            game_id = latest_game["game_id"]
            game_details = fetch_game_details(game_id)

            all_players = []

            # Loop through players in the most recent game
            for player in game_details.get("playerStats", []):
                if player["name"] in ALLOWED_PLAYERS:
                    all_players.append({
                        "name": player["name"],
                        "hltvRating": player.get("hltvRating", 0)  # Use 0 if rating is missing
                    })

            # Sort players by HLTV rating
            all_players.sort(key=itemgetter("hltvRating"))

            if all_players:
                # Determine the top and low player for the current game
                top_player = all_players[-1]  # Highest rating
                low_player = all_players[0]  # Lowest rating

                # If the low player is the same as last game, select the second-lowest
                if 'previous_low_player' in st.session_state and st.session_state.previous_low_player == low_player['name']:
                    if len(all_players) > 1:
                        second_low_player = all_players[1]  # Second-lowest player
                        low_player = second_low_player
                    else:
                        # If there's only one player, we'll just keep them as the low player
                        low_player = all_players[0]
                # Store the current low player for comparison in the next session
                st.session_state.previous_low_player = low_player['name']

                # Display the cards with a polished design
                col1, col2 = st.columns(2)

                with col1:
                    st.markdown(f"""
                        <div style="padding: 10px; background-color: #4CAF50; color: white; border-radius: 10px; text-align: center; box-shadow: 0px 4px 6px rgba(0,0,0,0.1);">
                            <h3>💪 Gjeldende top-gooner</h3>
                            <h4><strong>{top_player['name']}</strong></h4>
                        </div>
                    """, unsafe_allow_html=True)

                with col2:
                    # Decide which low player to show
                    low_player_display = second_low_player['name'] if second_low_player else low_player['name']
                    st.markdown(f"""
                        <div style="padding: 10px; background-color: #F44336; color: white; border-radius: 10px; text-align: center; box-shadow: 0px 4px 6px rgba(0,0,0,0.1);">
                            <h3>🍺 Gjeldende pils-bitch</h3>
                            <h4><strong>{low_player_display}</strong></h4>
                        </div>
                    """, unsafe_allow_html=True)

    except Exception as e:
        st.error(f"An error occurred while fetching new games: {e}")

# Function to refresh data manually
def refresh_data():
    st.session_state["games_data"] = get_cached_games()

def input_data_page():
    st.header("Input BubbeData")

    # Add a refresh button at the top
    if st.button("Refresh Data fra Sheets"):
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

@st.cache_data(ttl=5 * 5)
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

def Stats():
    st.header("Game Stats Bar Chart")

    try:
        # Stat selection dropdown
        stat_options = list(stat_display_mapping.keys()) + ["Beer", "Water"]
        selected_stat_display_name = st.selectbox("Select a stat to display in the bar chart:", stat_options)

        # Get the actual stat key
        selected_stat = stat_display_mapping.get(selected_stat_display_name, selected_stat_display_name.lower())

        player_stats = []

        with st.spinner("Fetching games and stats...Checking if Tobias gay?"):

            games_in_memory = sorted(get_cached_games(), key=lambda game: game["game_finished_at"], reverse=True)

            for game in games_in_memory:
                game_id = game["game_id"]
                map_name = game["map_name"]
                game_details = fetch_game_details(game_id)
                konsum_data = get_cached_konsum(game_id)  # Fetch beer & water data

                for player in game_details.get("playerStats", []):
                    if player["name"] in ALLOWED_PLAYERS:
                        # Get stat value
                        if selected_stat == "beer":
                            stat_value = konsum_data.get(player["name"], {}).get("beer", 0)
                        elif selected_stat == "water":
                            stat_value = konsum_data.get(player["name"], {}).get("water", 0)
                        else:
                            stat_value = get_player_stat(player, selected_stat)

                        # Add to player stats list
                        player_stats.append({
                            "Game": map_name,
                            "Player": player["name"],
                            "Stat Type": selected_stat_display_name,
                            "Stat Value": stat_value
                        })

            if player_stats:
                # Convert stats to DataFrame for plotting
                df = pd.DataFrame(player_stats)
                df = df.iloc[::-1]

                # Plot the bar chart
                fig = px.bar(df, x="Player", y="Stat Value", color="Game", barmode="group", title=f"{selected_stat_display_name} per Player in Recent Games")
                st.plotly_chart(fig)

                # **Add CSV Download Button**
                if st.button("Klikk her for å laste gamedata i CSV format"):
                    Download_Game_Stats()

            else:
                st.warning("No data available.")

    except Exception as e:
        st.error(f"An error occurred while generating the bar chart: {e}")

def Download_Game_Stats():
    try:
        all_game_data = []

        with st.spinner("Henter game data..."):
            games_in_memory = sorted(get_cached_games(), key=lambda game: game["game_finished_at"], reverse=True)

            for game in games_in_memory:
                game_id = game["game_id"]
                map_name = game["map_name"]
                game_details = fetch_game_details(game_id)
                konsum_data = get_cached_konsum(game_id)  # Fetch beer & water data

                for player in game_details.get("playerStats", []):
                    if player["name"] in ALLOWED_PLAYERS:
                        # Prepare full stats dictionary for CSV
                        player_data = {
                            "Game": map_name,
                            "Player": player["name"],
                            "Date": game["game_finished_at"].strftime("%Y-%m-%d %H:%M"),
                        }

                        # Add all game stats
                        for display_name, stat_key in stat_display_mapping.items():
                            player_data[display_name] = get_player_stat(player, stat_key)

                        # Add Beer & Water
                        player_data["Beer"] = konsum_data.get(player["name"], {}).get("beer", 0)
                        player_data["Water"] = konsum_data.get(player["name"], {}).get("water", 0)

                        all_game_data.append(player_data)

        if all_game_data:
            # Convert to DataFrame and export to CSV
            df_full = pd.DataFrame(all_game_data)
            csv_buffer = StringIO()
            df_full.to_csv(csv_buffer, index=False)
            csv_data = csv_buffer.getvalue()

            # Display download button
            st.download_button(
                label="Klikk her for å laste ned CSV fil",
                data=csv_data,
                file_name="all_game_stats.csv",
                mime="text/csv"
            )

        else:
            st.warning("No game data available for download.")

    except Exception as e:
        st.error(f"An error occurred while exporting the CSV: {e}")


# **Navigation Buttons**
st.markdown("<h3 style='text-align: center;'>Welcome to Bubberne Gaming</h3>", unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("🏠 Hjem", use_container_width=True):
        st.session_state["page"] = "Home"

with col2:
    if st.button("📝 Input BubbeData", use_container_width=True):
        st.session_state["page"] = "Input Data"

with col3:
    if st.button("📊 Stats", use_container_width=True):
        st.session_state["page"] = "Stats"

# **Handle Page Display**
if "page" not in st.session_state:
    st.session_state["page"] = "Home"  # Default page

if st.session_state["page"] == "Home":
    home_page()
elif st.session_state["page"] == "Input Data":
    input_data_page()
elif st.session_state["page"] == "Stats":
    Stats()