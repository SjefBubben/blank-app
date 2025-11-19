# main.py - Bubberne Gaming 🍺 FULLY FIXED + ALL ORIGINAL FEATURES
import streamlit as st
import requests
import base64
import json
import pandas as pd
import plotly.express as px
import threading
from supabase import create_client
from operator import itemgetter
from datetime import datetime, timedelta
from io import StringIO

# ========================= SECRETS & CLIENTS =========================
leetify_token = st.secrets["leetify"]["api_token"]
discord_webhook = st.secrets["discord"]["webhook"]

SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["key"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Google Sheets setup
SHEET_ID = "19vqg2lx3hMCEj7MtxkISzsYz0gUaCLgSV11q-YYtXQY"
from google.oauth2.service_account import Credentials
import gspread

service_account_info = dict(st.secrets["service_account"])
service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")
creds = Credentials.from_service_account_info(service_account_info, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
gsheet = gspread.authorize(creds)

# ========================= PLAYER MAPPING =========================
NAME_MAPPING = {
    "JimmyJimbob": "Jepprizz", "Jimmy": "Jepprizz", "Kåre": "Torgrizz", "Kaare": "Torgrizz",
    "Fakeface": "Birkle", "Killthem26": "Birkle", "Killbirk": "Birkle",
    "Lars Olaf": "Tobrizz", "tobbelobben": "Tobrizz",
    "Bøghild": "Borgle", "Nish": "Sandrizz", "Nishinosan": "Sandrizz",
    "Zohan": "Jorizz", "johlyn": "Jorizz"
}
ALLOWED_PLAYERS = set(NAME_MAPPING.values())

# ========================= GOOGLE SHEETS HELPERS =========================
def fetch_all_sheets_data():
    try:
        sh = gsheet.open_by_key(SHEET_ID)
        games = sh.worksheet("games").get_all_values()
        konsum = sh.worksheet("konsum").get_all_values()
        games_df = pd.DataFrame(games[1:], columns=games[0]) if games else pd.DataFrame()
        konsum_df = pd.DataFrame(konsum[1:], columns=konsum[0]) if konsum else pd.DataFrame()
        return games_df, konsum_df
    except Exception as e:
        st.error(f"Sheets error: {e}")
        return pd.DataFrame(), pd.DataFrame()

def save_game_data(game_id, map_name, match_result, s1, s2, finished_at):
    gsheet.open_by_key(SHEET_ID).worksheet("games").append_row([game_id, map_name, match_result, int(s1), int(s2), finished_at])

def save_konsum_batch(batch):
    if not batch:
        return
    sheet = gsheet.open_by_key(SHEET_ID).worksheet("konsum")
    rows = []
    for gid, players in batch.items():
        for p, d in players.items():
            ids_str = ",".join(map(str, d.get("ids", [])))
            rows.append([gid, p, d["beer"], d["water"], ids_str])
    sheet.append_rows(rows)

# ========================= SUPABASE → SHEETS SYNC (NOW WORKS!) =========================
def fetch_supabase_konsum():
    try:
        data = supabase.table("entries").select("*").execute().data
        df = pd.DataFrame(data)
        if df.empty:
            return df
        df['datetime'] = pd.to_datetime(df['datetime'], utc=True)
        df.rename(columns={'name': 'raw_name'}, inplace=True)
        return df
    except Exception as e:
        st.warning(f"Supabase fetch error: {e}")
        return pd.DataFrame()

def sync_supabase_to_sheets():
    sup_df = fetch_supabase_konsum()
    if sup_df.empty:
        return 0

    games_df = st.session_state.games_df.copy()
    if games_df.empty:
        return 0

    games_df['game_finished_at'] = pd.to_datetime(games_df['game_finished_at'], utc=True)
    games_df = games_df.sort_values('game_finished_at')

    def map_drink(x):
        if not isinstance(x, str): return None
        l = x.lower()
        if any(w in l for w in ["beer", "øl", "pils"]): return "beer"
        if any(w in l for w in ["water", "vann"]): return "water"
        return None

    sup_df['type'] = sup_df['bgdata'].apply(map_drink)
    sup_df = sup_df.dropna(subset=['type'])
    sup_df['player'] = sup_df['raw_name'].map(NAME_MAPPING).fillna(sup_df['raw_name'])

    batch = {}
    processed = 0

    for _, row in sup_df.iterrows():
        ts = row['datetime']
        player = row['player']
        drink = row['type']
        eid = row['id']

        past = games_df[games_df['game_finished_at'] <= ts]
        if past.empty:
            continue
        game = past.iloc[-1]
        if ts - game['game_finished_at'] > timedelta(hours=72):
            continue

        gid = game['game_id']
        batch.setdefault(gid, {})
        batch[gid].setdefault(player, {"beer": 0, "water": 0, "ids": []})
        if eid not in batch[gid][player]["ids"]:
            batch[gid][player][drink] += 1
            batch[gid][player]["ids"].append(eid)
            processed += 1

    if batch:
        save_konsum_batch(batch)
        # Refresh konsum cache
        _, st.session_state.konsum_df = fetch_all_sheets_data()

    return processed

# ========================= LEETIFY HELPERS =========================
def fetch_new_games(days=7):
    url = "https://api.cs-prod.leetify.com/api/v2/games/history"
    headers = {"Authorization": f"Bearer {leetify_token}"}
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    filters = {"currentPeriod": {"start": start.isoformat()+"Z", "end": end.isoformat()+"Z", "count": 50}}

    try:
        data = requests.get(url, headers=headers, params={"filters": json.dumps(filters)}).json()
    except:
        return []

    existing = set(st.session_state.games_df['game_id'].astype(str).tolist())
    new = []

    for g in data.get("games", []):
        gid = g.get("id")
        if not gid or gid in existing:
            continue
        finished = datetime.strptime(g["finishedAt"], "%Y-%m-%dT%H:%M:%S.%fZ")  # UTC!
        score = g.get("score", [0,0])
        new.append({
            "game_id": gid,
            "map_name": g.get("mapName", "Unknown"),
            "match_result": g.get("playerStats", {}).get("matchResult", "Unknown"),
            "score1": score[0], "score2": score[1],
            "finished_at": finished.strftime("%Y-%m-%d %H:%M:%S")
        })

    for g in new:
        save_game_data(g["game_id"], g["map_name"], g["match_result"], g["score1"], g["score2"], g["finished_at"])
        existing.add(g["game_id"])

    return new

def fetch_game_details(gid):
    try:
        return requests.get(f"https://api.cs-prod.leetify.com/api/games/{gid}").json()
    except:
        return {}

# ========================= SESSION & REFRESH =========================
def init():
    if "init" not in st.session_state:
        g, k = fetch_all_sheets_data()
        st.session_state.games_df = g
        st.session_state.konsum_df = k
        st.session_state.days = 7
        st.session_state.init = True

def full_refresh():
    with st.spinner("Henter nye kamper og synkroniserer øl..."):
        fetch_new_games(st.session_state.days)
        g, k = fetch_all_sheets_data()
        st.session_state.games_df = g
        st.session_state.konsum_df = k
        synced = sync_supabase_to_sheets()
        st.success(f"Full refresh ferdig! {synced} nye øl synkronisert 🍺")

init()

# ========================= UI HEADER =========================
img = base64.b64encode(open("bubblogo2.png", "rb").read()).decode()
st.markdown(f'<div style="text-align:center"><img src="data:image/png;base64,{img}" width="80"><h1>Bubberne Gaming</h1></div>', unsafe_allow_html=True)

st.sidebar.title("Navigation")
page = st.sidebar.radio("Gå til", ["🏠 Home", "🍺 Konsum", "📊 Stats", "🚽 Motivation"])

c1, c2 = st.sidebar.columns(2)
with c1:
    st.session_state.days = st.number_input("Dager tilbake", 1, 30, st.session_state.days)
with c2:
    if st.button("🔄 Refresh Alt"):
        full_refresh()

if st.sidebar.button("🍺 Force Sync Supabase Øl"):
    synced = sync_supabase_to_sheets()
    st.success(f"Synkronisert {synced} nye øl fra Supabase! 🍺")

# Recent games 
games_list = []
if not st.session_state.games_df.empty:
    df = st.session_state.games_df.copy()

    # THIS IS THE FIX: coerce errors instead of crashing
    df['game_finished_at'] = pd.to_datetime(df['game_finished_at'], utc=True, errors='coerce')

    # Drop rows where date parsing failed (old broken data)
    df = df.dropna(subset=['game_finished_at'])

    cutoff = datetime.utcnow() - timedelta(days=st.session_state.days)
    recent = df[df['game_finished_at'] >= cutoff].sort_values('game_finished_at', ascending=False)
    games_list = recent.to_dict('records')

# ========================= HOME PAGE (your beautiful awards) =========================
def home_page():
    if not games_list:
        st.warning("Ingen kamper funnet.")
        return

    options = [f"{g['map_name']} ({pd.to_datetime(g['game_finished_at']).strftime('%d.%m.%y %H:%M')}) - {g['game_id']}" for g in games_list]
    sel = st.selectbox("Velg kamp", options)
    gid = sel.split(" - ")[-1]
    game = next(g for g in games_list if g["game_id"] == gid)
    details = fetch_game_details(gid)

    if not details:
        st.error("Klarte ikke hente kampdetaljer.")
        return

    players = [
        {"name": NAME_MAPPING.get(p["name"], p["name"]), "reactionTime": p.get("reactionTime", 99),
         "tradeKillAttemptsPercentage": p.get("tradeKillAttemptsPercentage", 0),
         "utilityOnDeathAvg": p.get("utilityOnDeathAvg", 0),
         "hltvRating": p.get("hltvRating", 0)}
        for p in details.get("playerStats", [])
        if NAME_MAPPING.get(p["name"], p["name"]) in ALLOWED_PLAYERS
    ]

    if not players:
        st.info("Ingen Bubber-spillere i denne kampen.")
        return

    players.sort(key=itemgetter("reactionTime"))
    min_rt = min(p["reactionTime"] for p in players)
    max_rt = max(p["reactionTime"] for p in players)
    best_trade = max(p["tradeKillAttemptsPercentage"]*100 for p in players)
    worst_trade = min(p["tradeKillAttemptsPercentage"]*100 for p in players)
    worst_util = max(p.get("utilityOnDeathAvg", 0) for p in players)
    best_hltv = max(p.get("hltvRating", 0) for p in players)

    top_rt = [p for p in players if p["reactionTime"] == min_rt]
    low_rt = [p for p in players if p["reactionTime"] == max_rt]
    best_t = [p for p in players if p["tradeKillAttemptsPercentage"]*100 == best_trade]
    worst_t = [p for p in players if p["tradeKillAttemptsPercentage"]*100 == worst_trade]
    worst_u = [p for p in players if p.get("utilityOnDeathAvg",0) == worst_util]
    best_h = [p for p in players if p.get("hltvRating",0) == best_hltv]

    col1, col2 = st.columns(2)
    col3, col4 = st.columns(2)

    with col1:
        st.markdown(f"""
            <div style="padding: 15px; background-color: #388E3C; color: white; border-radius: 10px; text-align: center; border: 1px solid black; margin: 5px;">
                <h3>🔥 Reaction Time</h3>
                <h4>💪 Gooner: {', '.join(p['name'] for p in top_rt)} ({min_rt}s)</h4>
                <h4>🍺 Pils-bitch: {', '.join(p['name'] for p in low_rt)} ({max_rt}s)</h4>
            </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
            <div style="padding: 15px; background-color: #1976D2; color: white; border-radius: 10px; text-align: center; border: 1px solid black; margin: 5px;">
                <h3>🎯 Trade Kill Attempts</h3>
                <h4>✅ Rizzler: {', '.join(p['name'] for p in best_t)} ({best_trade:.1f}%)</h4>
                <h4>❌ Baiterbot: {', '.join(p['name'] for p in worst_t)} ({worst_trade:.1f}%)</h4>
            </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
            <div style="padding: 15px; background-color: #D32F2F; color: white; border-radius: 10px; text-align: center; border: 1px solid black; margin: 5px;">
                <h3>💣 Utility on Death</h3>
                <h4>🔥 McRizzler: {', '.join(p['name'] for p in worst_u)} ({worst_util:.2f})</h4>
            </div>
        """, unsafe_allow_html=True)

    with col4:
        st.markdown(f"""
            <div style="padding: 15px; background-color: #301934; color: white; border-radius: 10px; text-align: center; border: 1px solid black; margin: 5px;">
                <h3>🏆 Best HLTV Rating</h3>
                <h4>⭐ OhioMaster: {', '.join(p['name'] for p in best_h)} ({best_hltv:.2f})</h4>
            </div>
        """, unsafe_allow_html=True)

# ========================= KONSUM PAGE =========================
def konsum_page():
    st.header("🍺 BubbeData")
    all_players = set()
    for g in games_list:
        det = fetch_game_details(g["game_id"])
        for p in det.get("playerStats", []):
            n = NAME_MAPPING.get(p["name"], p["name"])
            if n in ALLOWED_PLAYERS:
                all_players.add(n)

    selected = st.multiselect("Filter spillere", sorted(all_players), default=[])

    for game in games_list:
        det = fetch_game_details(game["game_id"])
        konsum_rows = st.session_state.konsum_df[st.session_state.konsum_df["game_id"] == game["game_id"]]
        konsum_dict = {r["player_name"]: {"beer": int(r.get("beer") or 0), "water": int(r.get("water") or 0)} 
                      for _, r in konsum_rows.iterrows()}

        dt = pd.to_datetime(game["game_finished_at"]).strftime("%d.%m.%y %H:%M")
        label = f"🗺️ {game['map_name']} | {game['match_result']} ({game.get('score1',0)}:{game.get('score2',0)}) | {dt}"
        
        with st.expander(label, expanded=False):
            rows = []
            for p in det.get("playerStats", []):
                name = NAME_MAPPING.get(p["name"], p["name"])
                if name not in ALLOWED_PLAYERS or (selected and name not in selected):
                    continue
                rows.append({
                    "Player": name,
                    "Beer": konsum_dict.get(name, {}).get("beer", 0),
                    "Water": konsum_dict.get(name, {}).get("water", 0),
                    "K/D": round(p.get("kdRatio", 0), 2),
                    "ADR": round(p.get("dpr", 0), 2),
                    "HLTV": round(p.get("hltvRating", 0), 2),
                })
            if rows:
                st.dataframe(pd.DataFrame(rows))
            else:
                st.info("Ingen konsum registrert ennå.")

# ========================= STATS PAGE (with BubbeRating) =========================
STAT_MAP = {
    "K/D Ratio": "kdRatio", "ADR": "dpr", "HLTV Rating": "hltvRating",
    "Reaction Time": "reactionTime", "TradeAttempts": "tradeKillAttemptsPercentage",
}

def load_stats():
    rows = []
    for g in games_list:
        det = fetch_game_details(g["game_id"])
        konsum_dict = {r["player_name"]: {"beer": int(r.get("beer") or 0), "water": int(r.get("water") or 0)}
                      for _, r in st.session_state.konsum_df[st.session_state.konsum_df["game_id"] == g["game_id"]].iterrows()}
        label = f"{g['map_name']} ({pd.to_datetime(g['game_finished_at']).strftime('%d.%m.%y %H:%M')})"

        for p in det.get("playerStats", []):
            name = NAME_MAPPING.get(p["name"], p["name"])
            if name not in ALLOWED_PLAYERS:
                continue
            row = {"Game": label, "Player": name,
                   "Beer": konsum_dict.get(name, {}).get("beer", 0),
                   "Water": konsum_dict.get(name, {}).get("water", 0)}
            for disp, key in STAT_MAP.items():
                val = p.get(key, 0)
                if key == "tradeKillAttemptsPercentage":
                    val *= 100
                row[disp] = val
            rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return None, None

    grouped = df.groupby("Player").agg({
        "Beer": "sum", "Water": "sum", "K/D Ratio": "mean", "ADR": "mean",
        "HLTV Rating": "mean", "Reaction Time": "mean", "TradeAttempts": "mean"
    }).reset_index()

    games_count = df["Game"].nunique()
    grouped["BubbeRating"] = (
        grouped["HLTV Rating"] +
        grouped["HLTV Rating"] * ((grouped["Beer"] / max(games_count,1)) * 0.9) +
        (grouped["TradeAttempts"] / 100) * 0.5
    ).round(2)

    return df, grouped

def stats_page():
    st.header("📊 Stats")
    with st.spinner("Laster stats..."):
        df, grouped = load_stats()
        if df is None:
            st.warning("Ingen data.")
            return

        # Top 3 table
        def top3(col, asc=False, fmt=".2f"):
            top = grouped.sort_values(col, ascending=asc).head(3)
            return [f"{r.Player} ({r[col]:{fmt}})" for _, r in top.iterrows()] + ["-"]*3

        table = {
            "HLTV Rating": top3("HLTV Rating", False),
            "K/D Ratio": top3("K/D Ratio", False),
            "Reaction Time": top3("Reaction Time", True),
            "Trade (%)": top3("TradeAttempts", False, ".1f"),
            "Beer": top3("Beer", False, ".0f"),
            "Water": top3("Water", False, ".0f"),
            "BubbeRating": top3("BubbeRating", False),
        }
        st.markdown("### 🏆 Topp 3 Gjennom Alle Kamper")
        st.dataframe(pd.DataFrame(table, index=["1.", "2.", "3."]), use_container_width=True)

        stat = st.selectbox("Velg stat", list(STAT_MAP.keys()) + ["Beer", "Water", "BubbeRating"])
        if stat == "BubbeRating":
            fig = px.bar(grouped, x="Player", y="BubbeRating", title="BubbeRating")
        else:
            fig = px.bar(df, x="Player", y=stat, color="Game", barmode="group", title=stat)
        st.plotly_chart(fig, use_container_width=True)

        csv = df.to_csv(index=False)
        st.download_button("Last ned rådata (CSV)", csv, "bubber_stats.csv", "text/csv")

# ========================= MOTIVATION =========================
def motivation_page():
    st.header("Get skibid going!")
    st.video("https://www.youtube.com/watch?v=6dMjCa0nqK0")

# ========================= ROUTING =========================
if page == "🏠 Home":
    home_page()
elif page == "🍺 Konsum":
    konsum_page()
elif page == "📊 Stats":
    stats_page()
elif page == "🚽 Motivation":
    motivation_page()