"""Demonstrator: natürlichsprachliche Plausibilitätsprüfung für Anträge (fingierte Daten).

Start:  streamlit run app.py
"""
import json
import os
from pathlib import Path

import networkx as nx
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from openai import APIConnectionError, APIError
from pyvis.network import Network

from rules import OFFLINE_RULES, apply_rule, rule_hit_groups, score_cases, translate_rule, translate_rule_offline

BASE = Path(__file__).parent
load_dotenv(BASE / ".env")
DEMO_FILE = BASE / "data" / "demo_antraege.xlsx"
STATUS_FILE = BASE / "data" / "review_status.json"
STATUS_OPTIONS = ["offen", "verifiziert", "möglicherweise kritisch", "Betrugsverdacht"]

EXAMPLES = list(OFFLINE_RULES)

st.set_page_config(page_title="KI-Plausibilitätsprüfung – Demonstrator", layout="wide")


# ---------------------------------------------------------------- Zustand
@st.cache_data
def load_excel(src) -> pd.DataFrame:
    df = pd.read_excel(src)
    for c in df.columns:
        if "datum" in c.lower() or "date" in c.lower():
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def load_status() -> dict:
    return json.loads(STATUS_FILE.read_text(encoding="utf-8")) if STATUS_FILE.exists() else {}


def save_status(status: dict) -> None:
    STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


st.session_state.setdefault("rules", [])
st.session_state.setdefault("pending", None)
st.session_state.setdefault("status", load_status())

# ---------------------------------------------------------------- Sidebar
with st.sidebar:
    st.header("Datenbestand")
    upload = st.file_uploader("Eigene Excel-Datei (flach, eine Zeile je Antrag)", type=["xlsx"])
    if upload is None and not DEMO_FILE.exists():
        st.error("Demo-Datei fehlt – bitte `python generate_data.py` ausführen.")
        st.stop()
    df = load_excel(upload or DEMO_FILE)
    st.caption(f"Quelle: {'Upload' if upload else DEMO_FILE.name} · {len(df)} Anträge")
    id_candidates = [c for c in df.columns if "id" in c.lower()] or list(df.columns)
    id_col = st.selectbox("ID-Spalte", df.columns, index=list(df.columns).index(id_candidates[0]))
    offline = st.toggle("Offline-Modus (ohne KI, nur Beispielregeln)", value=not os.getenv("OPENAI_API_KEY"))
    st.divider()
    st.caption("Alle Daten sind vollständig fingiert. Das Sprachmodell übersetzt nur Regeln – "
               "die Prüfung selbst läuft deterministisch und nachvollziehbar.")
    if st.button("Alle Regeln entfernen"):
        st.session_state.rules = []
        st.rerun()

st.title("Natürlichsprachliche Plausibilitätsprüfung")

tab_cases, tab_rules, tab_review, tab_graph = st.tabs(
    ["① Fallübersicht", "② Regeln formulieren", "③ Prüfliste", "④ Beziehungsgraph"])

# ---------------------------------------------------------------- 1 Fallübersicht
with tab_cases:
    c1, c2, c3 = st.columns(3)
    c1.metric("Anträge", len(df))
    c2.metric("Aktive Regeln", sum(r.get("aktiv", True) for r in st.session_state.rules))
    scored = score_cases(df, st.session_state.rules, id_col)
    c3.metric("Auffällige Anträge", len(scored))
    st.dataframe(df, width="stretch", hide_index=True,
                 column_config={c: st.column_config.DateColumn(c, format="DD.MM.YYYY")
                                for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])})

# ---------------------------------------------------------------- 2 Regeln
with tab_rules:
    st.markdown("Formulieren Sie eine Prüfregel in natürlicher Sprache. Die KI übersetzt sie in eine "
                "**sichtbare, strukturierte Regel**, die anschließend auf **alle** Anträge angewendet wird.")
    ex = st.selectbox("Beispielregel übernehmen (optional)", [""] + EXAMPLES)
    text = st.text_area("Prüfregel", value=ex, height=90,
                        placeholder="z. B. Markiere Anträge, deren Notar in mehr als 3 Anträgen vorkommt.")
    if st.button("Regel übersetzen", type="primary") and text.strip():
        with st.spinner("KI übersetzt die Regel …"):
            try:
                st.session_state.pending = (translate_rule_offline(text, df) if offline
                                            else translate_rule(text, df, id_col))
            except (APIError, APIConnectionError) as e:
                try:  # Fallback, damit die Demo auch ohne API-Zugang läuft
                    st.session_state.pending = translate_rule_offline(text, df)
                    st.warning(f"KI nicht erreichbar ({type(e).__name__}) – vorbereitete Übersetzung verwendet.")
                except ValueError:
                    st.session_state.pending = None
                    st.error(f"KI nicht erreichbar: {e}")
            except Exception as e:  # noqa: BLE001 – Demo: Fehler direkt anzeigen
                st.session_state.pending = None
                st.error(f"Regel konnte nicht übersetzt werden: {e}")

    rule = st.session_state.pending
    if rule:
        if not rule.get("umsetzbar", True):
            st.warning(f"Nicht umsetzbar: {rule.get('erklaerung')}")
        else:
            st.subheader(f"Verstandene Regel: {rule['titel']}")
            st.info(rule["erklaerung"])
            left, right = st.columns([1, 2])
            with left:
                st.caption("Strukturierte Regel (wird deterministisch ausgeführt)")
                st.json({k: rule[k] for k in ("typ", "params", "filter") if k in rule})
                rule["gewicht"] = st.slider("Gewicht für den Score", 1, 5, int(rule.get("gewicht", 3)))
            with right:
                preview = apply_rule(rule, df, id_col)
                st.caption(f"Vorschau: {preview[id_col].nunique()} Anträge betroffen")
                st.dataframe(preview.drop(columns="gruppe"), hide_index=True, width="stretch")
            if st.button("✔ Regel in Regelwerk übernehmen"):
                st.session_state.rules.append({**rule, "aktiv": True})
                st.session_state.pending = None
                st.rerun()

    st.divider()
    st.subheader("Aktives Regelwerk")
    if not st.session_state.rules:
        st.caption("Noch keine Regeln übernommen.")
    for i, r in enumerate(st.session_state.rules):
        with st.expander(f"{'🟢' if r.get('aktiv', True) else '⚪'} {r['titel']}  ·  Gewicht {r['gewicht']}"):
            st.write(f"*Eingabe:* „{r['eingabe']}“")
            st.write(r["erklaerung"])
            st.json({k: r[k] for k in ("typ", "params", "filter") if k in r})
            a, b = st.columns(2)
            r["aktiv"] = a.toggle("aktiv", value=r.get("aktiv", True), key=f"act{i}")
            if b.button("Löschen", key=f"del{i}"):
                st.session_state.rules.pop(i)
                st.rerun()

# ---------------------------------------------------------------- 3 Prüfliste
with tab_review:
    scored = score_cases(df, st.session_state.rules, id_col)
    if scored.empty:
        st.info("Noch keine Treffer – bitte zuerst Regeln im Reiter ② anlegen.")
    else:
        st.markdown("Anträge sortiert nach Auffälligkeit. Prüfen Sie die Fälle einzeln und setzen Sie einen Status.")
        status = st.session_state.status
        view = scored.merge(df, on=id_col, how="left")
        view.insert(1, "Status", view[id_col].map(lambda x: status.get(str(x), {}).get("status", "offen")))
        view.insert(2, "Kommentar", view[id_col].map(lambda x: status.get(str(x), {}).get("kommentar", "")))
        edited = st.data_editor(
            view, hide_index=True, width="stretch",
            disabled=[c for c in view.columns if c not in ("Status", "Kommentar")],
            column_config={
                "Status": st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS, required=True),
                "Score": st.column_config.ProgressColumn("Score", min_value=0,
                                                         max_value=int(scored["Score"].max()), format="%d"),
                "Begründung": st.column_config.TextColumn("Begründung", width="large"),
                **{c: st.column_config.DateColumn(c, format="DD.MM.YYYY")
                   for c in view.columns if pd.api.types.is_datetime64_any_dtype(view[c])},
            },
        )
        new_status = {str(r[id_col]): {"status": r["Status"], "kommentar": r["Kommentar"] or ""}
                      for _, r in edited.iterrows()
                      if r["Status"] != "offen" or (r["Kommentar"] or "")}
        merged = {k: v for k, v in status.items() if k not in set(edited[id_col].astype(str))} | new_status
        if merged != status:
            st.session_state.status = merged
            save_status(merged)

        counts = edited["Status"].value_counts()
        st.caption(" · ".join(f"{s}: {counts.get(s, 0)}" for s in STATUS_OPTIONS))
        st.download_button("Prüfliste als CSV exportieren",
                           edited.to_csv(index=False, sep=";").encode("utf-8-sig"),
                           "pruefliste.csv", "text/csv")

        st.subheader("Einzelfall")
        pick = st.selectbox("Antrag", edited[id_col])
        row = edited[edited[id_col] == pick].iloc[0]
        st.markdown(f"**Score {row['Score']}** – ausgelöste Regeln: {row['Regeln']}")
        st.markdown(row["Begründung"].replace("\n", "  \n"))

# ---------------------------------------------------------------- 4 Graph
with tab_graph:
    default = [c for c in ["Mutter", "Vorfahr", "Notar", "Auslandsvertretung"] if c in df.columns]
    text_cols = [c for c in df.columns if c != id_col and not pd.api.types.is_datetime64_any_dtype(df[c])
                 and not pd.api.types.is_numeric_dtype(df[c])]
    ents = st.multiselect("Entitäten im Graphen", text_cols, default=[c for c in default if c in text_cols])
    label_col = "Antragsteller" if "Antragsteller" in df.columns else id_col
    flagged_ids = set(score_cases(df, st.session_state.rules, id_col)[id_col])
    flagged_groups = rule_hit_groups(df, st.session_state.rules, id_col)
    palette = ["#4c78a8", "#72b7b2", "#b279a2", "#9d755d", "#54a24b", "#eeca3b"]

    G = nx.Graph()
    for _, r in df.iterrows():
        aid = str(r[id_col])
        G.add_node(aid, label=str(r[label_col]), title=f"{aid}\n{r[label_col]}", shape="dot", size=10,
                   color="#d62728" if r[id_col] in flagged_ids else "#9e9e9e")
        for j, c in enumerate(ents):
            if pd.isna(r[c]):
                continue
            nid = f"{c}: {r[c]}"
            hot = nid in flagged_groups
            G.add_node(nid, label=str(r[c]), title=nid, shape="diamond" if hot else "box",
                       color="#d62728" if hot else palette[j % len(palette)], size=22 if hot else 14,
                       font={"color": "#ffffff" if not hot else "#000000"})
            G.add_edge(aid, nid, title=c, color="#d62728" if hot else "#cccccc")
    for n in G.nodes:  # Größe nach Vernetzung (Blumen-Muster sichtbar machen)
        if not n.startswith(tuple(f"{c}:" for c in ents)):
            continue
        G.nodes[n]["size"] = G.nodes[n]["size"] + 2 * G.degree(n)

    st.caption("Rot = von einer aktiven Regel betroffen. Große Knoten = viele verknüpfte Anträge.")
    net = Network(height="680px", width="100%", bgcolor="#ffffff", cdn_resources="in_line")
    net.from_nx(G)
    net.barnes_hut(gravity=-6000, spring_length=120)
    st.iframe(net.generate_html(), height=700)
