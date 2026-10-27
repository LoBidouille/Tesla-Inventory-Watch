from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import time

from .models import Search

INTERVAL = 8 * 3600


class Store:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = data_dir / 'inventory.sqlite3'
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), config TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), signature TEXT NOT NULL, initialized INTEGER NOT NULL DEFAULT 0,
                  next_check REAL NOT NULL DEFAULT 0, last_attempt REAL, last_success REAL, status TEXT NOT NULL DEFAULT 'paused', error TEXT, source TEXT);
                CREATE TABLE IF NOT EXISTS vehicles (vin TEXT PRIMARY KEY, payload TEXT NOT NULL, active INTEGER NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS seen (vin TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, vin TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL,
                  read_at REAL);
                CREATE TABLE IF NOT EXISTS checks (id INTEGER PRIMARY KEY AUTOINCREMENT, started REAL NOT NULL, finished REAL, status TEXT NOT NULL, count INTEGER, detail TEXT, source TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS login_attempts (address TEXT PRIMARY KEY, failures INTEGER NOT NULL, since REAL NOT NULL);
            ''')
            search = Search()
            db.execute('INSERT OR IGNORE INTO settings(id,config) VALUES(1,?)', (search.model_dump_json(),))
            db.execute('INSERT OR IGNORE INTO state(id,signature) VALUES(1,?)', (search.signature,))
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=30000')
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE state SET status='error', error='Le contrôle a été interrompu. L’échéance de huit heures est conservée.' WHERE status='checking'")
            db.execute("UPDATE checks SET status='interrupted', finished=?, detail='Processus interrompu' WHERE status='running'", (time.time(),))

    def search(self):
        with self.connect() as db:
            return Search.model_validate_json(db.execute('SELECT config FROM settings WHERE id=1').fetchone()[0])

    def snapshot(self):
        with self.connect() as db:
            state = dict(db.execute('SELECT * FROM state WHERE id=1').fetchone())
            settings = db.execute('SELECT * FROM settings WHERE id=1').fetchone()
            vehicles = [json.loads(row['payload']) | {'first_seen': row['first_seen']} for row in db.execute('SELECT * FROM vehicles WHERE active=1 ORDER BY json_extract(payload,\'$.price\')')]
            events = [dict(row) for row in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 100')]
            for event in events:
                event['vehicle'] = json.loads(event.pop('payload'))
            checks = [dict(row) for row in db.execute('SELECT * FROM checks ORDER BY id DESC LIMIT 20')]
            return {'config': json.loads(settings['config']), 'enabled': bool(settings['enabled']), 'state': state,
                    'vehicles': vehicles, 'events': events, 'checks': checks,
                    'unread_count': db.execute('SELECT COUNT(*) FROM events WHERE read_at IS NULL').fetchone()[0],
                    'server_time': time.time()}

    def configure(self, search: Search):
        with self.connect() as db:
            state = db.execute('SELECT signature FROM state WHERE id=1').fetchone()
            changed = state['signature'] != search.signature
            db.execute('UPDATE settings SET config=? WHERE id=1', (search.model_dump_json(),))
            if changed:
                db.execute("UPDATE state SET signature=?,initialized=0,last_success=NULL,source=NULL,status=CASE WHEN status='checking' THEN status ELSE 'waiting' END,error=NULL WHERE id=1", (search.signature,))
                db.execute('DELETE FROM seen')
                db.execute('UPDATE vehicles SET active=0')
        return changed

    def enable(self, enabled: bool):
        with self.connect() as db:
            db.execute('UPDATE settings SET enabled=? WHERE id=1', (enabled,))

    def claim(self, manual=False, now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            state = db.execute('SELECT * FROM state WHERE id=1').fetchone()
            settings = db.execute('SELECT * FROM settings WHERE id=1').fetchone()
            if state['next_check'] > now or state['status'] == 'checking' or (not manual and not settings['enabled']):
                return None
            db.execute("UPDATE state SET next_check=?,last_attempt=?,status='checking',error=NULL WHERE id=1", (now + INTERVAL, now))
            cursor = db.execute("INSERT INTO checks(started,status,source) VALUES(?,'running','browser')", (now,))
            return {'id': cursor.lastrowid, 'config': Search.model_validate_json(settings['config']), 'signature': state['signature']}

    def fail(self, claim, message, retry_after=0, now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute("UPDATE state SET status='error',error=?,next_check=MAX(next_check,?) WHERE id=1", (message, now + retry_after))
            db.execute("UPDATE checks SET status='error',finished=?,detail=? WHERE id=?", (now, message, claim['id']))

    def finish(self, claim, vehicles, source='browser', now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            return self._finish(db, claim, vehicles, source, now)

    def _finish(self, db, claim, vehicles, source, now):
        state = db.execute('SELECT * FROM state WHERE id=1').fetchone()
        if claim['signature'] != state['signature']:
            db.execute("UPDATE checks SET status='discarded',finished=?,detail='Filtres modifiés pendant le contrôle' WHERE id=?", (now, claim['id']))
            db.execute("UPDATE state SET status='waiting' WHERE id=1")
            return 0
        known = {row[0] for row in db.execute('SELECT vin FROM seen')}
        new_count = 0
        db.execute('UPDATE vehicles SET active=0')
        for vehicle in {v['vin']: v for v in vehicles}.values():
            vin, payload = vehicle['vin'], json.dumps(vehicle, ensure_ascii=False)
            db.execute('INSERT INTO vehicles VALUES(?,?,1,?,?) ON CONFLICT(vin) DO UPDATE SET payload=excluded.payload,active=1,last_seen=excluded.last_seen', (vin, payload, now, now))
            db.execute('INSERT OR IGNORE INTO seen VALUES(?)', (vin,))
            if state['initialized'] and vin not in known:
                db.execute('INSERT INTO events(vin,payload,created) VALUES(?,?,?)', (vin, payload, now))
                new_count += 1
        db.execute("UPDATE state SET initialized=1,last_success=?,status='ready',error=NULL,source=? WHERE id=1", (now, source))
        db.execute("UPDATE checks SET status='success',finished=?,count=?,detail=?,source=? WHERE id=?", (now, len(vehicles), f'{new_count} nouvelle(s) annonce(s)', source, claim['id']))
        # Bound retained operational history; discovery events remain available.
        db.execute('DELETE FROM checks WHERE id NOT IN (SELECT id FROM checks ORDER BY id DESC LIMIT 1000)')
        return new_count

    def import_snapshot(self, vehicles):
        with self.connect() as db:
            if db.execute('SELECT status FROM state WHERE id=1').fetchone()[0] == 'checking':
                raise ValueError('Un contrôle est déjà en cours.')
            signature = db.execute('SELECT signature FROM state WHERE id=1').fetchone()[0]
            check_id = db.execute("INSERT INTO checks(started,status,source) VALUES(?,'running','import')", (time.time(),)).lastrowid
            return self._finish(db, {'id': check_id, 'signature': signature}, vehicles, 'import', time.time())

    def mark_read(self):
        with self.connect() as db:
            db.execute('UPDATE events SET read_at=? WHERE read_at IS NULL', (time.time(),))

    def needs_setup(self):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM metadata WHERE key='password'").fetchone() is None

    def setup_password(self, password):
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex()
        with self.connect() as db:
            if db.execute("SELECT 1 FROM metadata WHERE key='password'").fetchone():
                raise ValueError('Un accès est déjà configuré.')
            db.execute("INSERT INTO metadata VALUES('password',?)", (salt.hex() + ':' + digest,))

    def login(self, password, address):
        now = time.time()
        with self.connect() as db:
            attempt = db.execute('SELECT * FROM login_attempts WHERE address=?', (address,)).fetchone()
            if attempt and attempt['since'] > now - 900 and attempt['failures'] >= 5:
                raise ValueError('Trop de tentatives. Réessayez dans 15 minutes.')
            row = db.execute("SELECT value FROM metadata WHERE key='password'").fetchone()
            valid = False
            if row:
                salt, expected = row[0].split(':')
                actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
                valid = hmac.compare_digest(actual, expected)
            if not valid:
                if not attempt or attempt['since'] <= now - 900:
                    db.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,1,?)', (address, now))
                else:
                    db.execute('UPDATE login_attempts SET failures=failures+1 WHERE address=?', (address,))
            else:
                db.execute('DELETE FROM login_attempts WHERE address=?', (address,))
        return valid

    def new_session(self):
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES(?,?)', (hashlib.sha256(token.encode()).hexdigest(), time.time() + 30 * 86400))
        return token

    def authenticated(self, token):
        if not token:
            return False
        with self.connect() as db:
            return db.execute('SELECT 1 FROM sessions WHERE token=? AND expires>?', (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone() is not None

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(token.encode()).hexdigest(),))
