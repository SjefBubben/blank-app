import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, timedelta, timezone
import streamlit as st
import json

# Google Sheets ID (replace with your actual Sheet ID)
SHEET_ID = "19vqg2lx3hMCEj7MtxkISzsYz0gUaCLgSV11q-YYtXQY"

# Google Sheets authentication setup
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]


# Load service account credentials from Streamlit secrets (it is already a dictionary)
service_account_info = st.secrets["service_account"]

# Manually create a dictionary based on the service account info
service_account_info_dict = dict(service_account_info)

# Fix private key string formatting if necessary
private_key = service_account_info_dict.get("private_key")

# Ensure that the private key is formatted correctly, with newline characters properly represented
if private_key:
    private_key = private_key.replace("\\n", "\n")  # Replaces escaped newlines with actual newlines
    service_account_info_dict["private_key"] = private_key  # Update the dictionary with the fixed key

# Create credentials using the updated dictionary
creds = Credentials.from_service_account_info(service_account_info_dict, scopes=SCOPES)

def connect_to_gsheet():
    """Connects to Google Sheets using Streamlit secrets"""
    client = gspread.authorize(creds)
    return client

def save_game_data(game_id, map_name, match_result, score_team1, score_team2, game_finished_at):
    client = connect_to_gsheet()
    sheet = client.open_by_key(SHEET_ID).worksheet("games")

    # Check if the game_id already exists
    existing_games = sheet.get_all_values()
    existing_game_ids = {row[0] for row in existing_games[1:]}  # Skip header row

    if game_id not in existing_game_ids:
        sheet.append_row([game_id, map_name, match_result, score_team1, score_team2, game_finished_at])

def save_konsum_data(game_id, player_name, beer, water_glasses):
    client = connect_to_gsheet()
    sheet = client.open_by_key(SHEET_ID).worksheet("konsum")

    # Fetch existing konsum records
    existing_konsum_data = sheet.get_all_values()

    # Find the row index where the game_id and player_name exist
    for i, row in enumerate(existing_konsum_data):
        if row[0] == game_id and row[1] == player_name:
            # Update the beer and water columns
            sheet.update_cell(i + 1, 3, beer)  # Update the "beer" column
            sheet.update_cell(i + 1, 4, water_glasses)  # Update the "water" column (glasses)
            return

    # If not found, add a new row
    sheet.append_row([game_id, player_name, beer, water_glasses])

def fetch_games_within_last_48_hours(days=2):
    try:
        # Connect to Google Sheets
        client = connect_to_gsheet()
        sheet = client.open_by_key(SHEET_ID).worksheet("games")
        data = sheet.get_all_values()

        if not data or len(data) <= 1:
            print("❌ No data found in Google Sheets")
            return []

        # Convert raw data to DataFrame
        df = pd.DataFrame(data[1:], columns=data[0])

        # Convert game_finished_at to timezone-aware datetime (UTC)
        df["game_finished_at"] = pd.to_datetime(df["game_finished_at"], errors="coerce", utc=True)

        # Define the cutoff time (48 hours ago) as timezone-aware datetime
        cutoff_time = datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(days=days)

        # Filter games within the last 48 hours using timezone-aware datetime comparison
        df = df[df["game_finished_at"] >= cutoff_time]

        # Convert the filtered DataFrame back to a dictionary list
        games_list = df.to_dict(orient="records")
        print(f"✅ Retrieved {len(games_list)} games from Google Sheets: {games_list}")

        return games_list

    except Exception as e:
        print(f"⚠️ Error fetching games: {e}")
        return []
def fetch_konsum_data_for_game(game_id):
    """Fetch beer and water (glasses) data for a specific game from the 'konsum' sheet."""
    client = connect_to_gsheet()
    sheet = client.open_by_key(SHEET_ID).worksheet("konsum")
    data = sheet.get_all_values()

    if not data or len(data) <= 1:
        print(f"⚠️ No konsum data found for game {game_id}!")
        return {}

    # Convert sheet data to dictionary
    konsum_data = {}
    for row in data[1:]:  # Skip header row
        if row[0] == game_id:
            player_name = row[1]
            beer_count = int(row[2]) if row[2].isdigit() else 0
            water_glasses = int(row[3]) if row[3].isdigit() else 0
            konsum_data[player_name] = {'beer': beer_count, 'water': water_glasses}

    print(f"✅ Konsum data for game {game_id}: {konsum_data}")
    return konsum_data