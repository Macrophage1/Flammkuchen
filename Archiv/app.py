import streamlit as st
import sqlite3
import pandas as pd
import datetime
import math

DB_NUTZER = "nutzer.db"
DB_ARTIKEL = "artikel.db"
DB_BESTELLUNGEN = "bestellungen.db"

# --- Hilfsfunktionen ---
def get_connection(db_path):
    return sqlite3.connect(db_path, check_same_thread=False)

def lade_benutzer():
    with get_connection(DB_NUTZER) as conn:
        df = pd.read_sql("SELECT name FROM benutzer ORDER BY name", conn)
    return df["name"].tolist()

def lade_artikel():
    with get_connection(DB_ARTIKEL) as conn:
        df = pd.read_sql("SELECT name, preis FROM artikel ORDER BY name", conn)
    return df.set_index("name").to_dict()["preis"]

def speichere_bestellung(benutzer, artikel_dict):
    zeit = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    daten = []
    for name, menge in artikel_dict.items():
        if menge > 0:
            preis = artikel_preise[name]
            gesamt = preis * menge
            daten.append((benutzer, name, menge, preis, gesamt, zeit))

    with get_connection(DB_BESTELLUNGEN) as conn:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT INTO bestellungen (benutzer, artikel, menge, einzelpreis, gesamtpreis, zeitstempel)
            VALUES (?, ?, ?, ?, ?, ?)
        """, daten)
        conn.commit()

def berechne_abholzeit(bestellte_menge):
    now = datetime.datetime.now()
    vor_20_min = now - datetime.timedelta(minutes=20)

    with get_connection(DB_BESTELLUNGEN) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT SUM(menge) FROM bestellungen
            WHERE zeitstempel > ?
        """, (vor_20_min.strftime("%Y-%m-%d %H:%M:%S"),))
        result = cursor.fetchone()
        warteschlange_menge = result[0] if result[0] else 0

    ofenkapazitaet = 8
    backzeit = 5
    vorbereitung = 2

    total = warteschlange_menge + bestellte_menge
    durchgaenge = math.ceil(total / ofenkapazitaet)
    minuten = durchgaenge * backzeit + vorbereitung

    fertig = now + datetime.timedelta(minutes=minuten)
    minute = (fertig.minute // 5 + 1) * 5
    fertig = fertig.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(minutes=minute)

    return fertig.strftime("%H:%M")

# --- Streamlit App ---

st.set_page_config(page_title="Flammkuchen Bestellung", page_icon="🔥", layout="centered")

st.title("🔥 Flammkuchen Bestellung")

# Benutzer auswählen
benutzer_liste = lade_benutzer()
benutzer = st.selectbox("Benutzer auswählen", benutzer_liste)

# Artikel anzeigen
artikel_preise = lade_artikel()
menge_dict = {}
st.subheader("🧾 Artikel wählen")

for name, preis in artikel_preise.items():
    menge = st.number_input(f"{name} ({preis:.2f} €)", min_value=0, max_value=50, step=1, key=name)
    menge_dict[name] = menge

# Bestellung abschließen
if st.button("✅ Bestellung abschließen"):
    gesamt_bestellt = sum(menge_dict.values())
    if gesamt_bestellt == 0:
        st.warning("Bitte mindestens ein Produkt auswählen.")
    else:
        speichere_bestellung(benutzer, menge_dict)
        abholzeit = berechne_abholzeit(gesamt_bestellt)
        st.success(f"Bestellung gespeichert! Abholzeit ca. {abholzeit} Uhr.")
        st.balloons()
