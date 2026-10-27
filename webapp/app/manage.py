"""Administrative commands for the owner of the server."""
import getpass
import hashlib
import secrets
import sys

from .config import Settings
from .db import Store


def main():
    if sys.argv[1:] != ['reset-password']:
        raise SystemExit('Usage : python -m app.manage reset-password')
    password = getpass.getpass('Nouveau mot de passe (12 caractères minimum) : ')
    confirmation = getpass.getpass('Confirmation : ')
    if len(password) < 12 or len(password) > 256 or password != confirmation:
        raise SystemExit('Mot de passe trop court ou confirmation différente.')
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex()
    store = Store(Settings.from_env().data_dir)
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO metadata VALUES('password',?)", (salt.hex()+':'+digest,))
        db.execute('DELETE FROM sessions')
    print('Mot de passe remplacé. Toutes les sessions ont été fermées. Les recherches sont conservées.')


if __name__ == '__main__':
    main()
