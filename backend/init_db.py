import sys

from db import init_db, metadata, engine

if __name__ == "__main__":
    if "--reset" in sys.argv:
        answer = input("ALLE Tabellen und Daten werden gelöscht. Zum Bestätigen 'ja' eingeben: ")
        if answer.strip().lower() != "ja":
            sys.exit("Abgebrochen.")
        metadata.drop_all(engine)
        print("Tabellen gelöscht.")
    init_db()
    print("Tabellen sind angelegt.")