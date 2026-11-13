from datetime import date
from config import require_env
from vpmobil import VertretungsplanZugang

access = VertretungsplanZugang(require_env("SCHULNUMMER"), require_env("BENUTZERNAME"), require_env("PASSWORT"))
plan = access.fetch(date.today())   # ggf. ein anderer Schultag
klasse = next(iter(plan.klassen.values()))
stunde = next(iter(klasse.stunden.values()))[0]
print(vars(stunde))