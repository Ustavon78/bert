import hashlib
import secrets
import sys
from datetime import datetime

from sqlalchemy import insert, select

from db import devices, engine


def create_device(room: str, name: str | None = None) -> tuple[str, str]:
    """Legt ein Display an und gibt (ID, Token) zurück."""
    token = secrets.token_urlsafe(32)
    with engine.begin() as conn:
        existing = set(conn.execute(select(devices.c.id)).scalars())
        while True:
            device_id = str(secrets.randbelow(900000) + 100000)
            if device_id not in existing:
                break
        conn.execute(insert(devices).values(
            id=device_id, name=name or f"Raum {room}", room=room,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            mode="active", ota_force=False, created_at=datetime.now(),
        ))
    return device_id, token


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('Aufruf: python add_device.py RAUM ["NAME"]')
    new_id, new_token = create_device(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(f"ID:    {new_id}")
    print(f"Token: {new_token}")
    print("Das Token wird nur jetzt angezeigt. Bitte sicher aufs Display übertragen.")