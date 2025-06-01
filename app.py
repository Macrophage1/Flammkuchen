import streamlit as st
import sqlite3
import datetime
import pandas as pd
import math
import time

DB_NUTZER = "nutzer.db"
DB_ARTIKEL = "artikel.db"
DB_BESTELLUNG = "bestellungen.db"
DB_KUECHE = "zubereitung.db"
DB_SIGNAL = "signal.db"

# Datenbanken initialisieren
def init_db():
    with sqlite3.connect(DB_NUTZER) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS benutzer (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)")
    with sqlite3.connect(DB_ARTIKEL) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS artikel (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, preis REAL NOT NULL CHECK(preis >= 0))")
    with sqlite3.connect(DB_BESTELLUNG) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS bestellungen (id INTEGER PRIMARY KEY AUTOINCREMENT, benutzer TEXT NOT NULL, artikel TEXT NOT NULL, menge INTEGER NOT NULL CHECK(menge > 0), einzelpreis REAL NOT NULL, gesamtpreis REAL NOT NULL, zeitstempel TEXT)")
    with sqlite3.connect(DB_KUECHE) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS kueche (id INTEGER PRIMARY KEY AUTOINCREMENT, inhalt TEXT NOT NULL, zeit TEXT)")
    with sqlite3.connect(DB_SIGNAL) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS signal (id INTEGER PRIMARY KEY, aktualisieren INTEGER)")
        conn.execute("INSERT OR IGNORE INTO signal (id, aktualisieren) VALUES (1, 0)")

def setze_signal():
    with sqlite3.connect(DB_SIGNAL) as conn:
        conn.execute("UPDATE signal SET aktualisieren = 1 WHERE id = 1")

def zuruecksetzen_signal():
    with sqlite3.connect(DB_SIGNAL) as conn:
        conn.execute("UPDATE signal SET aktualisieren = 0 WHERE id = 1")

def pruefe_signal():
    with sqlite3.connect(DB_SIGNAL) as conn:
        wert = conn.execute("SELECT aktualisieren FROM signal WHERE id = 1").fetchone()
        return wert[0] == 1 if wert else False

def get_benutzer():
    with sqlite3.connect(DB_NUTZER) as conn:
        return [row[0] for row in conn.execute("SELECT name FROM benutzer ORDER BY name ASC")]

def get_artikel():
    with sqlite3.connect(DB_ARTIKEL) as conn:
        return conn.execute("SELECT name, preis FROM artikel").fetchall()

def get_bestellungen(benutzer=None):
    with sqlite3.connect(DB_BESTELLUNG) as conn:
        if benutzer:
            return conn.execute("SELECT * FROM bestellungen WHERE benutzer=? ORDER BY id DESC", (benutzer,)).fetchall()
        return conn.execute("SELECT * FROM bestellungen ORDER BY id DESC").fetchall()

def get_kuechen_bestellungen():
    with sqlite3.connect(DB_KUECHE) as conn:
        return conn.execute("SELECT id, inhalt FROM kueche ORDER BY id ASC LIMIT 3").fetchall()

def entferne_kuechen_bestellung(bestell_id):
    with sqlite3.connect(DB_KUECHE) as conn:
        conn.execute("DELETE FROM kueche WHERE id=?", (bestell_id,))

def benutzer_verwalten():
    st.subheader("Benutzer")
    neuer_name = st.text_input("Neuen Benutzer hinzufügen")
    if st.button("Hinzufügen") and neuer_name:
        try:
            with sqlite3.connect(DB_NUTZER) as conn:
                conn.execute("INSERT INTO benutzer (name) VALUES (?)", (neuer_name.strip(),))
            st.success(f"Benutzer '{neuer_name}' hinzugefügt.")
        except sqlite3.IntegrityError:
            st.error("Benutzername existiert bereits.")
    if st.button("Benutzerliste aktualisieren"):
        st.session_state['benutzer_liste'] = get_benutzer()
    for name in st.session_state.get('benutzer_liste', get_benutzer()):
        col1, col2 = st.columns([4, 1])
        col1.write(name)
        if col2.button("🗑️", key=f"del_{name}"):
            with sqlite3.connect(DB_NUTZER) as conn:
                conn.execute("DELETE FROM benutzer WHERE name=?", (name,))
            st.success(f"Benutzer '{name}' gelöscht.")
            st.session_state['benutzer_liste'] = get_benutzer()
            st.experimental_rerun()

def artikel_verwalten():
    st.subheader("Artikel")
    name = st.text_input("Artikelname")
    preis = st.number_input("Preis (€)", min_value=0.0, format="%.2f")
    if st.button("Artikel hinzufügen") and name:
        try:
            with sqlite3.connect(DB_ARTIKEL) as conn:
                conn.execute("INSERT INTO artikel (name, preis) VALUES (?, ?)", (name.strip(), preis))
            st.success("Artikel hinzugefügt.")
        except sqlite3.IntegrityError:
            st.error("Artikelname existiert bereits.")
    artikel = get_artikel()
    for idx, (name, preis) in enumerate(artikel):
        col1, col2, col3 = st.columns([3, 1, 1])
        col1.write(f"{name} ({preis:.2f} €)")
        if col3.button("🗑️", key=f"del_art_{idx}"):
            with sqlite3.connect(DB_ARTIKEL) as conn:
                conn.execute("DELETE FROM artikel WHERE name=?", (name,))
            st.success(f"Artikel '{name}' gelöscht.")
            st.experimental_rerun()

def bestellung():
    conn = sqlite3.connect(DB_BESTELLUNG, check_same_thread=False)
    cursor = conn.cursor()

    st.subheader("Bestellung")
    benutzer = st.selectbox("Benutzer auswählen", get_benutzer())
    artikel_daten = get_artikel()

    if st.session_state.get("bestellung_abgeschlossen"):
        st.info(st.session_state.get("bon_text", ""))
        if st.button("➕ Neue Bestellung"):
            st.session_state.bestellung_abgeschlossen = False
            st.session_state.bon_text = ""
            st.rerun()
        return

    gesamt = 0
    artikel_mengen = {}
    for name, preis in artikel_daten:
        key = f"menge_{name}"
        menge = st.number_input(f"{name} ({preis:.2f} €)", min_value=0, step=1, key=key)
        artikel_mengen[name] = (menge, preis)
        gesamt += menge * preis

    st.markdown(f"### 💰 Gesamt: {gesamt:.2f} €")

    if st.button("✅ Bestellung abschließen"):
        bestellnummer = cursor.execute("SELECT MAX(id) FROM bestellungen").fetchone()[0]
        bestellnummer = (bestellnummer or 0) + 1
        zeit = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        bon_text = f"""🧾 **Bestellnummer:** #{bestellnummer}
**Benutzer:** {benutzer}

"""
        bestellte_menge = 0
        zubereitungs_text = f"Bestellung #{bestellnummer} – {benutzer}\n"
        for name, (menge, preis) in artikel_mengen.items():
            if menge > 0:
                einzel_summe = menge * preis
                bon_text += f"{menge} x {name} á {preis:.2f} € = {einzel_summe:.2f} €\n"
                zubereitungs_text += f"→ {menge} x {name}\n"
                cursor.execute(
                    "INSERT INTO bestellungen (benutzer, artikel, menge, einzelpreis, gesamtpreis, zeitstempel) VALUES (?, ?, ?, ?, ?, ?)",
                    (benutzer, name, menge, preis, einzel_summe, zeit)
                )
                bestellte_menge += menge

        bon_text += f"\n**Gesamt:** {gesamt:.2f} €"

        with sqlite3.connect(DB_KUECHE) as kconn:
            kconn.execute("INSERT INTO kueche (inhalt, zeit) VALUES (?, ?)", (zubereitungs_text.strip(), zeit))

        conn.commit()
        setze_signal()
        st.session_state.bon_text = bon_text
        st.session_state.bestellung_abgeschlossen = True
        st.rerun()

def zubereitung():
    st.subheader("🔥 Zubereitung")

    if "letzte_abfrage" not in st.session_state:
        st.session_state.letzte_abfrage = 0
    now = time.time()

    if now - st.session_state.letzte_abfrage > 3:
        st.session_state.letzte_abfrage = now
        if pruefe_signal():
            st.session_state.kueche_bestellungen = get_kuechen_bestellungen()
            zuruecksetzen_signal()

    bestellungen = st.session_state.get("kueche_bestellungen", get_kuechen_bestellungen())

    if not bestellungen:
        st.markdown("## ✅ **Alle Bestellungen erledigt!** 🎉🎉🎉")
        st.markdown("<marquee>👨‍🍳 Zeit für eine Pause! 👨‍🍳</marquee>", unsafe_allow_html=True)
        return

    for bestell_id, inhalt in bestellungen:
        with st.container():
            st.markdown(
                f"<div style='font-size:28px; line-height:1.8em; border:2px solid #f63366; padding:1em; border-radius:10px; background:#fff5f8'>{inhalt.replace(chr(10), '<br>')}</div>",
                unsafe_allow_html=True
            )
            if st.button("✅ Zubereitet", key=f"done_{bestell_id}"):
                entferne_kuechen_bestellung(bestell_id)
                zuruecksetzen_signal()
                st.rerun()

def statistik():
    st.subheader("📊 Statistik")
    nutzer_filter = st.selectbox("Benutzer filtern", [""] + get_benutzer())
    daten = get_bestellungen(nutzer_filter if nutzer_filter else None)
    df = pd.DataFrame(daten, columns=["ID", "Benutzer", "Artikel", "Menge", "Einzelpreis", "Gesamtpreis", "Zeitstempel"])
    st.dataframe(df)
    st.write(f"Anzahl Bestellungen: {len(df)}")
    st.write(f"Gesamtsumme: {df['Gesamtpreis'].sum():.2f} €")
    if st.button("CSV exportieren"):
        csv_data = df.to_csv(index=False)
        st.download_button("Download CSV", data=csv_data, file_name="bestellungen.csv", mime="text/csv")

# App Start
st.set_page_config(page_title="Flammkuchen", layout="wide")
init_db()

params = st.query_params

if "page" in params:
    st.session_state.page = params["page"]

with st.sidebar:
    st.markdown("## Navigation")
    if st.button("🧾 Bestellen", use_container_width=True):
        st.query_params["page"] = "Bestellen"
        st.session_state.page = "Bestellen"
    if st.button("👥 Benutzer", use_container_width=True):
        st.query_params["page"] = "Benutzer verwalten"
        st.session_state.page = "Benutzer verwalten"
    if st.button("🛠️ Artikel", use_container_width=True):
        st.query_params["page"] = "Artikel verwalten"
        st.session_state.page = "Artikel verwalten"
    if st.button("📊 Statistik", use_container_width=True):
        st.query_params["page"] = "Statistik anzeigen"
        st.session_state.page = "Statistik anzeigen"
    if st.button("🔥 Zubereitung", use_container_width=True):
        st.query_params["page"] = "Zubereitung"
        st.session_state.page = "Zubereitung"


if "page" not in st.session_state:
    st.session_state.page = "Bestellen"

if st.session_state.page == "Bestellen":
    bestellung()
elif st.session_state.page == "Benutzer verwalten":
    benutzer_verwalten()
elif st.session_state.page == "Artikel verwalten":
    artikel_verwalten()
elif st.session_state.page == "Statistik anzeigen":
    statistik()
elif st.session_state.page == "Zubereitung":
    zubereitung()
