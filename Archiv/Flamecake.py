import tkinter as tk
from tkinter import messagebox, filedialog
import sqlite3
import datetime
import csv

STANDARD_WIDTH = 25

class BestellApp:
    def __init__(self, root):
        self.root = root
        self.root.withdraw()
        self.aktueller_benutzer = None
        self.nutzer_var = tk.StringVar()
        self.init_datenbanken()
        self.zeige_startfenster()

    def init_datenbanken(self):
        self.nutzer_conn = sqlite3.connect("nutzer.db")
        self.nutzer_cursor = self.nutzer_conn.cursor()
        self.nutzer_cursor.execute("""
            CREATE TABLE IF NOT EXISTS benutzer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
        """)

        self.artikel_conn = sqlite3.connect("artikel.db")
        self.artikel_cursor = self.artikel_conn.cursor()
        self.artikel_cursor.execute("""
            CREATE TABLE IF NOT EXISTS artikel (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                preis REAL NOT NULL CHECK(preis >= 0)
            )
        """)

        self.bestell_conn = sqlite3.connect("bestellungen.db")
        self.bestell_cursor = self.bestell_conn.cursor()
        self.bestell_cursor.execute("""
            CREATE TABLE IF NOT EXISTS bestellungen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                benutzer TEXT NOT NULL,
                artikel TEXT NOT NULL,
                menge INTEGER NOT NULL CHECK(menge > 0),
                einzelpreis REAL NOT NULL,
                gesamtpreis REAL NOT NULL,
                zeitstempel TEXT
            )
        """)
        try:
            self.bestell_cursor.execute("ALTER TABLE bestellungen ADD COLUMN zeitstempel TEXT")
            self.bestell_conn.commit()
        except sqlite3.OperationalError:
            pass

    def zeige_startfenster(self):
        self.start_fenster = tk.Toplevel(self.root)
        self.start_fenster.title("Benutzer auswählen")
        self.start_fenster.configure(bg="#f0f0f0")

        frame = tk.Frame(self.start_fenster, bg="#f0f0f0", padx=20, pady=20)
        frame.pack()

        tk.Label(frame, text="👤 Benutzer auswählen", font=("Arial", 14, "bold"), bg="#f0f0f0").pack(pady=5)
        self.nutzer_dropdown = tk.OptionMenu(frame, self.nutzer_var, "")
        self.nutzer_dropdown.config(width=STANDARD_WIDTH)
        self.nutzer_dropdown.pack(pady=5)

        tk.Button(frame, text="✅ Weiter", bg="#ddffdd", width=STANDARD_WIDTH, command=self.nutzer_auswaehlen).pack(pady=10)
        tk.Button(frame, text="👥 Benutzer verwalten", bg="#ddeeff", width=STANDARD_WIDTH, command=self.benutzer_verwalten).pack(pady=5)
        tk.Button(frame, text="⚙️ Artikel verwalten", bg="#fff0cc", width=STANDARD_WIDTH, command=self.artikel_verwalten).pack(pady=5)
        tk.Button(frame, text="📊 Statistik anzeigen", bg="#e0ffe0", width=STANDARD_WIDTH, command=self.statistik_anzeigen).pack(pady=5)

        self.nutzer_liste_aktualisieren()

    def nutzer_auswaehlen(self):
        name = self.nutzer_var.get()
        if name:
            self.aktueller_benutzer = name
            self.start_fenster.destroy()
            self.bestellfenster_anzeigen()
        else:
            messagebox.showwarning("Fehler", "Bitte Benutzer auswählen!")

    def nutzer_liste_aktualisieren(self):
        self.nutzer_cursor.execute("SELECT name FROM benutzer")
        namen = [row[0] for row in self.nutzer_cursor.fetchall()]
        self.nutzer_var.set("")
        self.nutzer_dropdown["menu"].delete(0, "end")
        for name in namen:
            self.nutzer_dropdown["menu"].add_command(label=name, command=tk._setit(self.nutzer_var, name))

    def benutzer_verwalten(self):
        verwaltung = tk.Toplevel()
        verwaltung.title("👥 Benutzer verwalten")

        def aktualisiere_liste():
            nutzer_liste.delete(0, tk.END)
            self.nutzer_cursor.execute("SELECT id, name FROM benutzer")
            for id, name in self.nutzer_cursor.fetchall():
                nutzer_liste.insert(tk.END, f"{id}: {name}")

        def benutzer_hinzufuegen():
            name = entry_name.get().strip()
            if not name:
                messagebox.showwarning("Fehler", "Name darf nicht leer sein.")
                return
            try:
                self.nutzer_cursor.execute("INSERT INTO benutzer (name) VALUES (?)", (name,))
                self.nutzer_conn.commit()
                entry_name.delete(0, tk.END)
                aktualisiere_liste()
                self.nutzer_liste_aktualisieren()
            except sqlite3.IntegrityError:
                messagebox.showerror("Fehler", "Benutzername existiert bereits.")

        def benutzer_loeschen():
            auswahl = nutzer_liste.curselection()
            if auswahl:
                eintrag = nutzer_liste.get(auswahl[0])
                nutzer_id = int(eintrag.split(":")[0])
                self.nutzer_cursor.execute("DELETE FROM benutzer WHERE id = ?", (nutzer_id,))
                self.nutzer_conn.commit()
                aktualisiere_liste()
                self.nutzer_liste_aktualisieren()

        tk.Label(verwaltung, text="Benutzername").pack()
        entry_name = tk.Entry(verwaltung, width=STANDARD_WIDTH)
        entry_name.pack(pady=2)

        tk.Button(verwaltung, text="➕ Hinzufügen", command=benutzer_hinzufuegen, width=STANDARD_WIDTH).pack(pady=2)
        tk.Button(verwaltung, text="🗑️ Löschen", command=benutzer_loeschen, width=STANDARD_WIDTH).pack(pady=2)

        nutzer_liste = tk.Listbox(verwaltung, width=40)
        nutzer_liste.pack(pady=5)
        aktualisiere_liste()

    def artikel_verwalten(self):
        verwaltung = tk.Toplevel()
        verwaltung.title("🛠️ Artikel verwalten")

        def aktualisiere_liste():
            artikel_liste.delete(0, tk.END)
            self.artikel_cursor.execute("SELECT id, name, preis FROM artikel")
            for id, name, preis in self.artikel_cursor.fetchall():
                artikel_liste.insert(tk.END, f"{id}: {name} ({preis:.2f} €)")

        def artikel_hinzufuegen():
            name = entry_name.get().strip()
            try:
                preis = float(entry_preis.get())
                if preis < 0:
                    raise ValueError
                self.artikel_cursor.execute("INSERT INTO artikel (name, preis) VALUES (?, ?)", (name, preis))
                self.artikel_conn.commit()
                entry_name.delete(0, tk.END)
                entry_preis.delete(0, tk.END)
                aktualisiere_liste()
            except ValueError:
                messagebox.showwarning("Fehler", "Ungültiger Preis.")
            except sqlite3.IntegrityError:
                messagebox.showerror("Fehler", "Artikel existiert bereits.")

        def artikel_loeschen():
            auswahl = artikel_liste.curselection()
            if auswahl:
                eintrag = artikel_liste.get(auswahl[0])
                artikel_id = int(eintrag.split(":")[0])
                self.artikel_cursor.execute("DELETE FROM artikel WHERE id = ?", (artikel_id,))
                self.artikel_conn.commit()
                aktualisiere_liste()

        tk.Label(verwaltung, text="Artikelname").pack()
        entry_name = tk.Entry(verwaltung, width=STANDARD_WIDTH)
        entry_name.pack()

        tk.Label(verwaltung, text="Preis (€)").pack()
        entry_preis = tk.Entry(verwaltung, width=STANDARD_WIDTH)
        entry_preis.pack()

        tk.Button(verwaltung, text="➕ Hinzufügen", command=artikel_hinzufuegen, width=STANDARD_WIDTH).pack(pady=2)
        tk.Button(verwaltung, text="🗑️ Löschen", command=artikel_loeschen, width=STANDARD_WIDTH).pack(pady=2)

        artikel_liste = tk.Listbox(verwaltung, width=40)
        artikel_liste.pack(pady=5)
        aktualisiere_liste()

    def statistik_anzeigen(self):
        fenster = tk.Toplevel()
        fenster.title("📊 Bestellstatistik")
        fenster.geometry("750x500")

        filter_frame = tk.Frame(fenster)
        filter_frame.pack(pady=5)

        tk.Label(filter_frame, text="Benutzer filtern:").pack(side="left")

        self.nutzer_cursor.execute("SELECT name FROM benutzer ORDER BY name ASC")
        nutzer_namen = [row[0] for row in self.nutzer_cursor.fetchall()]
        filter_var = tk.StringVar()
        filter_var.set("")

        nutzer_dropdown = tk.OptionMenu(filter_frame, filter_var, "", *nutzer_namen)
        nutzer_dropdown.pack(side="left", padx=5)

        listbox = tk.Listbox(fenster, width=110)
        listbox.pack(padx=10, pady=10, fill="both", expand=True)

        info_label = tk.Label(fenster, text="Bestellungen: 0 | Gesamtsumme: 0.00 €", font=("Arial", 11, "bold"))
        info_label.pack(pady=(0, 5))

        def aktualisieren():
            listbox.delete(0, tk.END)
            gesamt = 0
            anzahl = 0

            if filter_var.get():
                self.bestell_cursor.execute("""
                    SELECT id, benutzer, artikel, menge, einzelpreis, gesamtpreis, zeitstempel
                    FROM bestellungen
                    WHERE benutzer = ?
                    ORDER BY id DESC
                """, (filter_var.get(),))
            else:
                self.bestell_cursor.execute("""
                    SELECT id, benutzer, artikel, menge, einzelpreis, gesamtpreis, zeitstempel
                    FROM bestellungen
                    ORDER BY id DESC
                """)

            daten = self.bestell_cursor.fetchall()
            for eintrag in daten:
                id_, benutzer, artikel, menge, einzelpreis, gesamtpreis, zeit = eintrag
                text = f"#{id_} | {benutzer} | {artikel} | {menge} Stk. á {einzelpreis:.2f} € = {gesamtpreis:.2f} € | {zeit}"
                listbox.insert(tk.END, text)
                gesamt += gesamtpreis
                anzahl += 1

            info_label.config(text=f"Bestellungen: {anzahl} | Gesamtsumme: {gesamt:.2f} €")

        def exportieren():
            daten = listbox.get(0, tk.END)
            dateipfad = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV-Dateien", "*.csv")])
            if dateipfad:
                with open(dateipfad, mode='w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Bestellnummer", "Benutzer", "Artikel", "Menge", "Einzelpreis", "Gesamtpreis", "Zeitstempel"])
                    for zeile in daten:
                        parts = zeile.split("|")
                        writer.writerow([part.strip() for part in parts])
                messagebox.showinfo("Erfolg", f"Exportiert nach:\n{dateipfad}")

        tk.Button(filter_frame, text="🔍 Filtern", command=aktualisieren).pack(side="left", padx=5)
        tk.Button(fenster, text="📤 Exportieren als CSV", command=exportieren, bg="#ddddff").pack(pady=5)

        aktualisieren()


    def bestellfenster_anzeigen(self):
        fenster = tk.Toplevel(self.root)
        fenster.title("Bestellung erfassen")

        self.artikel_cursor.execute("SELECT name, preis FROM artikel")
        artikel_liste = self.artikel_cursor.fetchall()
        auswahl = {name: [0, preis] for name, preis in artikel_liste}

        def aktualisieren():
            for widget in frame_anzeigen.winfo_children():
                widget.destroy()

            gesamt = 0
            row = 0
            for name, (menge, preis) in auswahl.items():
                if menge > 0:
                    tk.Label(frame_anzeigen, text=f"{menge} x {name}").grid(row=row, column=0, sticky="w")
                    tk.Label(frame_anzeigen, text=f"{menge * preis:.2f} €").grid(row=row, column=1, sticky="e")
                    row += 1
                    gesamt += menge * preis
            lbl_gesamt.config(text=f"Gesamt: {gesamt:.2f} €")

        def plus(name):
            auswahl[name][0] += 1
            aktualisieren()

        def minus(name):
            if auswahl[name][0] > 0:
                auswahl[name][0] -= 1
            aktualisieren()

        def naechste_bestellnummer():
            self.bestell_cursor.execute("SELECT MAX(id) FROM bestellungen")
            result = self.bestell_cursor.fetchone()[0]
            return (result or 0) + 1

        def abschliessen():
            bestellnummer = naechste_bestellnummer()
            zeit = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            bon_text = f"Bestellnummer: #{bestellnummer}\nBenutzer: {self.aktueller_benutzer}\n\n"
            gesamtpreis = 0
            bestellte_menge = 0

            for name, (menge, preis) in auswahl.items():
                if menge > 0:
                    einzel_summe = menge * preis
                    bon_text += f"{menge} x {name} á {preis:.2f} € = {einzel_summe:.2f} €\n"
                    gesamtpreis += einzel_summe
                    bestellte_menge += menge
                    self.bestell_cursor.execute("""
                        INSERT INTO bestellungen (benutzer, artikel, menge, einzelpreis, gesamtpreis, zeitstempel)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (self.aktueller_benutzer, name, menge, preis, einzel_summe, zeit))

            # 🔍 Bisherige offene Flammkuchen aus den letzten 20 Minuten (als Warteschlange)
            now = datetime.datetime.now()
            zwanzig_minuten_zurueck = now - datetime.timedelta(minutes=20)
            self.bestell_cursor.execute("""
                SELECT SUM(menge) FROM bestellungen
                WHERE zeitstempel > ?
            """, (zwanzig_minuten_zurueck.strftime("%Y-%m-%d %H:%M:%S"),))
            result = self.bestell_cursor.fetchone()
            warteschlange_menge = result[0] if result[0] else 0

            # 🔢 Ofenkapazität & Logik
            ofen_kapazitaet = 8
            backzeit = 5  # Minuten
            vorbereitung = 2  # Minuten
            import math

            total = warteschlange_menge + bestellte_menge
            durchgaenge = math.ceil(total / ofen_kapazitaet)
            minuten = durchgaenge * backzeit + vorbereitung

            # Abholzeit berechnen & runden
            fertig_uhrzeit = now + datetime.timedelta(minutes=minuten)
            minute = (fertig_uhrzeit.minute // 5 + 1) * 5
            fertig_uhrzeit = fertig_uhrzeit.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(minutes=minute)

            abholzeit_str = fertig_uhrzeit.strftime("%H:%M")
            bon_text += f"\nAbholzeit: ca. {abholzeit_str}"
            bon_text += f"\nGesamt: {gesamtpreis:.2f} €"

            self.bestell_conn.commit()
            messagebox.showinfo("🧾 Bestellung abgeschlossen", bon_text)

            fenster.destroy()
            self.bestellfenster_anzeigen()


        tk.Label(fenster, text=f"Benutzer: {self.aktueller_benutzer}", font=("Arial", 12, "bold")).pack(pady=5)

        frame_buttons = tk.Frame(fenster)
        frame_buttons.pack()

        for idx, (name, preis) in enumerate(artikel_liste):
            tk.Label(frame_buttons, text=f"{name} ({preis:.2f} €)", width=20, anchor="w").grid(row=idx, column=0)
            tk.Button(frame_buttons, text="➖", width=2, command=lambda n=name: minus(n)).grid(row=idx, column=1)
            tk.Button(frame_buttons, text="➕", width=2, command=lambda n=name: plus(n)).grid(row=idx, column=2)

        frame_anzeigen = tk.Frame(fenster)
        frame_anzeigen.pack(pady=5)

        lbl_gesamt = tk.Label(fenster, text="Gesamt: 0.00 €", font=("Arial", 12))
        lbl_gesamt.pack()

        tk.Button(fenster, text="🧾 Bestellung abschließen", command=abschliessen, bg="#ccffcc").pack(pady=5)
        tk.Button(fenster, text="🔙 Zurück", command=lambda: [fenster.destroy(), self.zeige_startfenster()], bg="#ffdddd").pack(pady=5)

        aktualisieren()


    def beenden(self):
        self.nutzer_conn.close()
        self.artikel_conn.close()
        self.bestell_conn.close()

if __name__ == "__main__":
    root = tk.Tk()
    try:
        app = BestellApp(root)
        root.mainloop()
    finally:
        app.beenden()
