import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date, timedelta
import plotly.graph_objects as go
from PIL import Image, ImageOps
import io
import base64
import calendar

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="ArchiGest", layout="wide", page_icon="🏛️")

DB_PATH = "archigest.db"

PHASES = ["ESQ", "APS", "APD", "PRO", "DET", "AOR"]
PHASE_COLORS = {
    "ESQ": "#4A90D9", "APS": "#7B68EE", "APD": "#50C878",
    "PRO": "#FFB347", "DET": "#FF6B6B", "AOR": "#40E0D0"
}
JALONS = [
    ("acompte",       "Acompte démarrage",     0.30),
    ("intermediaire", "Paiement intermédiaire", 0.40),
    ("solde",         "Solde",                 0.30),
]
DUREES_DEFAUT = {
    "ESQ": 4, "APS": 4, "APD": 4, "PRO": 8, "DET": 32, "AOR": 4
}  # en semaines

# ─────────────────────────────────────────────────────────────────────────────
# BASE DE DONNÉES
# ─────────────────────────────────────────────────────────────────────────────
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS projets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT,
            client TEXT,
            lieu TEXT,
            surface REAL,
            budget REAL,
            phase_actuelle TEXT,
            honoraires_total REAL,
            photo BLOB,
            archive INTEGER DEFAULT 0,
            archive_annee INTEGER,
            date_debut_mission TEXT,
            phases_selectionnees TEXT
        )
    """)

    existing_proj = [r[1] for r in c.execute("PRAGMA table_info(projets)").fetchall()]
    for col, typ in [
        ("date_debut_mission",   "TEXT"),
        ("phases_selectionnees", "TEXT"),
    ]:
        if col not in existing_proj:
            c.execute(f"ALTER TABLE projets ADD COLUMN {col} {typ}")

    c.execute("""
        CREATE TABLE IF NOT EXISTS phases_gantt (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            projet_id INTEGER,
            phase TEXT,
            date_debut TEXT,
            duree_mois INTEGER DEFAULT 2,
            active INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS jalons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            projet_id INTEGER,
            phase TEXT,
            type_jalon TEXT,
            libelle TEXT,
            montant REAL,
            statut TEXT DEFAULT 'attente',
            date_paiement TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS charges_fixes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            libelle TEXT,
            montant_mensuel REAL,
            actif INTEGER DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS regles_honoraires (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            surface_min REAL,
            surface_max REAL,
            taux REAL,
            actif INTEGER DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS repartition_phases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT DEFAULT 'v1',
            phase TEXT,
            pourcentage REAL,
            duree_semaines INTEGER
        )
    """)

    # Initialisation des règles honoraires si vide
    if c.execute("SELECT COUNT(*) FROM regles_honoraires").fetchone()[0] == 0:
        regles = [
            (0,     500,   0.12),
            (500,   1000,  0.10),
            (1000,  3000,  0.08),
            (3000,  10000, 0.06),
            (10000, 999999,0.05),
        ]
        c.executemany(
            "INSERT INTO regles_honoraires (surface_min,surface_max,taux) VALUES (?,?,?)", regles
        )

    # Initialisation répartition phases si vide
    if c.execute("SELECT COUNT(*) FROM repartition_phases").fetchone()[0] == 0:
        repartition = [
            ("ESQ", 0.08, 4),
            ("APS", 0.10, 4),
            ("APD", 0.12, 4),
            ("PRO", 0.20, 8),
            ("DET", 0.40, 32),
            ("AOR", 0.10, 4),
        ]
        c.executemany(
            "INSERT INTO repartition_phases (version,phase,pourcentage,duree_semaines) VALUES ('v1',?,?,?)",
            repartition
        )

    conn.commit()
    conn.close()

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def fmt(montant):
    devise = st.session_state.get("devise", "MGA")
    if devise == "EUR":
        taux = st.session_state.get("taux_change", 4500)
        return f"{montant/taux:,.0f} €"
    return f"{montant:,.0f} Mga"

def get_repartition():
    conn = get_conn()
    df = pd.read_sql(
        "SELECT phase, pourcentage, duree_semaines FROM repartition_phases WHERE version='v1'", conn
    )
    conn.close()
    return {r["phase"]: {"pct": r["pourcentage"], "semaines": r["duree_semaines"]} for _, r in df.iterrows()}

def calc_honoraires(surface, budget):
    conn = get_conn()
    regles = pd.read_sql(
        "SELECT * FROM regles_honoraires WHERE actif=1 ORDER BY surface_min", conn
    )
    conn.close()
    for _, r in regles.iterrows():
        if r["surface_min"] <= surface < r["surface_max"]:
            return budget * r["taux"]
    return budget * 0.08

def create_jalons_phase(projet_id, phase, honoraires_total, phases_sel):
    repartition = get_repartition()
    pct_phase   = repartition.get(phase, {}).get("pct", 1/len(phases_sel))
    montant_phase = honoraires_total * pct_phase
    conn = get_conn()
    c    = conn.cursor()
    for typ, lib, part in JALONS:
        c.execute(
            "INSERT INTO jalons (projet_id,phase,type_jalon,libelle,montant,statut) VALUES (?,?,?,?,?,?)",
            (projet_id, phase, typ, lib, montant_phase * part, "attente")
        )
    conn.commit()
    conn.close()

def check_phase_progression(projet_id):
    conn = get_conn()
    c    = conn.cursor()
    c.execute(
        "SELECT phase_actuelle, honoraires_total, phases_selectionnees FROM projets WHERE id=?",
        (projet_id,)
    )
    row = c.fetchone()
    if not row:
        conn.close(); return
    phase_actuelle, honoraires_total, phases_sel_str = row
    phases_sel = phases_sel_str.split(",") if phases_sel_str else PHASES

    c.execute(
        "SELECT COUNT(*) FROM jalons WHERE projet_id=? AND phase=? AND statut='payé'",
        (projet_id, phase_actuelle)
    )
    if c.fetchone()[0] >= 3:
        idx = phases_sel.index(phase_actuelle) if phase_actuelle in phases_sel else -1
        if idx >= 0 and idx < len(phases_sel) - 1:
            next_phase = phases_sel[idx + 1]
            c.execute("UPDATE projets SET phase_actuelle=? WHERE id=?", (next_phase, projet_id))
            conn.commit(); conn.close()
            create_jalons_phase(projet_id, next_phase, honoraires_total, phases_sel)
            return
    conn.commit()
    conn.close()

def photo_to_bw_b64(blob, size=(200, 140)):
    try:
        img = Image.open(io.BytesIO(blob)).convert("L")
        img.thumbnail(size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    except:
        return None

# ─────────────────────────────────────────────────────────────────────────────
# CALCUL DATES GANTT
# ─────────────────────────────────────────────────────────────────────────────
def recalc_dates_gantt(projet_id):
    conn = get_conn()
    c    = conn.cursor()
    c.execute("SELECT date_debut_mission FROM projets WHERE id=?", (projet_id,))
    row = c.fetchone()
    if not row or not row[0]:
        conn.close(); return
    date_ref = datetime.strptime(row[0], "%Y-%m-%d").date()

    c.execute(
        "SELECT phase, duree_mois FROM phases_gantt WHERE projet_id=? ORDER BY id", (projet_id,)
    )
    phases_dict = {ph: dur for ph, dur in c.fetchall()}

    curseur = date_ref
    for phase in PHASES:
        duree = phases_dict.get(phase, DUREES_DEFAUT.get(phase, 2))
        c.execute(
            "UPDATE phases_gantt SET date_debut=? WHERE projet_id=? AND phase=?",
            (curseur.isoformat(), projet_id, phase)
        )
        curseur = curseur + timedelta(days=duree * 30)

    conn.commit()
    conn.close()

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
def sidebar():
    with st.sidebar:
        st.title("🏛️ ArchiGest")
        st.divider()
        page = st.radio("Navigation", [
            "🏠 Dashboard", "📁 Projets", "📅 Gantt", "💰 Trésorerie", "⚙️ Paramètres"
        ])
        st.divider()
        st.caption("Devise")
        devise = st.selectbox(
            "Devise", ["MGA", "EUR"],
            index=0 if st.session_state.get("devise", "MGA") == "MGA" else 1,
            label_visibility="collapsed"
        )
        st.session_state["devise"] = devise
        if devise == "EUR":
            taux = st.number_input(
                "Taux MGA→EUR",
                value=st.session_state.get("taux_change", 4500), step=100
            )
            st.session_state["taux_change"] = taux
    return page

# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
def page_dashboard():
    st.title("📊 Dashboard")

    conn      = get_conn()
    projets   = pd.read_sql("SELECT * FROM projets WHERE archive=0", conn)
    jalons_df = pd.read_sql("SELECT * FROM jalons", conn)
    charges_df= pd.read_sql("SELECT * FROM charges_fixes WHERE actif=1", conn)
    conn.close()

    total_charges = charges_df["montant_mensuel"].sum() if not charges_df.empty else 0
    ca_total      = projets["honoraires_total"].sum() if not projets.empty else 0
    ca_encaisse   = jalons_df[jalons_df.statut == "payé"]["montant"].sum() if not jalons_df.empty else 0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("📁 Projets actifs",        len(projets))
    k2.metric("💰 CA total prévu",        fmt(ca_total))
    k3.metric("✅ CA encaissé",           fmt(ca_encaisse))
    k4.metric("📉 Charges fixes / mois",  fmt(total_charges))

    st.divider()

    # Alertes acomptes
    if not jalons_df.empty:
        alertes = jalons_df[(jalons_df.type_jalon == "acompte") & (jalons_df.statut == "attente")]
        if not alertes.empty:
            st.subheader("🔔 Alertes — Acomptes en attente")
            for _, a in alertes.iterrows():
                proj = projets[projets.id == a.projet_id]
                if not proj.empty:
                    st.warning(
                        f"⚠️ **{proj.iloc[0]['nom']}** — Phase **{a.phase}** — "
                        f"Acompte démarrage en attente : {fmt(a.montant)}"
                    )

    st.divider()
    st.subheader("📋 Projets en cours")
    if projets.empty:
        st.info("Aucun projet actif.")
    else:
        for _, proj in projets.iterrows():
            pid   = proj["id"]
            pj    = jalons_df[jalons_df.projet_id == pid] if not jalons_df.empty else pd.DataFrame()
            enc   = pj[pj.statut == "payé"]["montant"].sum() if not pj.empty else 0
            total = proj["honoraires_total"] or 0
            pct   = int(enc / total * 100) if total > 0 else 0
            st.markdown(f"**{proj['nom']}** — Phase : `{proj['phase_actuelle']}` — {fmt(enc)} / {fmt(total)}")
            st.progress(pct)

# ─────────────────────────────────────────────────────────────────────────────
# PROJETS
# ─────────────────────────────────────────────────────────────────────────────
def page_projets():
    st.title("📁 Projets")
    tab_actifs, tab_nouveau, tab_archives = st.tabs(
        ["📋 Projets actifs", "➕ Nouveau projet", "🗂️ Archives"]
    )

    # ── TAB : PROJETS ACTIFS ──────────────────────────────────────────────────
    with tab_actifs:
        conn      = get_conn()
        projets   = pd.read_sql("SELECT * FROM projets WHERE archive=0 ORDER BY nom", conn)
        jalons_df = pd.read_sql("SELECT * FROM jalons", conn)
        conn.close()

        if projets.empty:
            st.info("Aucun projet actif. Créez-en un dans l'onglet 'Nouveau projet'.")
        else:
            for _, proj in projets.iterrows():
                pid = proj["id"]
                with st.expander(f"📌 {proj['nom']} — {proj['phase_actuelle']}", expanded=False):
                    col_info, col_photo = st.columns([3, 1])
                    with col_info:
                        st.markdown(f"**Client :** {proj['client'] or '—'}")
                        st.markdown(f"**Lieu :** {proj['lieu'] or '—'}")
                        st.markdown(f"**Surface :** {proj['surface']} m²")
                        st.markdown(f"**Budget travaux :** {fmt(proj['budget'])}")
                        st.markdown(f"**Honoraires totaux :** {fmt(proj['honoraires_total'])}")
                        st.markdown(f"**Phase actuelle :** `{proj['phase_actuelle']}`")
                    with col_photo:
                        if proj["photo"]:
                            b64 = photo_to_bw_b64(proj["photo"])
                            if b64:
                                st.markdown(
                                    f'<img src="data:image/png;base64,{b64}" '
                                    f'style="width:100%;border-radius:8px;">',
                                    unsafe_allow_html=True
                                )

                    st.markdown("---")
                    # Jalons
                    pj = jalons_df[jalons_df.projet_id == pid]
                    if not pj.empty:
                        st.markdown("**Jalons de paiement :**")
                        for _, j in pj.iterrows():
                            c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
                            c1.write(f"{j['phase']} — {j['libelle']}")
                            c2.write(fmt(j["montant"]))
                            statut_color = "🟢" if j["statut"] == "payé" else "🔴"
                            c3.write(f"{statut_color} {j['statut']}")
                            if j["statut"] == "attente":
                                if c4.button("✅ Marquer payé", key=f"pay_{j['id']}"):
                                    conn = get_conn()
                                    conn.execute(
                                        "UPDATE jalons SET statut='payé', date_paiement=? WHERE id=?",
                                        (date.today().isoformat(), j["id"])
                                    )
                                    conn.commit(); conn.close()
                                    check_phase_progression(pid)
                                    st.rerun()

                    st.markdown("---")
                    col_arch, col_del = st.columns(2)
                    if col_arch.button("🗂️ Archiver", key=f"arch_{pid}"):
                        conn = get_conn()
                        conn.execute(
                            "UPDATE projets SET archive=1, archive_annee=? WHERE id=?",
                            (date.today().year, pid)
                        )
                        conn.commit(); conn.close()
                        st.success(f"Projet '{proj['nom']}' archivé.")
                        st.rerun()
                    if col_del.button("🗑️ Supprimer", key=f"sup_{pid}"):
                        conn = get_conn()
                        conn.execute("DELETE FROM projets WHERE id=?", (pid,))
                        conn.execute("DELETE FROM jalons WHERE projet_id=?", (pid,))
                        conn.execute("DELETE FROM phases_gantt WHERE projet_id=?", (pid,))
                        conn.commit(); conn.close()
                        st.success(f"Projet '{proj['nom']}' supprimé.")
                        st.rerun()

    # ── TAB : NOUVEAU PROJET ──────────────────────────────────────────────────
    with tab_nouveau:
        st.subheader("➕ Créer un nouveau projet")
        with st.form("form_nouveau_projet"):
            nom        = st.text_input("Nom du projet *")
            client     = st.text_input("Client")
            lieu       = st.text_input("Lieu")
            surface    = st.number_input("Surface (m²)", min_value=0.0, value=100.0)
            budget     = st.number_input("Budget travaux (Mga)", min_value=0.0, value=50000000.0)
            phases_sel = st.multiselect(
                "Phases de mission *", PHASES, default=PHASES,
                help="Sélectionnez uniquement les phases qui font partie de la mission"
            )
            phase_init = st.selectbox(
                "Phase de démarrage", phases_sel if phases_sel else PHASES
            )
            date_debut = st.date_input("Date de début de mission", value=date.today())
            photo      = st.file_uploader("Photo du projet", type=["jpg", "jpeg", "png"])
            submitted  = st.form_submit_button("✅ Créer le projet")

        if submitted and nom and phases_sel:
            honoraires     = calc_honoraires(surface, budget)
            photo_data     = photo.read() if photo else None
            phases_sel_str = ",".join(phases_sel)

            conn = get_conn()
            c    = conn.cursor()
            c.execute("""
                INSERT INTO projets
                    (nom, client, lieu, surface, budget, phase_actuelle,
                     honoraires_total, photo, date_debut_mission, phases_selectionnees)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (nom, client, lieu, surface, budget, phase_init,
                  honoraires, photo_data, date_debut.isoformat(), phases_sel_str))
            pid = c.lastrowid

            repartition = get_repartition()
            curseur = date_debut
            for phase in PHASES:
                duree_sem  = repartition.get(phase, {}).get("semaines", DUREES_DEFAUT[phase])
                duree_mois = max(1, round(duree_sem / 4))
                active     = 1 if phase == phase_init else 0
                c.execute(
                    "INSERT INTO phases_gantt (projet_id,phase,date_debut,duree_mois,active) VALUES (?,?,?,?,?)",
                    (pid, phase, curseur.isoformat(), duree_mois, active)
                )
                curseur = curseur + timedelta(days=duree_sem * 7)

            conn.commit(); conn.close()
            create_jalons_phase(pid, phase_init, honoraires, phases_sel)
            st.success(f"✅ Projet **{nom}** créé ! Honoraires : {fmt(honoraires)}")
            st.rerun()
        elif submitted:
            st.error("Veuillez renseigner le nom et sélectionner au moins une phase.")

    # ── TAB : ARCHIVES ────────────────────────────────────────────────────────
    with tab_archives:
        conn     = get_conn()
        archives = pd.read_sql(
            "SELECT * FROM projets WHERE archive=1 ORDER BY archive_annee DESC, nom", conn
        )
        conn.close()

        if archives.empty:
            st.info("Aucun projet archivé.")
        else:
            annees = sorted(archives["archive_annee"].dropna().unique(), reverse=True)
            for annee in annees:
                st.subheader(f"📅 {int(annee)}")
                ann_projs = archives[archives.archive_annee == annee]
                for _, proj in ann_projs.iterrows():
                    pid = proj["id"]
                    col_nom, col_rest, col_del = st.columns([4, 1, 1])
                    col_nom.markdown(
                        f"**{proj['nom']}** — {proj['lieu'] or '—'} | {proj['client'] or '—'}"
                    )
                    if col_rest.button("↩️ Restaurer", key=f"rest_{pid}"):
                        conn = get_conn()
                        conn.execute(
                            "UPDATE projets SET archive=0, archive_annee=NULL WHERE id=?", (pid,)
                        )
                        conn.commit(); conn.close()
                        st.success(f"Projet '{proj['nom']}' restauré.")
                        st.rerun()
                    if col_del.button("🗑️ Supprimer", key=f"del_{pid}"):
                        conn = get_conn()
                        conn.execute("DELETE FROM projets WHERE id=?", (pid,))
                        conn.execute("DELETE FROM jalons WHERE projet_id=?", (pid,))
                        conn.execute("DELETE FROM phases_gantt WHERE projet_id=?", (pid,))
                        conn.commit(); conn.close()
                        st.success(f"Projet '{proj['nom']}' supprimé définitivement.")
                        st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# GANTT
# ─────────────────────────────────────────────────────────────────────────────
def page_gantt():
    st.title("📅 Gantt")

    conn      = get_conn()
    projets   = pd.read_sql("SELECT * FROM projets WHERE archive=0", conn)
    gantt_df  = pd.read_sql("SELECT * FROM phases_gantt", conn)
    jalons_df = pd.read_sql("SELECT * FROM jalons", conn)
    conn.close()

    if projets.empty:
        st.info("Aucun projet actif.")
        return

    echelle = st.radio("Échelle", ["Semaine", "Mois", "Année"], horizontal=True)
    today   = date.today()
    fig     = go.Figure()

    for _, proj in projets.iterrows():
        pid            = proj["id"]
        phase_actuelle = proj["phase_actuelle"]
        proj_gantt     = gantt_df[gantt_df.projet_id == pid]

        for _, g in proj_gantt.iterrows():
            phase = g["phase"]
            try:
                debut = datetime.strptime(g["date_debut"], "%Y-%m-%d").date()
            except:
                debut = today

            acompte_paye = jalons_df[
                (jalons_df.projet_id == pid) &
                (jalons_df.phase == phase) &
                (jalons_df.type_jalon == "acompte") &
                (jalons_df.statut == "payé")
            ]
            if not acompte_paye.empty and acompte_paye.iloc[0]["date_paiement"]:
                debut = datetime.strptime(
                    acompte_paye.iloc[0]["date_paiement"], "%Y-%m-%d"
                ).date()

            fin     = debut + timedelta(days=int(g["duree_mois"]) * 30)
            color   = PHASE_COLORS.get(phase, "#888")
            opacity = 1.0 if phase == phase_actuelle else 0.45

            def to_unit(d):
                delta = (d - today).days
                if echelle == "Semaine": return delta / 7
                if echelle == "Mois":   return delta / 30
                return delta / 365

            x0, x1 = to_unit(debut), to_unit(fin)

            fig.add_trace(go.Bar(
                x=[x1 - x0],
                y=[f"{proj['nom']} — {phase}"],
                base=[x0],
                orientation="h",
                marker=dict(color=color, opacity=opacity),
                name=phase,
                hovertemplate=(
                    f"<b>{proj['nom']}</b><br>Phase : {phase}<br>"
                    f"Début : {debut}<br>Fin : {fin}<extra></extra>"
                ),
                showlegend=False,
            ))

    x_label = {"Semaine": "Semaines", "Mois": "Mois", "Année": "Années"}[echelle]
    fig.add_vline(x=0, line_color="red", line_dash="dash", annotation_text="Aujourd'hui")
    fig.update_layout(
        barmode="overlay",
        height=max(350, len(projets) * len(PHASES) * 35),
        xaxis_title=x_label,
        showlegend=False,
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="white"),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("##### Légende des phases")
    cols = st.columns(len(PHASES))
    for i, ph in enumerate(PHASES):
        color = PHASE_COLORS[ph]
        cols[i].markdown(
            f'<div style="background:{color};border-radius:6px;padding:6px 10px;'
            f'text-align:center;color:white;font-weight:bold;">{ph}</div>',
            unsafe_allow_html=True
        )

    alertes = jalons_df[(jalons_df.type_jalon == "acompte") & (jalons_df.statut == "attente")]
    if not alertes.empty:
        st.divider()
        st.subheader("🔔 Acomptes en attente")
        for _, a in alertes.iterrows():
            proj = projets[projets.id == a.projet_id]
            if not proj.empty:
                st.warning(
                    f"⚠️ **{proj.iloc[0]['nom']}** — Phase **{a.phase}** — "
                    f"Acompte en attente : {fmt(a.montant)}"
                )

# ─────────────────────────────────────────────────────────────────────────────
# TRÉSORERIE
# ─────────────────────────────────────────────────────────────────────────────
def page_tresorerie():
    st.title("💰 Trésorerie")

    conn       = get_conn()
    jalons_df  = pd.read_sql("SELECT * FROM jalons", conn)
    charges_df = pd.read_sql("SELECT * FROM charges_fixes WHERE actif=1", conn)
    conn.close()

    total_charges = charges_df["montant_mensuel"].sum() if not charges_df.empty else 0
    today = date.today()

    mois_data = []
    for i in range(12):
        y = today.year + (today.month - 1 + i) // 12
        m = (today.month - 1 + i) % 12 + 1
        label        = f"{y}-{m:02d}"
        label_affich = datetime(y, m, 1).strftime("%b %Y")

        if not jalons_df.empty:
            recettes_reelles = jalons_df[
                (jalons_df.statut == "payé") &
                (jalons_df.date_paiement.str[:7] == label)
            ]["montant"].sum()
            recettes_prevues = jalons_df[jalons_df.statut == "attente"]["montant"].sum() / 12
        else:
            recettes_reelles = 0
            recettes_prevues = 0

        mois_data.append({
            "Mois":               label_affich,
            "Recettes prévues":   recettes_prevues,
            "CA Réel (encaissé)": recettes_reelles,
            "Dépenses":           total_charges,
            "Solde":              recettes_reelles - total_charges,
            "Seuil rentabilité":  total_charges,
        })

    df_treso = pd.DataFrame(mois_data)

    k1, k2, k3 = st.columns(3)
    k1.metric("CA total prévu (12 mois)", fmt(df_treso["Recettes prévues"].sum()))
    k2.metric("CA réel encaissé",         fmt(df_treso["CA Réel (encaissé)"].sum()))
    k3.metric("Charges fixes / mois",     fmt(total_charges))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df_treso["Mois"], y=df_treso["CA Réel (encaissé)"],
        name="Encaissé", marker_color="#50C878"
    ))
    fig.add_trace(go.Scatter(
        x=df_treso["Mois"], y=df_treso["Recettes prévues"],
        name="Prévu", mode="lines+markers", line=dict(color="#4A90D9", dash="dot")
    ))
    fig.add_trace(go.Scatter(
        x=df_treso["Mois"], y=df_treso["Seuil rentabilité"],
        name="Seuil rentabilité", mode="lines",
        line=dict(color="#FF6B6B", dash="dash")
    ))
    fig.update_layout(
        plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
        font=dict(color="white"), height=400,
        legend=dict(orientation="h", yanchor="bottom", y=1.02)
    )
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(df_treso, use_container_width=True)

    st.divider()
    st.subheader("📋 Charges fixes")
    if not charges_df.empty:
        for _, ch in charges_df.iterrows():
            col1, col2, col3 = st.columns([4, 2, 1])
            col1.write(ch["libelle"])
            col2.write(fmt(ch["montant_mensuel"]))
            if col3.button("🗑️", key=f"del_ch_{ch['id']}"):
                conn = get_conn()
                conn.execute("UPDATE charges_fixes SET actif=0 WHERE id=?", (ch["id"],))
                conn.commit(); conn.close()
                st.rerun()

    with st.expander("➕ Ajouter une charge fixe"):
        with st.form("form_charge"):
            lib = st.text_input("Libellé")
            mnt = st.number_input("Montant mensuel (Mga)", min_value=0.0)
            if st.form_submit_button("Ajouter"):
                conn = get_conn()
                conn.execute(
                    "INSERT INTO charges_fixes (libelle,montant_mensuel) VALUES (?,?)", (lib, mnt)
                )
                conn.commit(); conn.close()
                st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# PARAMÈTRES
# ─────────────────────────────────────────────────────────────────────────────
def page_parametres():
    st.title("⚙️ Paramètres")
    tab1, tab2 = st.tabs(["📐 Règles honoraires", "📊 Répartition phases"])

    with tab1:
        conn = get_conn()
        df   = pd.read_sql("SELECT * FROM regles_honoraires WHERE actif=1", conn)
        conn.close()
        st.subheader("Barème des taux")
        st.dataframe(df[["surface_min", "surface_max", "taux"]], use_container_width=True)
        st.caption("Édition complète : prochaine version.")

    with tab2:
        conn = get_conn()
        df   = pd.read_sql(
            "SELECT id, phase, pourcentage, duree_semaines FROM repartition_phases WHERE version='v1'",
            conn
        )
        conn.close()

        st.subheader("Répartition honoraires & durées par phase")
        st.caption(
            "**Pourcentage** : part des honoraires totaux par phase. "
            "**Durée (semaines)** : durée type utilisée au Gantt."
        )

        with st.form("form_repartition"):
            rows  = []
            cols_h = st.columns([2, 3, 3])
            cols_h[0].markdown("**Phase**")
            cols_h[1].markdown("**% honoraires**")
            cols_h[2].markdown("**Durée (semaines)**")

            for _, row in df.iterrows():
                c0, c1, c2 = st.columns([2, 3, 3])
                c0.markdown(f"**{row['phase']}**")
                pct = c1.number_input(
                    f"% {row['phase']}", value=float(row["pourcentage"]),
                    min_value=0.0, max_value=1.0, step=0.01,
                    format="%.2f", label_visibility="collapsed",
                    key=f"pct_{row['id']}"
                )
                dur = c2.number_input(
                    f"sem {row['phase']}", value=int(row["duree_semaines"]),
                    min_value=1, step=1,
                    label_visibility="collapsed",
                    key=f"dur_{row['id']}"
                )
                rows.append((row["id"], pct, dur))

            saved = st.form_submit_button("💾 Enregistrer")

        if saved:
            total_pct = sum(r[1] for r in rows)
            if abs(total_pct - 1.0) > 0.01:
                st.error(f"La somme des pourcentages doit être 1.00 (actuellement {total_pct:.2f}).")
            else:
                conn = get_conn()
                for rid, pct, dur in rows:
                    conn.execute(
                        "UPDATE repartition_phases SET pourcentage=?, duree_semaines=? WHERE id=?",
                        (pct, dur, rid)
                    )
                conn.commit(); conn.close()
                st.success("✅ Répartition mise à jour.")
                st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    init_db()
    page = sidebar()
    if "nav" in st.session_state:
        page = st.session_state.pop("nav")
    if   page == "🏠 Dashboard":  page_dashboard()
    elif page == "📁 Projets":    page_projets()
    elif page == "📅 Gantt":      page_gantt()
    elif page == "💰 Trésorerie": page_tresorerie()
    elif page == "⚙️ Paramètres": page_parametres()

if __name__ == "__main__":
    main()
