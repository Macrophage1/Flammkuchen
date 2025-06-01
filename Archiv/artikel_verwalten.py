import sqlite3
import streamlit as st

# Verbindung zur Datenbank
conn = sqlite3.connect("artikel.db", check_same_thread=False)
cursor = conn.cursor()

# Tabelle erstellen, falls sie nicht existiert
cursor.execute("""
CREATE TABLE IF NOT EXISTS artikel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    preis REAL NOT NULL CHECK(preis >= 0)
)
""")
conn.commit()

st.title("🛠️ Artikelverwaltung")

# Artikel hinzufügen
st.subheader("➕ Neuen Artikel hinzufügen")
name = st.text_input("Artikelname")
preis = st.number_input("Preis (€)", min_value=0.0, step=0.10, format="%.2f")

if st.button("Artikel hinzufügen"):
    if name.strip():
        try:
            cursor.execute("INSERT INTO artikel (name, preis) VALUES (?, ?)", (name.strip(), preis))
            conn.commit()
            st.success(f"Artikel '{name}' hinzugefügt.")
        except sqlite3.IntegrityError:
            st.error("Artikelname existiert bereits.")
    else:
        st.warning("Bitte einen gültigen Artikelnamen eingeben.")

# Artikel anzeigen und löschen
st.subheader("🗑️ Bestehende Artikel löschen")
cursor.execute("SELECT id, name, preis FROM artikel ORDER BY name")
artikel_liste = cursor.fetchall()

if artikel_liste:
    artikel_anzeige = [f"{id_}: {name} ({preis:.2f} €)" for id_, name, preis in artikel_liste]
    auswahl = st.selectbox("Artikel auswählen", artikel_anzeige)
    if st.button("Löschen"):
        artikel_id = int(auswahl.split(":")[0])
        cursor.execute("DELETE FROM artikel WHERE id = ?", (artikel_id,))
        conn.commit()
        st.success("Artikel gelöscht.")
        st.experimental_rerun()
else:
    st.info("Noch keine Artikel vorhanden.")

conn.close()
