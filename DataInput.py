import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st
import logging
from typing import Tuple, List, Dict

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Constants
SHEET_ID = "19vqg2lx3hMCEj7MtxkISzsYz0gUaCLgSV11q-YYtXQY"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

def connect_to_gsheet() -> gspread.Client:
    """Connect to Google Sheets using Streamlit secrets."""
    try:
        service_account_info = dict(st.secrets["service_account"])
        service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        logging.error(f"Failed to connect to Google Sheets: {e}")
        raise

def fetch_all_sheets_data() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch all data from 'games' and 'konsum' sheets."""
    try:
        client = connect_to_gsheet()
        spreadsheet = client.open_by_key(SHEET_ID)
        
        games_sheet = spreadsheet.worksheet("games")
        games_data = games_sheet.get_all_values()
        games_df = pd.DataFrame(games_data[1:], columns=games_data[0]) if games_data else pd.DataFrame()
        
        konsum_sheet = spreadsheet.worksheet("konsum")
        konsum_data = konsum_sheet.get_all_values()
        konsum_df = pd.DataFrame(konsum_data[1:], columns=konsum_data[0]) if konsum_data else pd.DataFrame()
        
        logging.info(f"Fetched {len(games_df)} games and {len(konsum_df)} konsum records from Sheets")
        return games_df, konsum_df
    except Exception as e:
        logging.error(f"Error fetching Sheets data: {e}")
        return pd.DataFrame(), pd.DataFrame()

def save_game_data(game_id: str, map_name: str, match_result: str, score_team1: int, score_team2: int, game_finished_at: str) -> None:
    """Save game data to Sheets and update cached data."""
    try:
        client = connect_to_gsheet()
        sheet = client.open_by_key(SHEET_ID).worksheet("games")
        
        score_team1 = int(score_team1)
        score_team2 = int(score_team2)
        
        existing_games = st.session_state.get('games_df', pd.DataFrame())
        if not existing_games.empty and game_id not in existing_games['game_id'].values:
            sheet.append_row([game_id, map_name, match_result, score_team1, score_team2, game_finished_at])
            
            new_row = pd.DataFrame([{
                'game_id': game_id, 'map_name': map_name, 'match_result': match_result,
                'score_team1': score_team1, 'score_team2': score_team2, 'game_finished_at': game_finished_at
            }])
            st.session_state['games_df'] = pd.concat([existing_games, new_row], ignore_index=True, copy=False)
            logging.info(f"Saved game {game_id} to Sheets")
    except Exception as e:
        logging.error(f"Error saving game data for {game_id}: {e}")

def save_konsum_data(game_id: str, player_name: str, beer: int, water_glasses: int) -> None:
    """Save konsum data to Sheets and update cached data."""
    try:
        client = connect_to_gsheet()
        sheet = client.open_by_key(SHEET_ID).worksheet("konsum")
        
        existing_konsum = st.session_state.get('konsum_df', pd.DataFrame())
        matching_rows = existing_konsum[(existing_konsum['game_id'] == game_id) & (existing_konsum['player_name'] == player_name)]
        
        if not matching_rows.empty:
            row_index = matching_rows.index[0] + 2  # 1-based indexing + header
            sheet.update_cell(row_index, 3, beer)
            sheet.update_cell(row_index, 4, water_glasses)
            
            st.session_state['konsum_df'].loc[matching_rows.index, ['beer', 'water']] = [beer, water_glasses]
        else:
            sheet.append_row([game_id, player_name, beer, water_glasses])
            
            new_row = pd.DataFrame([{
                'game_id': game_id, 'player_name': player_name, 'beer': beer, 'water': water_glasses
            }])
            st.session_state['konsum_df'] = pd.concat([existing_konsum, new_row], ignore_index=True, copy=False)
        
        logging.info(f"Saved konsum data for {player_name} in game {game_id}")
    except Exception as e:
        logging.error(f"Error saving konsum data for {player_name} in game {game_id}: {e}")

def fetch_games_within_last_48_hours(days: int = 2) -> List[Dict]:
    """Fetch games from cached data within the specified timeframe."""
    try:
        games_df = st.session_state.get('games_df', pd.DataFrame())
        if games_df.empty:
            logging.warning("No games data in cache")
            return []
        
        games_df['game_finished_at'] = pd.to_datetime(games_df['game_finished_at'], format="%Y-%m-%d %H:%M:%S", errors='coerce')
        cutoff_time = datetime.utcnow() - timedelta(days=days)
        filtered_games = games_df[games_df['game_finished_at'] >= cutoff_time].copy()
        
        filtered_games['score_team1'] = pd.to_numeric(filtered_games['score_team1'], errors='coerce').fillna(0).astype(int)
        filtered_games['score_team2'] = pd.to_numeric(filtered_games['score_team2'], errors='coerce').fillna(0).astype(int)
        
        games_list = filtered_games.to_dict(orient='records')
        logging.info(f"Retrieved {len(games_list)} games from cache")
        return games_list
    except Exception as e:
        logging.error(f"Error processing cached games: {e}")
        return []

def fetch_konsum_data_for_game(game_id: str) -> Dict:
    """Fetch konsum data for a specific game from cached data."""
    try:
        konsum_df = st.session_state.get('konsum_df', pd.DataFrame())
        if konsum_df.empty:
            logging.warning(f"No konsum data in cache for game {game_id}")
            return {}
        
        game_konsum = konsum_df[konsum_df['game_id'] == game_id]
        konsum_data = {}
        for _, row in game_konsum.iterrows():
            player_name = row['player_name']
            beer = pd.to_numeric(row['beer'], errors='coerce').fillna(0).astype(int)
            water = pd.to_numeric(row['water'], errors='coerce').fillna(0).astype(int)
            konsum_data[player_name] = {'beer': beer, 'water': water}
        
        logging.info(f"Retrieved konsum data for game {game_id}")
        return konsum_data
    except Exception as e:
        logging.error(f"Error processing cached konsum data for game {game_id}: {e}")
        return {}