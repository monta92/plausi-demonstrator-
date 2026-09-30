"""Headless-Rauchtest: alle Beispielregeln (Offline-Modus) über die Oberfläche anlegen."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

at = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=60).run()
next(t for t in at.toggle if t.label.startswith("Offline")).set_value(True).run()
btn = lambda label: next(b for b in at.button if b.label.startswith(label))
examples = next(s for s in at.selectbox if s.label.startswith("Beispielregel")).options[1:]
for text in examples:
    at.text_area[0].set_value(text).run()
    btn("Regel übersetzen").click().run()
    assert not at.error, [e.value for e in at.error]
    btn("✔").click().run()
assert not at.exception, [e.value for e in at.exception]
print("Regeln:", len(at.session_state.rules))
print({m.label: m.value for m in at.metric})
