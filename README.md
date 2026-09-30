# Demonstrator: natürlichsprachliche Plausibilitätsprüfung

Einfacher Demonstrator (kein Produkt) für die Einbürgerungsanträge nach Art. 116 Abs. 2 GG.
Sachbearbeitende formulieren eine Prüfregel auf Deutsch; die KI übersetzt sie in eine
**sichtbare, strukturierte Regel**, die **deterministisch** auf alle Anträge angewendet wird.
Das Sprachmodell bewertet keine einzelnen Anträge.

## Installation (nach dem Klonen)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env         # eigenen OPENAI_API_KEY eintragen
streamlit run app.py           # http://localhost:8501
```

Die Demo-Daten liegen bereits in `data/demo_antraege.xlsx`. `python generate_data.py` erzeugt sie
neu, das Ergebnis ist immer dasselbe.

`.env` enthält `OPENAI_API_KEY` und `OPENAI_MODEL` (Standard `gpt-4.1`). Die Datei ist nicht im
Repository enthalten.
Ohne API-Zugang: in der Sidebar **Offline-Modus** aktivieren. Die fünf Beispielregeln sind dann
vorab übersetzt hinterlegt. Bei API-Fehlern wird automatisch auf diese Übersetzung zurückgegriffen.

## Aufbau

| Datei | Inhalt |
|---|---|
| `generate_data.py` | flache Excel, eine Zeile je Antrag, keine Beziehungstabelle; Verknüpfung über gleiche Namen. Enthält eingebaute Auffälligkeiten (Notar „Dr. Elias Varga“, Vorfahr „Jakob Liebermann“ als „Blume“, Geschwister 165 Tage auseinander, Mutter 12 bzw. 56 Jahre, Zwillinge als plausibler Gegenfall) |
| `rules.py` | Prompt zur Regelübersetzung, fester Regelkatalog, pandas-Ausführung, Scoring |
| `app.py` | Streamlit-Oberfläche: ① Fallübersicht ② Regeln ③ Prüfliste mit Status ④ Beziehungsgraph |
| `tests/smoke_test.py` | Headless-Test der Oberfläche im Offline-Modus |

### Regelkatalog (Ausgabe des LLM)

| Typ | Beispiel |
|---|---|
| `gruppen_anzahl` | Notar in mehr als 5 Anträgen; Vorfahr mit mehr als 6 Nachkommen |
| `gruppen_ausreisser` | Notar > 2 Standardabweichungen über dem Durchschnitt |
| `datumsabstand` | Kinder derselben Mutter < 9 Monate auseinander (Zwillinge ausgenommen) |
| `altersdifferenz` | Mutter bei Geburt < 14 oder > 50 Jahre |
| `feldvergleich` (+ optionaler `filter`) | Eingang nach 01.06.2025, nur Botschaft London |

Jede Regel hat ein Gewicht (1–5). Der Score eines Antrags ist die Summe der Gewichte aller
ausgelösten Regeln. In der Prüfliste lässt sich je Fall ein Status setzen: *verifiziert*,
*möglicherweise kritisch* oder *Betrugsverdacht*. Der Status wird in `data/review_status.json`
gespeichert, die Liste kann als CSV exportiert werden.

Gerhards Excel lässt sich per Upload in der Sidebar laden. Die Regelübersetzung nutzt die
tatsächlichen Spaltennamen, die Offline-Beispielregeln setzen jedoch die Demo-Spaltennamen voraus.
