"""Erzeugt einen vollständig fingierten Demo-Datenbestand (flache Excel-Datei).

Eine Zeile = ein Antrag einer antragstellenden Person. Es gibt keine separate
Beziehungstabelle: Verknüpfungen entstehen über gleiche Namen (Mutter, Vorfahr,
Notar, Auslandsvertretung) in mehreren Zeilen.

Bewusst eingebaute Auffälligkeiten:
  * Notar "Dr. Elias Varga" beglaubigt ungewöhnlich viele Anträge
  * Vorfahr "Jakob Liebermann" hat sehr viele Nachkommen in vielen Ländern ("Blume")
  * Mutter "Miriam Adler" hat zwei Kinder im Abstand von ca. 5 Monaten
  * Zwei Mütter sind bei der Geburt des Kindes biologisch unplausibel alt/jung
  * Zwillinge (gleicher Geburtstag) als plausibler Gegenfall
"""
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

random.seed(42)

MISSIONS = {
    "Botschaft Tel Aviv": ("Israel", ["Tel Aviv", "Haifa", "Jerusalem"]),
    "Generalkonsulat New York": ("USA", ["New York", "Boston", "Philadelphia"]),
    "Botschaft London": ("Vereinigtes Königreich", ["London", "Manchester"]),
    "Botschaft Buenos Aires": ("Argentinien", ["Buenos Aires", "Rosario"]),
    "Generalkonsulat São Paulo": ("Brasilien", ["São Paulo", "Curitiba"]),
    "Generalkonsulat Toronto": ("Kanada", ["Toronto", "Montreal"]),
}
NOTARIES = ["Dr. Hannah Kessler", "Samuel Oren", "Laura Whitfield", "Dr. Martín Ibarra", "Clara Wolff",
            "Daniel Rothman", "Priya Anand", "Yael Dror", "Michael Grant", "Dr. Paula Senra", "Ari Kaplan",
            "Sophie Lambert", "Ricardo Fontes", "Nathan Pierce", "Dr. Ilse Hartung"]
ANCESTORS = [("Jakob Liebermann", 1885), ("Rosa Feldmann", 1892), ("Salomon Grünberg", 1879),
             ("Bertha Silbermann", 1896), ("Isidor Kahnweiler", 1888), ("Frieda Morgenroth", 1901)]
FIRST = ["Noa", "Daniel", "Sarah", "Lucas", "Emma", "David", "Olivia", "Tomás", "Lea", "Ethan",
         "Maya", "Gabriel", "Julia", "Benjamin", "Sofia", "Aaron", "Isabella", "Jonah", "Clara", "Mateo"]
LAST = ["Levin", "Carter", "Shapiro", "Moreno", "Goldberg", "Blake", "Katz", "Ferreira", "Stein",
        "Harper", "Weiss", "Alvarez", "Brenner", "Collins", "Rosen", "Duarte"]


def rand_date(start_year, end_year):
    start = date(start_year, 1, 1)
    return start + timedelta(days=random.randint(0, (date(end_year, 12, 31) - start).days))


def family(ancestor, mission, n_children, mother_name=None, mother_birth=None):
    """Eine Mutter mit n Kindern (= Antragstellende), alle mit demselben Vorfahren."""
    last = random.choice(LAST)
    mother_name = mother_name or f"{random.choice(['Ruth', 'Esther', 'Anna', 'Judith', 'Mara', 'Helen', 'Naomi'])} {last}"
    mother_birth = mother_birth or rand_date(1950, 1972)
    land, cities = MISSIONS[mission]
    city = random.choice(cities)
    rows, child_birth = [], mother_birth + timedelta(days=365 * random.randint(22, 28))
    for _ in range(n_children):
        rows.append(dict(Antragsteller=f"{random.choice(FIRST)} {last}", Geburtsdatum_Antragsteller=child_birth,
                         Mutter=mother_name, Geburtsdatum_Mutter=mother_birth, Vorfahr=ancestor[0],
                         Geburtsjahr_Vorfahr=ancestor[1], Auslandsvertretung=mission, Wohnland=land, Wohnort=city))
        child_birth += timedelta(days=random.randint(500, 1800))
    return rows


def build():
    rows = []
    missions = list(MISSIONS)
    # Unauffällige Familien
    for anc in ANCESTORS[1:]:
        for _ in range(2):
            rows += family(anc, random.choice(missions), random.randint(1, 3))
    # "Blume": sehr viele Nachkommen desselben Vorfahren über viele Länder
    for m in missions:
        rows += family(ANCESTORS[0], m, 2)
    # Zwei Kinder derselben Mutter im Abstand von ~5 Monaten
    fam = family(ANCESTORS[2], "Botschaft London", 2, "Miriam Adler", date(1968, 4, 2))
    fam[0]["Geburtsdatum_Antragsteller"] = date(1994, 3, 10)
    fam[1]["Geburtsdatum_Antragsteller"] = date(1994, 8, 22)
    rows += fam
    # Zwillinge (plausibel)
    fam = family(ANCESTORS[3], "Generalkonsulat Toronto", 2, "Esther Weiss", date(1970, 6, 12))
    fam[1]["Geburtsdatum_Antragsteller"] = fam[0]["Geburtsdatum_Antragsteller"]
    rows += fam
    # Mutter bei Geburt 12 bzw. 56 Jahre alt
    fam = family(ANCESTORS[4], "Botschaft Buenos Aires", 1, "Lucia Moreno", date(1975, 9, 1))
    fam[0]["Geburtsdatum_Antragsteller"] = date(1987, 11, 3)
    rows += fam
    fam = family(ANCESTORS[5], "Generalkonsulat New York", 1, "Deborah Katz", date(1941, 2, 14))
    fam[0]["Geburtsdatum_Antragsteller"] = date(1997, 5, 20)
    rows += fam

    random.shuffle(rows)
    for i, r in enumerate(rows, start=1):
        r["Antrag_ID"] = f"A-2025-{i:04d}"
        r["Notar"] = NOTARIES[i % len(NOTARIES)]  # gleichmäßig verteilt: je 2–3 Anträge
        r["Eingangsdatum"] = rand_date(2024, 2025)
    # Auffälliger Notar: beglaubigt 9 Anträge
    for r in random.sample(rows, 9):
        r["Notar"] = "Dr. Elias Varga"

    cols = ["Antrag_ID", "Antragsteller", "Geburtsdatum_Antragsteller", "Mutter", "Geburtsdatum_Mutter",
            "Vorfahr", "Geburtsjahr_Vorfahr", "Notar", "Auslandsvertretung", "Wohnort", "Wohnland", "Eingangsdatum"]
    df = pd.DataFrame(rows)[cols]
    for c in ["Geburtsdatum_Antragsteller", "Geburtsdatum_Mutter", "Eingangsdatum"]:
        df[c] = pd.to_datetime(df[c])
    return df


if __name__ == "__main__":
    out = Path(__file__).parent / "data" / "demo_antraege.xlsx"
    out.parent.mkdir(exist_ok=True)
    df = build()
    df.to_excel(out, index=False)
    print(f"{len(df)} Anträge geschrieben nach {out}")
