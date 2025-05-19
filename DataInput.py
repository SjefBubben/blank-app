import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st

# Google Sheets ID
SHEET_ID = "19vqg2lx3hMCEj7MtxkISzsYz0gUaCLgSV11q-YYtXQY"

# Google Sheets authentication setup
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
service_account_info = dict(st.secrets["service_account"])
service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")
creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)

def connect_to_gsheet():
    return gspread.authorize(creds)

def fetch_all_sheets_data():
    try:
        client = connect_to_gsheet()
        spreadsheet = client.open_by_key(SHEET_ID)
        games_sheet = spreadsheet.worksheet("games")
        konsum_sheet = spreadsheet.worksheet("konsum")
        
        games_data = games_sheet.get_all_records()
        konsum_data = konsum_sheet.get_all_records()
        
        games_df = pd.DataFrame(games_data) if games_data else pd.DataFrame()
        konsum_df = pd.DataFrame(konsum_data) if konsum_data else pd.DataFrame()
        
        print(f"✅ Fetched {len(games_df)} games and {len(konsum_df)} konsum records from Sheets")
        return games_df, konsum_df
    except Exception as e:
        print(f"⚠️ Error fetching Sheets data: {e}")
        return pd.DataFrame(), pd.DataFrame()

def save_game_data(game_id, map_name, match_result, score_team1, score_team2, game_finished_at):
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
        st.session_state['games_df'] = pd.concat([existing_games, new_row], ignore_index=True)

def save_konsum_data(game_id, player_name, beer, water_glasses):
    client = connect_to_gsheet()
    sheet = client.open_by_key(SHEET_ID).worksheet("konsum")
    
    existing_konsum = st.session_state.get('konsum_df', pd.DataFrame())
    matching_rows = existing_konsum[(existing_konsum['game_id'] == game_id) & (existing_konsum['player_name'] == player_name)]
    
    if not matching_rows.empty:
        row_index = matching_rows.index[0] + 2
        sheet.update([[beer, water_glasses]], f'C{row_index}:D{row_index}')
        st.session_state['konsum_df'].loc[matching_rows.index, ['beer', 'water']] = [beer, water_glasses]
    else:
        sheet.append_row([game_id, player_name, beer, water_glasses])
        new_row = pd.DataFrame([{
            'game_id': game_id, 'player_name': player_name, 'beer': beer, 'water': water_glasses
        }])
        st.session_state['konsum_df'] = pd.concat([existing_konsum, new_row], ignore_index=True)

def fetch_games_within_last_48_hours(days=2):
    try:
        games_df = st.session_state.get('games_df', pd.DataFrame())
        if games_df.empty:
            print("❌ No games data in cache")
            return []
        
        games_df['game_finished_at'] = pd.to_datetime(games_df['game_finished_at'], errors='coerce')
        cutoff_time = datetime.utcnow() - timedelta(days=days)
        filtered_games = games_df[games_df['game_finished_at'] >= cutoff_time].copy()
        
        filtered_games['score_team1'] = filtered_games['score_team1'].astype(int, errors='ignore')
        filtered_games['score_team2'] = filtered_games['score_team2'].astype(int, errors='ignore')
        
        games_list = filtered_games.to_dict(orient='records')
        print(f"✅ Retrieved {len(games_list)} games from cache")
        return games_list
    except Exception as e:
        print(f"⚠️ Error processing cached games: {e}")
        return []

def fetch_konsum_data_for_game(game_id):
    try:
        konsum_df = st.session_state.get('konsum_df', pd.DataFrame())
        if konsum_df.empty:
            print(f"⚠️ No konsum data in cache for game {game_id}")
            return {}
        
        game_konsum = konsum_df[konsum_df['game_id'] == game_id]
        konsum_data = {
            row['player_name']: {'beer': int(row['beer']) if str(row['beer']).isdigit() else 0,
                                'water': int(row['water']) if str(row['water']).isdigit() else 0}
            for _, row in game_konsum.iterrows()
        }
        
        print(f"✅ Konsum data for game {game_id} from cache: {konsum_data}")
        return konsum_data
    except Exception as e:
        print(f"⚠️ Error processing cached konsum data: {e}")
        return {}