import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        sys.exit(f"Fehlende Einstellung in .env: {name}")
    return value


def json_env_list(name: str) -> list:
    raw = os.getenv(name, "[]").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        raw = raw[1:-1]
    value = json.loads(raw or "[]")
    if not isinstance(value, list):
        sys.exit(f"{name} muss eine JSON-Liste sein.")
    return value