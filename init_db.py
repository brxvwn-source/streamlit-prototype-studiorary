import sqlite3
from datetime import datetime

conn = sqlite3.connect("agence.db")
cursor = conn.cursor()

# =========================
# TABLE VERSIONS
# =========================
cursor.execute("""
CREATE TABLE IF NOT EXISTS versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    date_creation TEXT NOT NULL,
    active INTEGER DEFAULT 0
)
""")

# =========================
# REGLES HONORAIRES
# =========================
cursor.execute("""
CREATE TABLE IF NOT EXISTS regles_honoraires (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER,
    surface_min REAL,
    surface_max REAL,
    taux REAL,
    FOREIGN KEY(version_id) REFERENCES versions(id)
)
""")

# =========================
# PHASES
# =========================
cursor.execute("""
CREATE TABLE IF NOT EXISTS phases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER,
    nom TEXT,
    ordre INTEGER,
    pourcentage REAL,
    FOREIGN KEY(version_id) REFERENCES versions(id)
)
""")

# =========================
# TYPES FACTURE
# =========================
cursor.execute("""
CREATE TABLE IF NOT EXISTS types_facture (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER,
    nom TEXT,
    pourcentage REAL,
    FOREIGN KEY(version_id) REFERENCES versions(id)
)
""")

# =========================
# CHARGES FIXES
# =========================
cursor.execute("""
CREATE TABLE IF NOT EXISTS charges_fixes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER,
    nom TEXT,
    montant REAL,
    FOREIGN KEY(version_id) REFERENCES versions(id)
)
""")

# =========================
# PROJETS
# =========================
cursor.execute("""
CREATE TABLE IF NOT EXISTS projets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT,
    surface REAL,
    budget REAL,
    date_debut TEXT,
    phase_ordre INTEGER,
    version_id INTEGER,
    FOREIGN KEY(version_id) REFERENCES versions(id)
)
""")

# =========================
# FACTURES
# =========================
cursor.execute("""
CREATE TABLE IF NOT EXISTS factures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    projet_id INTEGER,
    phase_ordre INTEGER,
    type_nom TEXT,
    montant REAL,
    date_emission TEXT,
    date_prevue TEXT,
    payee INTEGER DEFAULT 0,
    date_paiement TEXT,
    FOREIGN KEY(projet_id) REFERENCES projets(id)
)
""")

conn.commit()

# =========================
# INSERT VERSION INITIALE
# =========================
cursor.execute("INSERT INTO versions (nom, date_creation, active) VALUES (?, ?, ?)",
               ("Version initiale 2026", datetime.now().isoformat(), 1))

version_id = cursor.lastrowid

# =========================
# INSERT REGLES HONORAIRES
# =========================
honoraires = [
    (version_id, 0, 200, 0.10),
    (version_id, 200, 500, 0.08),
    (version_id, 500, 999999, 0.07)
]

cursor.executemany("""
INSERT INTO regles_honoraires (version_id, surface_min, surface_max, taux)
VALUES (?, ?, ?, ?)
""", honoraires)

# =========================
# INSERT PHASES
# =========================
phases = [
    (version_id, "ESQ", 1, 0.10),
    (version_id, "APS", 2, 0.15),
    (version_id, "APD", 3, 0.15),
    (version_id, "PRO", 4, 0.20),
    (version_id, "DET", 5, 0.25),
    (version_id, "AOR", 6, 0.15),
]

cursor.executemany("""
INSERT INTO phases (version_id, nom, ordre, pourcentage)
VALUES (?, ?, ?, ?)
""", phases)

# =========================
# INSERT TYPES FACTURE
# =========================
types = [
    (version_id, "Acompte", 0.30),
    (version_id, "Intermédiaire", 0.30),
    (version_id, "Solde", 0.40),
]

cursor.executemany("""
INSERT INTO types_facture (version_id, nom, pourcentage)
VALUES (?, ?, ?)
""", types)

conn.commit()
conn.close()

print("✅ Base de données créée avec version initiale")