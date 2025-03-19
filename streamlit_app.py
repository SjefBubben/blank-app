import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from operator import itemgetter
from datetime import datetime, timedelta
from io import StringIO
from DataInout import fetch_games_within_last_48_hours, fetch_konsum_data_for_game, save_konsum_data, save_game_data

# Base API URLs
PROFILE_API = "https://api.cs-prod.leetify.com/api/profile/id/"
GAMES_API = "https://api.cs-prod.leetify.com/api/games/"

# User's Steam ID
STEAM_ID = "76561197983741618"

# Name mapping for players
NAME_MAPPING = {
    "JimmyJimbob": "Jeppe", "Jimmy": "Jeppe", "Kåre": "Torgrizz", "Kaare": "Torgrizz",
    "Fakeface": "Birkle", "Killthem26": "Birkle", "Lars Olaf": "PappaBubben",
    "Bøghild": "Bøghild", "Nish": "Nish", "Zohan": "Patient 0"
}
ALLOWED_PLAYERS = set(NAME_MAPPING.values())

# API fetch functions
def fetch_profile(steam_id):
    try:
        response = requests.get(PROFILE_API + steam_id)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None

def fetch_game_details(game_id):
    try:
        response = requests.get(GAMES_API + game_id)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None

# Fetch and save new games within the last X days
def fetch_new_games(days=2):
    games_in_db = fetch_games_within_last_48_hours(days)
    saved_game_ids = {game['game_id'] for game in games_in_db}

    profile_data = fetch_profile(STEAM_ID)
    if not profile_data:
        return []

    games_from_api = profile_data.get("games", [])
    new_games = []
    games_needing_stats = []
    current_time = datetime.utcnow()

    for game in games_from_api:
        game_id = game.get("gameId")
        if game_id not in saved_game_ids:
            try:
                game_finished_at = datetime.strptime(game["gameFinishedAt"], "%Y-%m-%dT%H:%M:%S.%fZ")
                if game_finished_at > current_time - timedelta(days=days):
                    new_games.append({
                        "game_id": game_id, "map_name": game.get("mapName", "Unknown Map"),
                        "match_result": game.get("matchResult", "Unknown Result"),
                        "scores": game.get("scores", [0, 0]), "game_finished_at": game_finished_at
                    })
                    games_needing_stats.append(game_id)
            except (ValueError, KeyError):
                continue

    for game in new_games:
        save_game_data(
            game["game_id"], game["map_name"], game["match_result"],
            game["scores"][0], game["scores"][1], game["game_finished_at"]
        )

    game_stats_batch = {game_id: fetch_game_details(game_id) for game_id in games_needing_stats if fetch_game_details(game_id)}
    for game in new_games:
        game["details"] = game_stats_batch.get(game["game_id"], {})

    return new_games

@st.cache_data(ttl=300)
def get_cached_games(days=2):
    return fetch_games_within_last_48_hours(days)

# Home Page
def home_page():
    days = st.number_input("Skriv inn antall dager tilbake i tid", min_value=1, max_value=7, value=2)
    with st.spinner("Checking for new games..."):
        new_games = fetch_new_games(days)
        games_in_memory = sorted(get_cached_games(days), key=lambda x: x["game_finished_at"], reverse=True)

    if not games_in_memory:
        st.write("No games found in the selected timeframe.")
        return

    game_options = [f"{g['map_name']} ({g['game_finished_at'].strftime('%d.%m.%y %H:%M')}) - {g['game_id']}" for g in games_in_memory]
    selected_game = st.selectbox("Select a game", game_options)
    selected_game_id = selected_game.split(" - ")[-1]
    selected_game_details = next((g for g in games_in_memory if g["game_id"] == selected_game_id), None)

    if selected_game_details:
        game_details = fetch_game_details(selected_game_id)
        if game_details:
            all_players = [
                {"name": NAME_MAPPING.get(p["name"], p["name"]), "reactionTime": p.get("reactionTime", 0)}
                for p in game_details.get("playerStats", []) if NAME_MAPPING.get(p["name"], p["name"]) in ALLOWED_PLAYERS
            ]
            all_players.sort(key=itemgetter("reactionTime"))

            if all_players:
                # Find fastest (min reaction time) and slowest (max reaction time)
                min_reaction_time = min(p["reactionTime"] for p in all_players)
                max_reaction_time = max(p["reactionTime"] for p in all_players)

                # Get all players tied for fastest
                top_players = [p for p in all_players if p["reactionTime"] == min_reaction_time]
                # Get all players tied for slowest
                low_players = [p for p in all_players if p["reactionTime"] == max_reaction_time]

                # Handle the "previous low player" logic for slowest
                if "previous_low_player" in st.session_state and st.session_state.previous_low_player in [p["name"] for p in low_players] and len(all_players) > len(low_players):
                    # If the previous low player is among the tied slowest, pick the next slowest group
                    next_slowest_time = min(p["reactionTime"] for p in all_players if p["reactionTime"] > max_reaction_time or p not in low_players)
                    low_players = [p for p in all_players if p["reactionTime"] == next_slowest_time]
                
                # Update the previous low player to the first of the slowest group (arbitrary choice for tie)
                st.session_state.previous_low_player = low_players[0]["name"]

                # Format names for display
                top_names = ", ".join(p["name"] for p in top_players)
                low_names = ", ".join(p["name"] for p in low_players)

                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"""
                        <div style="padding: 10px; background-color: #4CAF50; color: white; border-radius: 10px; text-align: center; box-shadow: 0px 4px 6px rgba(0,0,0,0.1);">
                            <h3>💪 Raskeste gooner</h3>
                            <h4><strong>{top_names}</strong></h4>
                        </div>
                    """, unsafe_allow_html=True)
                with col2:
                    st.markdown(f"""
                        <div style="padding: 10px; background-color: #F44336; color: white; border-radius: 10px; text-align: center; box-shadow: 0px 4px 6px rgba(0,0,0,0.1);">
                            <h3>🍺 Tregeste pils-bitch</h3>
                            <h4><strong>{low_names}</strong></h4>
                        </div>
                    """, unsafe_allow_html=True)

    if new_games:
        st.write("### Nye bubbegames")
        for game in new_games:
            st.write(f"**{game['map_name']} - {game['match_result'].capitalize()} ({game['scores'][0]}:{game['scores'][1]})**")
            st.write(f"Game ID: {game['game_id']}")
    st.write(f"### Total Bubbegames lagret over valgt tidsrom: {len(games_in_memory)}")

# Input Data Page
def input_data_page():
    st.header("Input BubbeData")
    days = st.number_input("Skriv inn antall dager tilbake i tid", min_value=1, max_value=7, value=2)
    games_in_memory = sorted(get_cached_games(days), key=lambda x: x["game_finished_at"], reverse=True)

    for game in games_in_memory:
        game_id = game["game_id"]
        game_details = fetch_game_details(game_id)
        if not game_details:
            continue

        with st.expander(f"{game['map_name']} - {game['match_result'].capitalize()} ({game['scores'][0]}:{game['scores'][1]}) - {game['game_finished_at'].strftime('%d.%m.%y %H:%M')}"):
            konsum_data = st.session_state.get(game_id, fetch_konsum_data_for_game(game_id) or {})
            st.session_state[game_id] = konsum_data

            for player in game_details.get("playerStats", []):
                mapped_name = NAME_MAPPING.get(player["name"], player["name"])
                if mapped_name in ALLOWED_PLAYERS:
                    st.write(f"**{mapped_name}** - K/D: {player['kdRatio']}, ADR: {player['dpr']}, HLTV Rating: {player['hltvRating']}")
                    previous_beer = konsum_data.get(mapped_name, {}).get('beer', 0)
                    previous_water = konsum_data.get(mapped_name, {}).get('water', 0)

                    beers = st.number_input(f"How many pils på {mapped_name}?", min_value=0, value=previous_beer, step=1, key=f"{mapped_name}-beer-{game_id}")
                    water = st.number_input(f"How mye hydrering på {mapped_name}?", min_value=0, value=previous_water, step=1, key=f"{mapped_name}-water-{game_id}")

                    if beers != previous_beer or water != previous_water:
                        save_konsum_data(game_id, mapped_name, beers, water)
                        st.session_state[game_id][mapped_name] = {'beer': beers, 'water': water}
                        st.success(f"Data for {mapped_name} updated: {beers} Beers, {water} Glasses of Water")

# Stats Page
stat_display_mapping = {
    "K/D Ratio": 'kdRatio', "ADR (Average Damage per Round)": "dpr", "HLTV Rating": "hltvRating",
    "Enemies Flashed": "flashbangThrown", "Friends Flashed": "flashbangHitFoe", "Avg. Unused Utility": "utilityOnDeathAvg",
    "Trade Kill Opportunities": "tradeKillOpportunities", "Trade Kill Attempts": "tradeKillAttempts",
    "Trade Kill Success": "tradeKillsSucceeded", "2k Kills": "multi2k", "3k Kills": "multi3k",
    "4k Kills": "multi4k", "5k Kills": "multi5k", "Flashbang Leading to Kill": "flashbangLeadingToKill",
    "Reaction Time": "reactionTime", "HE Grenades Thrown": "heThrown", "Molotovs Thrown": "molotovThrown",
    "Smokes Thrown": "smokeThrown"
}

def Stats():
    st.header("Game Stats Bar Chart")
    days = st.number_input("Skriv inn antall dager tilbake i tid", min_value=1, max_value=7, value=2)
    stat_options = list(stat_display_mapping.keys()) + ["Beer", "Water"]
    selected_stat_display_name = st.selectbox("Select a stat to display in the bar chart:", stat_options)
    selected_stat = stat_display_mapping.get(selected_stat_display_name, selected_stat_display_name.lower())

    with st.spinner("Fetching games and stats..."):
        games_in_memory = sorted(get_cached_games(days), key=lambda x: x["game_finished_at"])
        player_stats = []

        for game in games_in_memory:
            game_details = fetch_game_details(game["game_id"])
            konsum_data = fetch_konsum_data_for_game(game["game_id"]) or {}
            game_time = game["game_finished_at"].strftime("%d.%m.%y %H:%M")

            for player in game_details.get("playerStats", []):
                mapped_name = NAME_MAPPING.get(player["name"], player["name"])
                if mapped_name in ALLOWED_PLAYERS:
                    stat_value = konsum_data.get(mapped_name, {}).get(selected_stat, 0) if selected_stat in ["beer", "water"] else player.get(selected_stat, 0)
                    player_stats.append({
                        "Game": f"{game['map_name']} ({game_time})", "Player": mapped_name,
                        "Stat Type": selected_stat_display_name, "Stat Value": stat_value
                    })

        if player_stats:
            df = pd.DataFrame(player_stats)
            fig = px.bar(df, x="Player", y="Stat Value", color="Game", barmode="group", title=f"{selected_stat_display_name} per Player in Recent Games")
            st.plotly_chart(fig)
            if st.button("Klikk her for å laste gamedata i CSV format"):
                Download_Game_Stats(days, player_stats)

# Download Game Stats
def Download_Game_Stats(days, player_stats=None):
    if not player_stats:
        player_stats = []
        games_in_memory = sorted(get_cached_games(days), key=lambda x: x["game_finished_at"], reverse=True)
        for game in games_in_memory:
            game_details = fetch_game_details(game["game_id"])
            konsum_data = fetch_konsum_data_for_game(game["game_id"]) or {}
            for player in game_details.get("playerStats", []):
                mapped_name = NAME_MAPPING.get(player["name"], player["name"])
                if mapped_name in ALLOWED_PLAYERS:
                    player_data = {"Game": game["map_name"], "Player": mapped_name, "Date": game["game_finished_at"].strftime("%Y-%m-%d %H:%M")}
                    player_data.update({k: player.get(v, 0) for k, v in stat_display_mapping.items()})
                    player_data["Beer"] = konsum_data.get(mapped_name, {}).get("beer", 0)
                    player_data["Water"] = konsum_data.get(mapped_name, {}).get("water", 0)
                    player_stats.append(player_data)

    df_full = pd.DataFrame(player_stats)
    csv_buffer = StringIO()
    df_full.to_csv(csv_buffer, index=False)
    st.download_button(label="Klikk her for å laste ned CSV fil", data=csv_buffer.getvalue(), file_name="all_game_stats.csv", mime="text/csv")

# Motivation Page
def motivation_page():
    st.title("Get Skibid going")
    st.write("Bubbesnacks:")
    st.markdown("""
        <iframe width="600" height="315" src="https://www.youtube.com/embed/6dMjCa0nqK0"  
        frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"  
        allowfullscreen></iframe>
    """, unsafe_allow_html=True)

# UI Setup
st.image("bubblogo2.png", width=75)
st.markdown("<h1 style='text-align: center; font-weight: bold;'>Bubberne Gaming</h1>", unsafe_allow_html=True)

col1, col2, col3, col4 = st.columns(4)
with col1:
    if st.button("🏠 Hjem", use_container_width=True):
        st.session_state["page"] = "Home"
with col2:
    if st.button("📝 Input BubbeData", use_container_width=True):
        st.session_state["page"] = "Input Data"
with col3:
    if st.button("📊 Stats", use_container_width=True):
        st.session_state["page"] = "Stats"
with col4:
    if st.button("🚽 Motivasjon", use_container_width=True):
        st.session_state["page"] = "Motivasjon"

if "page" not in st.session_state:
    st.session_state["page"] = "Home"

if st.session_state["page"] == "Home":
    home_page()
elif st.session_state["page"] == "Input Data":
    input_data_page()
elif st.session_state["page"] == "Stats":
    Stats()
elif st.session_state["page"] == "Motivasjon":
    motivation_page()