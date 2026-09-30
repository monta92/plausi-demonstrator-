"""Regel-Engine: natürlichsprachliche Regel -> strukturierte Regel (LLM) -> deterministische Prüfung.

Das LLM bewertet keine einzelnen Anträge. Es übersetzt lediglich einen deutschen Satz
in eine Regel aus einem festen, kleinen Regelkatalog. Die Regel wird angezeigt und
anschließend rein deterministisch mit pandas auf alle Anträge angewendet.
"""
import json
import os

import pandas as pd
from openai import OpenAI

OPERATORS = {">", ">=", "<", "<=", "==", "!=", "enthaelt", "in"}
RULE_TYPES = {"gruppen_anzahl", "gruppen_ausreisser", "datumsabstand", "altersdifferenz", "feldvergleich"}

SYSTEM_PROMPT = """Du übersetzt Prüfregeln von Sachbearbeitenden (deutsch, natürliche Sprache)
in eine strukturierte, deterministisch ausführbare Regel. Du bewertest KEINE Daten.

Datenbestand: eine flache Tabelle, eine Zeile = ein Antrag. Verknüpfungen zwischen Anträgen
entstehen nur über gleiche Werte (z. B. gleicher Notar, gleiche Mutter, gleicher Vorfahr).

Spalten (Name | Typ | Beispielwerte | Anzahl verschiedener Werte):
{schema}

Erlaubte Regeltypen und Parameter:
1. "gruppen_anzahl": Gruppiere nach group_col, zähle verschiedene Werte von count_col
   (Standard: ID-Spalte "{id_col}"). Markiere alle Anträge der Gruppen, deren Anzahl die
   Bedingung operator/schwelle erfüllt.
   params: {{"group_col": str, "count_col": str, "operator": ">"|">="|"<"|"<="|"==", "schwelle": number}}
   Beispiel: "Notar in mehr als 3 Anträgen" -> group_col=Notar, count_col={id_col}, operator=">", schwelle=3
   Beispiel: "Vorfahr mit mehr als 5 Nachkommen" -> group_col=Vorfahr, count_col=Antragsteller
2. "gruppen_ausreisser": Wie gruppen_anzahl, aber markiert Gruppen, deren Anzahl mehr als
   sigma Standardabweichungen über (richtung="oben") bzw. unter ("unten") dem Mittelwert liegt.
   params: {{"group_col": str, "count_col": str, "sigma": number, "richtung": "oben"|"unten"}}
3. "datumsabstand": Innerhalb einer Gruppe (group_col) werden die Datumswerte in date_col
   sortiert; markiert Anträge, deren Abstand zum benachbarten Datum zwischen min_tage und
   max_tage (inklusive) liegt. Für "Geschwister weniger als 9 Monate auseinander" z. B.
   min_tage=2 (Zwillinge ausnehmen), max_tage=270.
   params: {{"group_col": str, "date_col": str, "min_tage": number, "max_tage": number}}
4. "altersdifferenz": Differenz in Jahren = spalte_spaet - spalte_frueh (Datums- oder
   Jahresspalten). Markiert Anträge, deren Differenz AUSSERHALB von [min_jahre, max_jahre] liegt.
   Beispiel: "Mutter bei Geburt jünger als 14 oder älter als 50" -> spalte_frueh=Geburtsdatum_Mutter,
   spalte_spaet=Geburtsdatum_Antragsteller, min_jahre=14, max_jahre=50. Nicht genannte Grenze -> null.
   params: {{"spalte_frueh": str, "spalte_spaet": str, "min_jahre": number|null, "max_jahre": number|null}}
5. "feldvergleich": markiert Anträge, bei denen spalte operator wert erfüllt.
   params: {{"spalte": str, "operator": ">"|">="|"<"|"<="|"=="|"!="|"enthaelt"|"in", "wert": any}}
   Datumswerte als "YYYY-MM-DD"; bei "in" ist wert eine Liste.

Optional "filter": Liste von Vorbedingungen {{"spalte","operator","wert"}} (wie feldvergleich),
die den Datenbestand VOR der Regel einschränken (z. B. "nur Anträge über Botschaft London").

Antworte ausschließlich mit JSON:
{{
  "umsetzbar": true|false,
  "titel": "kurzer Regelname",
  "erklaerung": "1-2 Sätze: wie die Regel verstanden und umgesetzt wird (für Sachbearbeitung)",
  "typ": "<einer der Regeltypen>",
  "params": {{...}},
  "filter": [],
  "gewicht": 1-5 (Schwere der Auffälligkeit, Standard 3)
}}
Nur existierende Spaltennamen exakt verwenden. Wenn die Regel nicht mit diesen Typen abbildbar
ist, setze "umsetzbar": false und erkläre in "erklaerung" warum.
"""


def describe_schema(df: pd.DataFrame) -> str:
    lines = []
    for c in df.columns:
        s = df[c].dropna()
        if pd.api.types.is_datetime64_any_dtype(s):
            typ, ex = "Datum", ", ".join(s.head(2).dt.strftime("%Y-%m-%d"))
        elif pd.api.types.is_numeric_dtype(s):
            typ, ex = "Zahl", ", ".join(map(str, s.head(3)))
        else:
            typ, ex = "Text", ", ".join(map(str, s.unique()[:3]))
        lines.append(f"- {c} | {typ} | {ex} | {s.nunique()}")
    return "\n".join(lines)


def translate_rule(text: str, df: pd.DataFrame, id_col: str, model: str | None = None) -> dict:
    client = OpenAI()
    resp = client.chat.completions.create(
        model=model or os.getenv("OPENAI_MODEL", "gpt-4.1"),
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(schema=describe_schema(df), id_col=id_col)},
            {"role": "user", "content": text},
        ],
    )
    rule = json.loads(resp.choices[0].message.content)
    rule["eingabe"] = text
    if rule.get("umsetzbar", True):
        validate_rule(rule, df)
    return rule


# Vorab übersetzte Beispielregeln für den Offline-Modus (kein API-Zugriff / kein Guthaben).
OFFLINE_RULES = {
    "Markiere Anträge, deren Notar in mehr als 5 Anträgen vorkommt.": {
        "titel": "Häufiger Notar", "typ": "gruppen_anzahl", "gewicht": 3,
        "erklaerung": "Anträge werden nach Notar gruppiert; markiert werden Notare mit mehr als 5 Anträgen.",
        "params": {"group_col": "Notar", "count_col": "Antrag_ID", "operator": ">", "schwelle": 5}},
    "Markiere Vorfahren, die mehr als 6 Nachkommen über alle Anträge haben.": {
        "titel": "Vorfahr mit vielen Nachkommen", "typ": "gruppen_anzahl", "gewicht": 4,
        "erklaerung": "Pro Vorfahr werden die verschiedenen Antragstellenden gezählt; markiert ab 7.",
        "params": {"group_col": "Vorfahr", "count_col": "Antragsteller", "operator": ">", "schwelle": 6}},
    "Markiere Kinder derselben Mutter, die weniger als 9 Monate auseinander geboren sind.": {
        "titel": "Geschwister zu kurz nacheinander geboren", "typ": "datumsabstand", "gewicht": 5,
        "erklaerung": "Geburtsdaten der Kinder je Mutter werden verglichen; Abstände von 2–270 Tagen "
                      "werden markiert (Zwillinge ausgenommen).",
        "params": {"group_col": "Mutter", "date_col": "Geburtsdatum_Antragsteller", "min_tage": 2, "max_tage": 270}},
    "Markiere Notare, deren Anzahl beglaubigter Anträge mehr als 2 Standardabweichungen über dem Durchschnitt liegt.": {
        "titel": "Notar statistisch auffällig", "typ": "gruppen_ausreisser", "gewicht": 4,
        "erklaerung": "Anzahl Anträge je Notar wird mit dem Durchschnitt verglichen; markiert ab +2 σ.",
        "params": {"group_col": "Notar", "count_col": "Antrag_ID", "sigma": 2, "richtung": "oben"}},
    "Markiere Anträge, bei denen die Mutter bei der Geburt jünger als 14 oder älter als 50 war.": {
        "titel": "Biologisch unplausibles Alter der Mutter", "typ": "altersdifferenz", "gewicht": 5,
        "erklaerung": "Alter der Mutter bei Geburt der antragstellenden Person muss zwischen 14 und 50 Jahren liegen.",
        "params": {"spalte_frueh": "Geburtsdatum_Mutter", "spalte_spaet": "Geburtsdatum_Antragsteller",
                   "min_jahre": 14, "max_jahre": 50}},
}


def translate_rule_offline(text: str, df: pd.DataFrame) -> dict:
    rule = OFFLINE_RULES.get(text.strip())
    if rule is None:
        raise ValueError("Offline-Modus: nur die vorgegebenen Beispielregeln sind verfügbar.")
    rule = {**rule, "umsetzbar": True, "filter": [], "eingabe": text, "offline": True}
    validate_rule(rule, df)
    return rule


def validate_rule(rule: dict, df: pd.DataFrame) -> None:
    if rule.get("typ") not in RULE_TYPES:
        raise ValueError(f"Unbekannter Regeltyp: {rule.get('typ')}")
    p = rule.get("params", {})
    col_keys = ["group_col", "count_col", "date_col", "spalte_frueh", "spalte_spaet", "spalte"]
    cols = [p[k] for k in col_keys if p.get(k)] + [f["spalte"] for f in rule.get("filter", [])]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Regel verweist auf unbekannte Spalten: {missing}")
    ops = [p.get("operator")] + [f.get("operator") for f in rule.get("filter", [])]
    bad = [o for o in ops if o is not None and o not in OPERATORS]
    if bad:
        raise ValueError(f"Unbekannter Operator: {bad}")


# ---------------------------------------------------------------- Ausführung

def _cmp(series: pd.Series, op: str, value) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series) and op not in ("enthaelt", "in"):
        value = pd.to_datetime(value)
    if op == "enthaelt":
        return series.astype(str).str.contains(str(value), case=False, na=False)
    if op == "in":
        return series.isin(value if isinstance(value, list) else [value])
    return {">": series.gt, ">=": series.ge, "<": series.lt, "<=": series.le,
            "==": series.eq, "!=": series.ne}[op](value)


def _years(series: pd.Series) -> pd.Series:
    """Datums- oder Jahresspalte -> Jahre als Dezimalzahl."""
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    d = pd.to_datetime(series, errors="coerce")
    return d.dt.year + (d.dt.dayofyear - 1) / 365.25


def _fmt(v):
    return v.strftime("%d.%m.%Y") if isinstance(v, pd.Timestamp) else str(v)


def apply_rule(rule: dict, df: pd.DataFrame, id_col: str) -> pd.DataFrame:
    """Gibt DataFrame [id_col, begruendung, gruppe] der getroffenen Anträge zurück."""
    data = df.copy()
    for f in rule.get("filter", []):
        data = data[_cmp(data[f["spalte"]], f["operator"], f["wert"])]
    p, typ = rule["params"], rule["typ"]
    hits = []

    if typ in ("gruppen_anzahl", "gruppen_ausreisser"):
        g, c = p["group_col"], p.get("count_col") or id_col
        counts = data.dropna(subset=[g]).groupby(g)[c].nunique()
        if typ == "gruppen_anzahl":
            flagged = counts[_cmp(counts, p["operator"], p["schwelle"])]
            why = lambda k, n: f"{g} „{k}“ tritt bei {n} verschiedenen {c} auf (Regel: {p['operator']} {p['schwelle']})"
        else:
            mean, std = counts.mean(), counts.std(ddof=0) or 1.0
            z = (counts - mean) / std
            flagged = counts[z > p["sigma"]] if p.get("richtung", "oben") == "oben" else counts[z < -p["sigma"]]
            why = lambda k, n: (f"{g} „{k}“: {n} {c} – Durchschnitt {mean:.1f}, "
                                f"{(n - mean) / std:+.1f} Standardabweichungen (Regel: > {p['sigma']} σ)")
        for key, n in flagged.items():
            for aid in data.loc[data[g] == key, id_col]:
                hits.append((aid, why(key, n), f"{g}: {key}"))

    elif typ == "datumsabstand":
        g, d = p["group_col"], p["date_col"]
        sub = data.dropna(subset=[g, d]).assign(_d=lambda x: pd.to_datetime(x[d])).sort_values([g, "_d"])
        for key, grp in sub.groupby(g):
            dates, ids = grp["_d"].tolist(), grp[id_col].tolist()
            for i in range(1, len(dates)):
                gap = (dates[i] - dates[i - 1]).days
                if p["min_tage"] <= gap <= p["max_tage"]:
                    txt = (f"{g} „{key}“: {d} {_fmt(dates[i - 1])} und {_fmt(dates[i])} liegen nur "
                           f"{gap} Tage auseinander (Regel: {p['min_tage']}–{p['max_tage']} Tage)")
                    hits += [(ids[i - 1], txt, f"{g}: {key}"), (ids[i], txt, f"{g}: {key}")]

    elif typ == "altersdifferenz":
        a, b = p["spalte_frueh"], p["spalte_spaet"]
        diff = _years(data[b]) - _years(data[a])
        lo, hi = p.get("min_jahre"), p.get("max_jahre")
        mask = pd.Series(False, index=data.index)
        if lo is not None:
            mask |= diff < lo
        if hi is not None:
            mask |= diff > hi
        for idx in data.index[mask & diff.notna()]:
            hits.append((data.at[idx, id_col],
                         f"Abstand {a} → {b}: {diff[idx]:.1f} Jahre (erlaubt: {lo if lo is not None else '–'}"
                         f" bis {hi if hi is not None else '–'} Jahre)", None))

    elif typ == "feldvergleich":
        col = p["spalte"]
        for idx in data.index[_cmp(data[col], p["operator"], p["wert"])]:
            hits.append((data.at[idx, id_col],
                         f"{col} = {_fmt(data.at[idx, col])} (Regel: {p['operator']} {p['wert']})", None))

    out = pd.DataFrame(hits, columns=[id_col, "begruendung", "gruppe"])
    return out.drop_duplicates(subset=[id_col, "begruendung"])


def score_cases(df: pd.DataFrame, rules: list[dict], id_col: str) -> pd.DataFrame:
    """Wendet alle aktiven Regeln an und aggregiert einen Auffälligkeits-Score pro Antrag."""
    rows = []
    for r in rules:
        if not r.get("aktiv", True):
            continue
        for _, h in apply_rule(r, df, id_col).iterrows():
            rows.append({id_col: h[id_col], "regel": r["titel"], "gewicht": r.get("gewicht", 3),
                         "begruendung": h["begruendung"], "gruppe": h["gruppe"]})
    if not rows:
        return pd.DataFrame(columns=[id_col, "Score", "Regeln", "Begründung"])
    hits = pd.DataFrame(rows).drop_duplicates(subset=[id_col, "regel"])
    agg = hits.groupby(id_col).agg(
        Score=("gewicht", "sum"),
        Regeln=("regel", lambda s: " | ".join(s)),
        Begründung=("begruendung", lambda s: "\n".join(f"• {x}" for x in s)),
    ).reset_index()
    return agg.sort_values("Score", ascending=False)


def rule_hit_groups(df: pd.DataFrame, rules: list[dict], id_col: str) -> set[str]:
    """Gruppenwerte (z. B. 'Notar: Dr. X'), die eine aktive Regel ausgelöst haben – für den Graphen."""
    groups = set()
    for r in rules:
        if r.get("aktiv", True):
            groups |= set(apply_rule(r, df, id_col)["gruppe"].dropna())
    return groups
