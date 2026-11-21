# SPDX-License-Identifier: GPL-3.0-or-later
"""Create the admin password hash for the .env.

    python admin_passwd.py              ask for a password
    python admin_passwd.py --generate   create a random password (used by install.sh)
"""

import getpass
import secrets
import sys

from admin_auth import hash_password

MIN_LENGTH = 12

if __name__ == "__main__":
    if "--generate" in sys.argv:
        password = secrets.token_urlsafe(18)
        print(f"ADMIN_PASSWORD={password}")
        print(f"ADMIN_PASSWORD_HASH='{hash_password(password)}'")
        sys.exit(0)

    password = getpass.getpass("New admin password: ")
    if len(password) < MIN_LENGTH:
        sys.exit(f"Please use at least {MIN_LENGTH} characters.")
    if password != getpass.getpass("Repeat: "):
        sys.exit("The passwords do not match.")
    print("\nAdd these lines to your .env (and restart the server):\n")
    print("ADMIN_USER=admin")
    print(f"ADMIN_PASSWORD_HASH='{hash_password(password)}'")