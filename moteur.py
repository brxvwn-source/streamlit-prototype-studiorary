import sqlite3
from datetime import datetime

DB = "agence.db"

# ─────────────────────────────────────────────
# BASE
# ─────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT,
            date_creation TEXT,
            active INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS regles_honoraires (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id INTEGER,
            surface_min REAL,
            surface_max REAL,
            taux REAL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS phases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id INTEGER,
            nom TEXT,
            ordre INTEGER,
            pourcentage REAL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS types_facture (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id INTEGER,
            nom TEXT,
            pourcentage REAL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS projets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT,
            surface REAL,
            budget REAL,
            date_debut TEXT,
            phase_ordre INTEGER,
            version_id INTEGER,
            photo BLOB,
            photo_nom TEXT,
            photo_type TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS factures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            projet_id INTEGER,
            phase_ordre INTEGER,
            type_nom TEXT,
            montant REAL,
            date_emission TEXT,
            date_prevue TEXT,
            date_paiement TEXT,
            payee INTEGER DEFAULT 0,
            numero TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS charges_fixes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            libelle TEXT,
            montant REAL,
            periodicite TEXT,
            date_debut TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS agence (
            id INTEGER PRIMARY KEY,
            nom TEXT,
            adresse TEXT,
            telephone TEXT,
            email TEXT,
            siret TEXT
        )
    """)

    # Infos agence par défaut
    c.execute("SELECT COUNT(*) FROM agence")
    if c.fetchone()[0] == 0:
        c.execute("""
            INSERT INTO agence (id, nom, adresse, telephone, email, siret)
            VALUES (1, 'Studiorary', '', '', '', '')
        """)

    # Colonnes projets manquantes (migration)
    existing = [row[1] for row in c.execute("PRAGMA table_info(projets)").fetchall()]
    for col, typ in [("photo", "BLOB"), ("photo_nom", "TEXT"), ("photo_type", "TEXT")]:
        if col not in existing:
            c.execute(f"ALTER TABLE projets ADD COLUMN {col} {typ}")

    # Colonne numero dans factures
    existing_f = [row[1] for row in c.execute("PRAGMA table_info(factures)").fetchall()]
    if "numero" not in existing_f:
        c.execute("ALTER TABLE factures ADD COLUMN numero TEXT")

    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# VERSIONS
# ─────────────────────────────────────────────

def get_active_version():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT id FROM versions WHERE active = 1")
    v = c.fetchone()
    conn.close()
    return v[0] if v else None


# ─────────────────────────────────────────────
# HONORAIRES
# ─────────────────────────────────────────────

def get_taux_honoraires(surface, version_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        SELECT taux FROM regles_honoraires
        WHERE version_id = ? AND ? >= surface_min AND ? < surface_max
    """, (version_id, surface, surface))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0.0


def calcul_honoraires(surface, budget, version_id):
    taux = get_taux_honoraires(surface, version_id)
    return budget * taux


def get_cumul_phase(phase_ordre, version_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        SELECT SUM(pourcentage) FROM phases
        WHERE version_id = ? AND ordre <= ?
    """, (version_id, phase_ordre))
    row = c.fetchone()
    conn.close()
    return row[0] if row[0] else 0.0


def droit_a_facturer(surface, budget, phase_ordre, version_id):
    honoraires = calcul_honoraires(surface, budget, version_id)
    cumul = get_cumul_phase(phase_ordre, version_id)
    return honoraires * cumul


def montant_facture(surface, budget, phase_ordre, type_nom, version_id):
    honoraires = calcul_honoraires(surface, budget, version_id)
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        SELECT pourcentage FROM phases
        WHERE version_id = ? AND ordre = ?
    """, (version_id, phase_ordre))
    phase_pct = c.fetchone()
    c.execute("""
        SELECT pourcentage FROM types_facture
        WHERE version_id = ? AND nom = ?
    """, (version_id, type_nom))
    type_pct = c.fetchone()
    conn.close()
    if not phase_pct or not type_pct:
        return 0.0
    return honoraires * phase_pct[0] * type_pct[0]


# ─────────────────────────────────────────────
# PROJETS
# ─────────────────────────────────────────────

def creer_projet(nom, surface, budget, date_debut, phase_ordre):
    version_id = get_active_version()
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO projets (nom, surface, budget, date_debut, phase_ordre, version_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (nom, surface, budget, date_debut, phase_ordre, version_id))
    conn.commit()
    conn.close()


def liste_projets():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        SELECT id, nom, surface, budget, phase_ordre, version_id
        FROM projets
    """)
    rows = c.fetchall()
    conn.close()
    return rows


def get_projet(projet_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        SELECT id, nom, surface, budget, date_debut, phase_ordre, version_id,
               photo, photo_nom, photo_type
        FROM projets WHERE id = ?
    """, (projet_id,))
    row = c.fetchone()
    conn.close()
    return row


def modifier_projet(projet_id, nom, surface, budget, date_debut, phase_ordre):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        UPDATE projets
        SET nom=?, surface=?, budget=?, date_debut=?, phase_ordre=?
        WHERE id=?
    """, (nom, surface, budget, date_debut, phase_ordre, projet_id))
    conn.commit()
    conn.close()


def upload_photo_projet(projet_id, photo_bytes, photo_nom, photo_type):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        UPDATE projets SET photo=?, photo_nom=?, photo_type=?
        WHERE id=?
    """, (photo_bytes, photo_nom, photo_type, projet_id))
    conn.commit()
    conn.close()


def supprimer_projet(projet_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM projets WHERE id=?", (projet_id,))
    c.execute("DELETE FROM factures WHERE projet_id=?", (projet_id,))
    conn.commit()
    conn.close()


def droit_projet(projet_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        SELECT surface, budget, phase_ordre, version_id FROM projets WHERE id=?
    """, (projet_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return 0.0
    return droit_a_facturer(*row)


# ─────────────────────────────────────────────
# FACTURES
# ─────────────────────────────────────────────

def generer_numero_facture():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    annee = datetime.now().year
    c.execute("""
        SELECT COUNT(*) FROM factures
        WHERE numero LIKE ?
    """, (f"{annee}-%",))
    count = c.fetchone()[0]
    conn.close()
    return f"{annee}-{count+1:03d}"


def creer_facture(projet_id, phase_ordre, type_nom, montant, date_emission, date_prevue):
    numero = generer_numero_facture()
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO factures (
            projet_id, phase_ordre, type_nom, montant,
            date_emission, date_prevue, payee, numero
        )
        VALUES (?, ?, ?, ?, ?, ?, 0, ?)
    """, (projet_id, phase_ordre, type_nom, montant, date_emission, date_prevue, numero))
    conn.commit()
    conn.close()
    return numero


def liste_factures(projet_id=None):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    if projet_id:
        c.execute("""
            SELECT f.id, f.numero, p.nom, f.phase_ordre, f.type_nom,
                   f.montant, f.date_emission, f.date_prevue, f.date_paiement, f.payee
            FROM factures f
            JOIN projets p ON f.projet_id = p.id
            WHERE f.projet_id = ?
            ORDER BY f.date_emission DESC
        """, (projet_id,))
    else:
        c.execute("""
            SELECT f.id, f.numero, p.nom, f.phase_ordre, f.type_nom,
                   f.montant, f.date_emission, f.date_prevue, f.date_paiement, f.payee
            FROM factures f
            JOIN projets p ON f.projet_id = p.id
            ORDER BY f.date_emission DESC
        """)
    rows = c.fetchall()
    conn.close()
    return rows


def marquer_facture_payee(facture_id, date_paiement):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        UPDATE factures SET payee=1, date_paiement=?
        WHERE id=?
    """, (date_paiement, facture_id))
    conn.commit()
    conn.close()


def total_facture_projet(projet_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT SUM(montant) FROM factures WHERE projet_id=?", (projet_id,))
    total = c.fetchone()[0]
    conn.close()
    return total if total else 0.0


def total_encaisse_projet(projet_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT SUM(montant) FROM factures WHERE projet_id=? AND payee=1", (projet_id,))
    total = c.fetchone()[0]
    conn.close()
    return total if total else 0.0


def supprimer_facture(facture_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM factures WHERE id=?", (facture_id,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# TRÉSORERIE
# ─────────────────────────────────────────────

def tresorerie_mensuelle(nb_mois=12):
    """
    Retourne une liste de dicts {mois, prevu, encaisse}
    - prevu : somme des factures dont date_prevue est dans ce mois
    - encaisse : somme des factures payées dont date_paiement est dans ce mois
    """
    from datetime import date
    import calendar

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    today = date.today()
    resultats = []

    for i in range(nb_mois):
        mois = (today.month - 1 + i) % 12 + 1
        annee = today.year + (today.month - 1 + i) // 12
        label = f"{annee}-{mois:02d}"

        c.execute("""
            SELECT SUM(montant) FROM factures
            WHERE strftime('%Y-%m', date_prevue) = ?
        """, (label,))
        prevu = c.fetchone()[0] or 0.0

        c.execute("""
            SELECT SUM(montant) FROM factures
            WHERE payee=1 AND strftime('%Y-%m', date_paiement) = ?
        """, (label,))
        encaisse = c.fetchone()[0] or 0.0

        resultats.append({"mois": label, "prevu": prevu, "encaisse": encaisse})

    conn.close()
    return resultats


# ─────────────────────────────────────────────
# PARAMÈTRES
# ─────────────────────────────────────────────

def get_agence():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT nom, adresse, telephone, email, siret FROM agence WHERE id=1")
    row = c.fetchone()
    conn.close()
    return row


def update_agence(nom, adresse, telephone, email, siret):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        UPDATE agence SET nom=?, adresse=?, telephone=?, email=?, siret=?
        WHERE id=1
    """, (nom, adresse, telephone, email, siret))
    conn.commit()
    conn.close()


def get_phases(version_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        SELECT id, nom, ordre, pourcentage FROM phases
        WHERE version_id=? ORDER BY ordre
    """, (version_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def update_phase(phase_id, pourcentage):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE phases SET pourcentage=? WHERE id=?", (pourcentage, phase_id))
    conn.commit()
    conn.close()


def get_regles_honoraires(version_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        SELECT id, surface_min, surface_max, taux FROM regles_honoraires
        WHERE version_id=? ORDER BY surface_min
    """, (version_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def update_regle_honoraire(regle_id, surface_min, surface_max, taux):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        UPDATE regles_honoraires SET surface_min=?, surface_max=?, taux=?
        WHERE id=?
    """, (surface_min, surface_max, taux, regle_id))
    conn.commit()
    conn.close()


def get_types_facture(version_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        SELECT id, nom, pourcentage FROM types_facture
        WHERE version_id=? ORDER BY nom
    """, (version_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def update_type_facture(type_id, pourcentage):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE types_facture SET pourcentage=? WHERE id=?", (pourcentage, type_id))
    conn.commit()
    conn.close()
