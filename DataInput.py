import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st

# Google Sheets ID
SHEET_ID = "19vqg2lx3hMCEj7MtxkISzsYz0gUaCLgSV11q-YYtXQY"

# Google Sheets authentication
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
service_account_info = dict(st.secrets["service_account"])
service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")
creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)

def connect_to_gsheet():
    return gspread.authorize(creds)


def fetch_all_sheets_data():
    """Fetch all data from 'games' and 'konsum' sheets once."""
    try:
        client = connect_to_gsheet()
        spreadsheet = client.open_by_key(SHEET_ID)
        
        # Games sheet
        games_sheet = spreadsheet.worksheet("games")
        games_data = games_sheet.get_all_values()
        games_df = pd.DataFrame(games_data[1:], columns=games_data[0]) if games_data else pd.DataFrame()
        
        # Konsum sheet
        konsum_sheet = spreadsheet.worksheet("konsum")
        konsum_data = konsum_sheet.get_all_values()
        konsum_df = pd.DataFrame(konsum_data[1:], columns=konsum_data[0]) if konsum_data else pd.DataFrame()
        
        return games_df, konsum_df
    except Exception as e:
        print(f"⚠️ Error fetching Sheets data: {e}")
        return pd.DataFrame(), pd.DataFrame()


def save_game_data(game_id, map_name, match_result, score_team1, score_team2, game_finished_at):
    """Save a game to Sheets and update session_state."""
    client = connect_to_gsheet()
    sheet = client.open_by_key(SHEET_ID).worksheet("games")

    existing_games = st.session_state.get('games_df', pd.DataFrame())
    if game_id in existing_games.get('game_id', []):
        return

    sheet.append_row([game_id, map_name, match_result, int(score_team1), int(score_team2), game_finished_at])
    
    new_row = pd.DataFrame([{
        'game_id': game_id,
        'map_name': map_name,
        'match_result': match_result,
        'score_team1': int(score_team1),
        'score_team2': int(score_team2),
        'game_finished_at': game_finished_at
    }])
    st.session_state['games_df'] = pd.concat([existing_games, new_row], ignore_index=True)


def save_konsum_data(konsum_updates):
    """
    konsum_updates: dict of {game_id: {player_name: {"beer": x, "water": y, "ids": [id1, id2]}}}
    Saves all konsum updates to Google Sheets.
    """
    if not konsum_updates:
        return

    client = connect_to_gsheet()
    sheet = client.open_by_key(SHEET_ID).worksheet("konsum")
    existing_konsum = st.session_state.get('konsum_df', pd.DataFrame())
    
    rows_to_append = []
    updated_indices = []

    for game_id, players in konsum_updates.items():
        for player_name, counts in players.items():
            beer = counts["beer"]
            water = counts["water"]
            ids = counts.get("ids", [])
            ids_str = f"({', '.join(map(str, ids))})" if ids else ""

            matching_rows = existing_konsum[
                (existing_konsum['game_id'] == game_id) &
                (existing_konsum['player_name'] == player_name)
            ]
            
            if not matching_rows.empty:
                row_index = matching_rows.index[0] + 2
                updated_indices.append((row_index, beer, water, ids_str))
                existing_konsum.loc[matching_rows.index, ['beer','water','IDs']] = [beer, water, ids_str]
            else:
                rows_to_append.append([game_id, player_name, beer, water, ids_str])
                new_row = pd.DataFrame([{
                    'game_id': game_id,
                    'player_name': player_name,
                    'beer': beer,
                    'water': water,
                    'IDs': ids_str
                }])
                existing_konsum = pd.concat([existing_konsum, new_row], ignore_index=True)

    for row_index, beer, water, ids_str in updated_indices:
        sheet.update(f"C{row_index}:E{row_index}", [[beer, water, ids_str]])

    for row in rows_to_append:
        sheet.append_row(row)

    st.session_state['konsum_df'] = existing_konsum
    print(f"✅ Konsum batch saved: {len(updated_indices)} updates, {len(rows_to_append)} new rows")


def fetch_games_within_last_48_hours(days=2):
    try:
        games_df = st.session_state.get('games_df', pd.DataFrame())
        if games_df.empty:
            return []

        games_df['game_finished_at'] = pd.to_datetime(games_df['game_finished_at'], errors='coerce')
        cutoff = datetime.utcnow() - timedelta(days=days)
        filtered = games_df[games_df['game_finished_at'] >= cutoff].copy()
        filtered['score_team1'] = filtered['score_team1'].astype(int)
        filtered['score_team2'] = filtered['score_team2'].astype(int)
        return filtered.to_dict(orient='records')
    except:
        return []


def fetch_konsum_data_for_game(game_id):
    """Fetch konsum data for a game, including IDs for duplicate prevention."""
    konsum_df = st.session_state.get('konsum_df', pd.DataFrame())
    if konsum_df.empty:
        return {}

    game_konsum = konsum_df[konsum_df['game_id'] == game_id]
    konsum_data = {}

    for _, row in game_konsum.iterrows():
        player_name = row['player_name']
        beer = int(row['beer']) if str(row['beer']).isdigit() else 0
        water = int(row['water']) if str(row['water']).isdigit() else 0
        ids_str = str(row.get('IDs',''))
        if ids_str.startswith("(") and ids_str.endswith(")"):
            ids_list = [int(x.strip()) for x in ids_str[1:-1].split(",") if x.strip().isdigit()]
        else:
            ids_list = []

        konsum_data[player_name] = {'beer': beer, 'water': water, 'ids': ids_list}

    return konsum_data
