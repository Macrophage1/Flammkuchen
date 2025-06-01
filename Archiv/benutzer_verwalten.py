import sqlite3
import streamlit as st

# Verbindung zur Datenbank
conn = sqlite3.connect("nutzer.db", check_same_thread=False)
cursor = conn.cursor()

# Tabelle erstellen, falls sie nicht existiert
cursor.execute("""
CREATE TABLE IF NOT EXISTS benutzer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
)
""")
conn.commit()

# Streamlit UI
st.title("👥 Benutzerverwaltung")

# Benutzer hinzufügen
st.subheader("➕ Neuen Benutzer hinzufügen")
new_user = st.text_input("Benutzername eingeben")
if st.button("Hinzufügen"):
    if new_user.strip():
        try:
            cursor.execute("INSERT INTO benutzer (name) VALUES (?)", (new_user.strip(),))
            conn.commit()
            st.success(f"Benutzer '{new_user}' hinzugefügt.")
        except sqlite3.IntegrityError:
            st.error("Benutzername existiert bereits.")
    else:
        st.warning("Bitte einen gültigen Benutzernamen eingeben.")

# Benutzerliste anzeigen und löschen
st.subheader("🗑️ Bestehende Benutzer löschen")
cursor.execute("SELECT id, name FROM benutzer ORDER BY name ASC")
benutzer_liste = cursor.fetchall()

if benutzer_liste:
    benutzer_namen = [f"{id_}: {name}" for id_, name in benutzer_liste]
    auswahl = st.selectbox("Benutzer auswählen", benutzer_namen)
    if st.button("Löschen"):
        benutzer_id = int(auswahl.split(":")[0])
        cursor.execute("DELETE FROM benutzer WHERE id = ?", (benutzer_id,))
        conn.commit()
        st.success("Benutzer gelöscht.")
        st.experimental_rerun()
else:
    st.info("Noch keine Benutzer vorhanden.")

# Verbindung schließen
conn.close()
