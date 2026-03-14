import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import io
from datetime import datetime, date, timedelta
import time

# ==========================================
# 1. CONFIGURATIE & GOOGLE SHEETS SETUP
# ==========================================
SHEET_NAME = "Skistage_Data"

TABS = {
    "students": "students",
    "evaluations": "evaluations",
    "subjects": "subjects",
    "streaks": "streaks",
    "attendance": "attendance",
    "teachers": "teachers"
}

COLUMN_DEFS = {
    "students": ["voornaam", "achternaam", "klas", "status"],
    "subjects": ["onderwerp"],
    "evaluations": ["datum", "tijdstip", "leraar", "leerling_naam", "klas", "onderwerp", "score", "opmerking"],
    "attendance": ["datum", "leraar", "leerling_naam", "klas", "status"],
    "streaks": ["leraar", "punten", "laatste_datum", "streak"],
    "teachers": ["naam", "pin"]
}

# ==========================================
# 2. STYLING & CSS
# ==========================================
def local_css():
    st.markdown("""
    <style>
    .stApp { background: linear-gradient(to bottom, #e3f2fd, #ffffff); }
    h1, h2, h3 { color: #1565c0; font-family: 'Helvetica', sans-serif; }
    .stButton>button {
        width: 100%; border-radius: 12px; height: 60px;
        background-color: #0277bd; color: white; font-weight: bold; border: none;
        box-shadow: 0px 4px 6px rgba(0,0,0,0.1);
        font-size: 18px;
    }
    .stButton>button:hover { background-color: #01579b; color: white; }
    .streak-card {
        background-color: white; padding: 20px; border-radius: 15px;
        border: 2px solid #ff9800; text-align: center; margin-bottom: 20px;
        box-shadow: 0px 4px 10px rgba(0,0,0,0.05);
    }
    div[data-testid="stForm"] {
        background-color: rgba(255, 255, 255, 0.9); padding: 20px;
        border-radius: 15px; border: 1px solid #bbdefb;
    }
    .student-header {
        color: #0277bd; font-size: 18px; font-weight: bold;
        margin-top: 10px; margin-bottom: 5px; border-bottom: 2px solid #b3e5fc;
    }
    .new-user-box {
        background-color: #d1e7dd; color: #0f5132; padding: 15px; border-radius: 10px; margin-bottom: 15px; border: 1px solid #badbcc;
    }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 3. DATA FUNCTIES (MET CACHING ⚡)
# ==========================================
@st.cache_resource
def get_gspread_client():
    creds_dict = dict(st.secrets["gcp_service_account"])
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

@st.cache_resource
def get_spreadsheet():
    client = get_gspread_client()
    return client.open(SHEET_NAME)

def init_data():
    if 'data_initialized' in st.session_state:
        return

    try:
        sh = get_spreadsheet()
    except gspread.SpreadsheetNotFound:
        st.error(f"Kan Google Sheet '{SHEET_NAME}' niet vinden.")
        st.stop()

    current_worksheets = [ws.title for ws in sh.worksheets()]

    for tab_key, tab_name in TABS.items():
        if tab_name not in current_worksheets:
            ws = sh.add_worksheet(title=tab_name, rows=100, cols=20)
            cols = COLUMN_DEFS.get(tab_key, [])
            if cols:
                ws.update([cols])
            
            if tab_key == "students":
                ws.append_row(["Voorbeeld", "Student", "6A", "Actief"])
            elif tab_key == "subjects":
                for sub in ["Bochten Techniek", "Houding", "Controle", "Inzet"]:
                    ws.append_row([sub])
    
    st.session_state.data_initialized = True

@st.cache_data(ttl=600)
def load_data(key):
    sh = get_spreadsheet()
    ws = sh.worksheet(TABS[key])
    
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    
    expected_cols = COLUMN_DEFS.get(key, [])
    
    if df.empty:
        df = pd.DataFrame(columns=expected_cols)
    else:
        for col in expected_cols:
            if col not in df.columns:
                df[col] = None

    if key == "teachers" and 'pin' in df.columns:
        df['pin'] = df['pin'].astype(str)
        
    return df

def save_data(key, df):
    sh = get_spreadsheet()
    ws = sh.worksheet(TABS[key])
    
    ws.clear()
    
    df_to_save = df.copy()
    for col in df_to_save.columns:
        if pd.api.types.is_datetime64_any_dtype(df_to_save[col]):
             df_to_save[col] = df_to_save[col].astype(str)
        elif df_to_save[col].dtype == 'object':
             df_to_save[col] = df_to_save[col].astype(str)
            
    ws.update([df_to_save.columns.values.tolist()] + df_to_save.values.tolist())
    st.cache_data.clear()

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    return output.getvalue()

def generate_full_report():
    df_eval = load_data("evaluations")
    df_stud = load_data("students")
    df_subj = load_data("subjects")

    if df_stud.empty: return df_eval 

    active_students = df_stud[df_stud['status'] == 'Actief'].copy()
    active_students['display'] = active_students['voornaam'] + " " + active_students['achternaam'] + " (" + active_students['klas'] + ")"

    dates = df_eval['datum'].unique()
    if len(dates) == 0: return df_eval 

    full_rows = []
    for d in dates:
        for _, stud in active_students.iterrows():
            name = stud['display']
            klas = stud['klas']
            for sub in df_subj['onderwerp']:
                full_rows.append({"datum": d, "leerling_naam": name, "klas": klas, "onderwerp": sub})
    
    df_template = pd.DataFrame(full_rows)
    df_merged = pd.merge(df_template, df_eval, on=["datum", "leerling_naam", "onderwerp"], how="left", suffixes=("", "_old"))

    if 'klas_old' in df_merged.columns:
        df_merged['klas'] = df_merged['klas'].fillna(df_merged['klas_old'])
        df_merged.drop(columns=['klas_old'], inplace=True)

    df_merged['score'] = df_merged['score'].fillna("Geen deelname")
    df_merged['leraar'] = df_merged['leraar'].fillna("Systeem")
    df_merged['tijdstip'] = df_merged['tijdstip'].fillna("-")
    df_merged['opmerking'] = df_merged['opmerking'].fillna("-")

    return df_merged.sort_values(by=["datum", "klas", "leerling_naam", "onderwerp"])

# ==========================================
# 4. GAMIFICATION LOGICA
# ==========================================
def update_streak_and_points(leraar_naam, evaluatie_datum, reeds_geëvalueerd):
    # Voorkom dubbele punten op dezelfde dag
    if reeds_geëvalueerd:
        return "Leerlingen toegevoegd! (Je had al punten ontvangen voor deze datum)."

    df = load_data("streaks")
    nu = datetime.now()
    vandaag = nu.date()
    uur = nu.hour
    
    # Check of de leraar te laat is (datum ligt in het verleden)
    is_te_laat = evaluatie_datum < vandaag
    
    if is_te_laat:
        basis = 5 # Troostprijs voor late evaluaties
    else:
        # Normale puntenverdeling voor evaluaties op de dag zelf
        if uur < 17: basis = 100
        elif uur < 19: basis = 75
        elif uur < 21: basis = 50
        elif uur < 23: basis = 25
        else: basis = 10

    bericht = ""
    
    if df.empty or leraar_naam not in df['leraar'].values:
        laatste_d = str(vandaag) if not is_te_laat else "2000-01-01"
        nieuwe_rij = {"leraar": leraar_naam, "punten": basis, "laatste_datum": laatste_d, "streak": 1 if not is_te_laat else 0}
        df = pd.concat([df, pd.DataFrame([nieuwe_rij])], ignore_index=True)
        bericht = f"🚀 Eerste evaluatie! +{basis} punten."
    else:
        idx = df[df['leraar'] == leraar_naam].index[0]
        laatste_datum_str = str(df.at[idx, 'laatste_datum'])
        try:
            laatste_datum = datetime.strptime(laatste_datum_str, '%Y-%m-%d').date()
        except:
            laatste_datum = date(2000, 1, 1)

        huidige_streak = int(df.at[idx, 'streak'])
        
        if is_te_laat:
            df.at[idx, 'punten'] += basis
            bericht = f"Late evaluatie opgeslagen! +{basis} punten."
        else:
            if laatste_datum == vandaag - timedelta(days=1):
                nieuwe_streak = min(huidige_streak + 1, 7)
                df.at[idx, 'streak'] = nieuwe_streak
                df.at[idx, 'laatste_datum'] = str(vandaag)
                totaal = basis * nieuwe_streak
                df.at[idx, 'punten'] += totaal
                bericht = f"🔥 STREAK DAG {nieuwe_streak}! +{totaal} punten!"
            elif laatste_datum == vandaag:
                # Voor de veiligheid, mocht reeds_geëvalueerd falen
                bericht = "Punten waren al toegekend voor vandaag."
            else:
                df.at[idx, 'streak'] = 1
                df.at[idx, 'laatste_datum'] = str(vandaag)
                df.at[idx, 'punten'] += basis
                bericht = f"Nieuwe start: +{basis} punten."

    save_data("streaks", df)
    return bericht

# ==========================================
# 5. DE APPLICATIE START
# ==========================================
st.set_page_config(page_title="Skistage App", page_icon="🎿", layout="centered")
local_css()

try:
    init_data()
except Exception as e:
    st.error("Er ging iets mis met de Google Sheets verbinding.")
    st.error(f"Foutmelding: {e}")
    st.stop()

st.sidebar.image("https://img.icons8.com/color/96/skiing.png", width=60)
st.sidebar.title("Navigatie")
page = st.sidebar.radio("Ga naar:", ["⛷️ Skileraar Omgeving", "⚙️ Beheerder Login"])

# ------------------------------------------
# PAGINA: SKILERAAR
# ------------------------------------------
if page == "⛷️ Skileraar Omgeving":
    st.title("⛷️ Skileraar Dashboard")
    
    if 'ingelogd' not in st.session_state: st.session_state.ingelogd = False
    if 'leraar_naam' not in st.session_state: st.session_state.leraar_naam = ""
    if 'login_stap' not in st.session_state: st.session_state.login_stap = 1
    if 'temp_naam' not in st.session_state: st.session_state.temp_naam = ""
    if 'is_nieuwe_user' not in st.session_state: st.session_state.is_nieuwe_user = False

    if not st.session_state.ingelogd:
        
        if st.session_state.login_stap == 1:
            st.markdown("### 👋 Stap 1: Wie ben je?")
            naam_input = st.text_input("Typ je voornaam:", placeholder="Bijv. Meester Jan")
            st.write("")
            if st.button("🔎 Verder naar Pincode"):
                if naam_input.strip():
                    df_t = load_data("teachers")
                    naam_clean = naam_input.strip()
                    bestaande_user = pd.DataFrame()
                    if not df_t.empty:
                        bestaande_user = df_t[df_t['naam'].str.lower() == naam_clean.lower()]
                    
                    st.session_state.temp_naam = naam_clean
                    st.session_state.is_nieuwe_user = bestaande_user.empty
                    
                    if not bestaande_user.empty:
                        st.session_state.temp_naam = bestaande_user['naam'].values[0]
                        
                    st.session_state.login_stap = 2
                    st.rerun()
                else:
                    st.warning("Vul eerst een naam in.")

        elif st.session_state.login_stap == 2:
            st.markdown(f"### 👤 Hallo **{st.session_state.temp_naam}**!")
            
            if st.session_state.is_nieuwe_user:
                st.info("🆕 Je bent nieuw! Kies een pincode.")
                new_pin = st.text_input("Kies PIN (4 cijfers):", type="password", max_chars=4, key="pin_new")
                if st.button("✨ Account Maken & Starten"):
                    if len(new_pin) == 4 and new_pin.isdigit():
                        df_t = load_data("teachers")
                        new_row = pd.DataFrame([{"naam": st.session_state.temp_naam, "pin": str(new_pin)}])
                        df_t = pd.concat([df_t, new_row], ignore_index=True)
                        save_data("teachers", df_t)
                        st.session_state.leraar_naam = st.session_state.temp_naam
                        st.session_state.ingelogd = True
                        st.success("Account aangemaakt!")
                        st.rerun()
                    else: st.error("PIN moet 4 cijfers zijn.")
            else:
                st.write("Vul je pincode in om verder te gaan.")
                pin_check = st.text_input("PIN:", type="password", max_chars=4, key="pin_check")
                if st.button("🚀 Inloggen"):
                    df_t = load_data("teachers")
                    correct_pin = df_t[df_t['naam'] == st.session_state.temp_naam]['pin'].values[0]
                    if str(pin_check) == str(correct_pin):
                        st.session_state.leraar_naam = st.session_state.temp_naam
                        st.session_state.ingelogd = True
                        st.rerun()
                    else: st.error("Foute pincode.")
            
            st.write("---")
            if st.button("⬅️ Terug", key="back_btn"):
                st.session_state.login_stap = 1
                st.rerun()

    else:
        df_streaks = load_data("streaks")
        pts, strk = 0, 0
        if not df_streaks.empty and st.session_state.leraar_naam in df_streaks['leraar'].values:
            user_data = df_streaks[df_streaks['leraar'] == st.session_state.leraar_naam]
            pts = user_data['punten'].values[0]
            strk = user_data['streak'].values[0]
        
        # Eigen scorekaart
        st.markdown(f"""
        <div class="streak-card">
            <h3 style="margin:0; color:#e65100;">{st.session_state.leraar_naam}</h3>
            <div style="font-size: 28px; margin-top:10px;">🔥 <b>{strk}/7</b> Dagen | 🏆 <b>{pts}</b> Ptn</div>
        </div>
        """, unsafe_allow_html=True)
        
        # --- NIEUW: LEADERBOARD VOOR LERAREN ---
        with st.expander("🏆 Bekijk het Leaderboard"):
            if not df_streaks.empty:
                df_leader = df_streaks[['leraar', 'punten', 'streak']].sort_values('punten', ascending=False).reset_index(drop=True)
                df_leader.index += 1 # Laat de index beginnen bij 1 in plaats van 0 voor de ranglijst
                st.dataframe(df_leader, use_container_width=True)
            else:
                st.info("Nog geen scores beschikbaar.")
        # ---------------------------------------
        
        if st.button("🔄 Uitloggen", key="logout_btn"):
            st.session_state.ingelogd = False
            st.session_state.login_stap = 1
            st.rerun()

        st.divider()

        df_stud = load_data("students")
        df_subj = load_data("subjects")
        df_eval = load_data("evaluations")
        
        if df_stud.empty:
            st.warning("Nog geen leerlingen in het systeem.")
        else:
            # --- DATUM KIEZEN ---
            st.subheader("📅 Evaluatie Datum")
            gekozen_datum = st.date_input("Voor welke dag wil je de leerlingen evalueren?", value=date.today(), max_value=date.today())
            gekozen_datum_str = str(gekozen_datum)
            st.write("---")
            
            actieve_lln = df_stud[df_stud['status'] == 'Actief'].copy()
            actieve_lln['display'] = actieve_lln['voornaam'] + " " + actieve_lln['achternaam'] + " (" + actieve_lln['klas'] + ")"
            
            reeds_gedaan = pd.DataFrame()
            if not df_eval.empty:
                reeds_gedaan = df_eval[
                    (df_eval['datum'] == gekozen_datum_str) & 
                    (df_eval['leraar'] == st.session_state.leraar_naam)
                ]
            
            # Controleren of de leraar al eerder opsloeg voor deze datum
            heeft_al_geëvalueerd = not reeds_gedaan.empty
            
            namen_gedaan = []
            if not reeds_gedaan.empty:
                namen_gedaan = reeds_gedaan['leerling_naam'].unique().tolist()
            
            beschikbare_lln = actieve_lln[~actieve_lln['display'].isin(namen_gedaan)]
            lln_lijst = sorted(beschikbare_lln['display'].tolist())
            
            st.subheader(f"🔍 Wie wil je evalueren voor {gekozen_datum.strftime('%d-%m-%Y')}?")
            
            if not lln_lijst:
                st.success("🎉 Je hebt iedereen al geëvalueerd voor deze dag!")
            else:
                gekozen = st.multiselect("Nog te doen:", lln_lijst)

                if gekozen:
                    with st.form("evaluatie_form"):
                        st.write("Vul de scores in (0-10):")
                        opslag = {}
                        for leerling_str in gekozen:
                            st.markdown(f"<div class='student-header'>👤 {leerling_str}</div>", unsafe_allow_html=True)
                            opslag[leerling_str] = {}
                            if not df_subj.empty:
                                for vak in df_subj['onderwerp'].tolist():
                                    opslag[leerling_str][vak] = st.slider(f"{vak}", 0, 10, 5, key=f"{leerling_str}_{vak}")
                            opslag[leerling_str]["opmerking"] = st.text_input(f"Opmerking", key=f"opm_{leerling_str}")
                        
                        st.write("")
                        if st.form_submit_button("✅ Opslaan"):
                            tijd_str = datetime.now().strftime("%H:%M")
                            nieuwe_data = []
                            for l_naam, resultaten in opslag.items():
                                try: klas_val = l_naam.split('(')[-1].replace(')', '')
                                except: klas_val = "Onbekend"
                                commentaar = resultaten.pop("opmerking")
                                for vak, punt in resultaten.items():
                                    nieuwe_data.append({
                                        "datum": gekozen_datum_str,
                                        "tijdstip": tijd_str,
                                        "leraar": st.session_state.leraar_naam,
                                        "leerling_naam": l_naam,
                                        "klas": klas_val,
                                        "onderwerp": vak,
                                        "score": punt,
                                        "opmerking": commentaar
                                    })
                            
                            df_eval = pd.concat([df_eval, pd.DataFrame(nieuwe_data)], ignore_index=True)
                            save_data("evaluations", df_eval)
                            
                            # Doorgeven aan de gamification of ze al punten hebben gekregen!
                            msg = update_streak_and_points(st.session_state.leraar_naam, gekozen_datum, heeft_al_geëvalueerd)
                            
                            st.balloons()
                            st.success(msg)
                            st.rerun()

# ------------------------------------------
# PAGINA: BEHEERDER
# ------------------------------------------
elif page == "⚙️ Beheerder Login":
    st.title("⚙️ Beheerder Dashboard")
    wachtwoord = st.text_input("Wachtwoord:", type="password")
    
    if wachtwoord == "Westmalle2650":
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["👨‍🏫 Leraren", "👥 Leerlingen", "📚 Onderwerpen", "🏆 Leaderboard", "💾 Export"])
        
        with tab1:
            st.subheader("Leraren")
            df_t = load_data("teachers")
            if not df_t.empty:
                to_rem = st.multiselect("Verwijder leraar:", df_t['naam'].tolist())
                if st.button("Verwijder", key="del_teach") and to_rem:
                    df_t = df_t[~df_t['naam'].isin(to_rem)]
                    save_data("teachers", df_t)
                    st.rerun()
                st.dataframe(df_t)
            else: st.info("Geen leraren.")

        with tab2:
            st.subheader("Leerlingen")
            df_s = load_data("students")
            with st.expander("➕ Bulk Toevoegen"):
                bulk = st.text_area("Lijst (Voornaam, Achternaam, Klas):", placeholder="Jan, Jansen, 6A")
                if st.button("Toevoegen", key="add_stud"):
                    lijst = []
                    for r in bulk.strip().split('\n'):
                        d = r.split(',')
                        if len(d) >= 3: lijst.append({"voornaam": d[0].strip(), "achternaam": d[1].strip(), "klas": d[2].strip(), "status": "Actief"})
                    if lijst:
                        df_s = pd.concat([df_s, pd.DataFrame(lijst)], ignore_index=True)
                        save_data("students", df_s)
                        st.success("Toegevoegd!")
                        st.rerun()
            with st.expander("🗑️ Verwijderen"):
                if not df_s.empty:
                    df_s['display'] = df_s['voornaam'] + " " + df_s['achternaam']
                    kies = st.multiselect("Kies:", df_s['display'].tolist())
                    if st.button("Verwijder", key="del_stud") and kies:
                        df_s = df_s[~df_s['display'].isin(kies)].drop(columns=['display'])
                        save_data("students", df_s)
                        st.rerun()
            st.dataframe(df_s)

        with tab3:
            st.subheader("Onderwerpen")
            df_sub = load_data("subjects")
            c1, c2 = st.columns([3, 1])
            nw = c1.text_input("Nieuw:")
            if c2.button("Add", key="add_sub") and nw:
                df_sub = pd.concat([df_sub, pd.DataFrame({"onderwerp": [nw]})], ignore_index=True)
                save_data("subjects", df_sub)
                st.rerun()
            if not df_sub.empty:
                rem = st.multiselect("Verwijder:", df_sub['onderwerp'].tolist())
                if st.button("Del", key="del_sub") and rem:
                    df_sub = df_sub[~df_sub['onderwerp'].isin(rem)]
                    save_data("subjects", df_sub)
                    st.rerun()
            st.table(df_sub)

        with tab4:
            st.subheader("🏆 Leaderboard & Punten Beheer")
            st.write("Pas de punten of streaks direct in de tabel aan en klik op opslaan.")
            
            df_str = load_data("streaks")
            
            if not df_str.empty:
                # We sorteren de lijst zodat de koploper bovenaan staat
                df_str_sorted = df_str.sort_values('punten', ascending=False).reset_index(drop=True)
                
                # st.data_editor maakt de tabel interactief!
                edited_df = st.data_editor(
                    df_str_sorted, 
                    use_container_width=True,
                    key="streak_editor",
                    hide_index=True # Zorgt voor een nettere weergave zonder rij-nummers
                )
                
                if st.button("💾 Wijzigingen Opslaan", key="save_streaks"):
                    # Als de beheerder op opslaan klikt, sturen we de bewerkte tabel naar de sheet
                    save_data("streaks", edited_df)
                    st.success("De punten en streaks zijn succesvol bijgewerkt!")
                    st.rerun()
            else: 
                st.info("Nog geen gamification data beschikbaar.")

        with tab5:
            st.subheader("Downloads (Excel)")
            c1, c2 = st.columns(2)
            with c1:
                df_rep = generate_full_report()
                st.download_button("📊 Evaluaties (.xlsx)", to_excel(df_rep), "evaluaties.xlsx", key="dl_ev")
            with c2:
                df_att = load_data("attendance")
                st.download_button("📝 Aanwezigheden (.xlsx)", to_excel(df_att), "aanw.xlsx", key="dl_att")
    
    elif wachtwoord: st.error("Fout wachtwoord")
