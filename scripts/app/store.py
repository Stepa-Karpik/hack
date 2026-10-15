"""SQLite storage: users, sessions, API keys, documents. Standard library only."""
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL DEFAULT '',
  password TEXT NOT NULL, created REAL NOT NULL, auto_approve INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created REAL NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS api_keys (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, prefix TEXT NOT NULL,
  key_hash TEXT UNIQUE NOT NULL, created REAL NOT NULL, last_used REAL);
CREATE TABLE IF NOT EXISTS documents (
  slug TEXT PRIMARY KEY, user_id INTEGER NOT NULL, filename TEXT NOT NULL, requested_type TEXT NOT NULL,
  document_type TEXT, status TEXT NOT NULL, error TEXT, created REAL NOT NULL, updated REAL NOT NULL,
  found INTEGER, total INTEGER, valid INTEGER, approved INTEGER NOT NULL DEFAULT 0, approved_at REAL,
  approved_by TEXT, verified TEXT NOT NULL DEFAULT '{}', source TEXT NOT NULL DEFAULT 'web',
  seconds REAL, seen INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS documents_user ON documents(user_id, created DESC);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, slug TEXT NOT NULL, at REAL NOT NULL, user_id INTEGER, kind TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS events_slug ON events(slug, at);
CREATE TABLE IF NOT EXISTS versions (
  id INTEGER PRIMARY KEY, slug TEXT NOT NULL, n INTEGER NOT NULL, filename TEXT NOT NULL, created REAL NOT NULL,
  source TEXT NOT NULL, found INTEGER, total INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS invites (
  token_hash TEXT PRIMARY KEY, prefix TEXT NOT NULL, role TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_by INTEGER NOT NULL,
  created REAL NOT NULL, expires REAL NOT NULL, used_by INTEGER, used_at REAL, revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS doc_types (
  key TEXT PRIMARY KEY, title TEXT NOT NULL, config TEXT NOT NULL, created REAL NOT NULL, created_by INTEGER);
"""
# Columns added after the first release (kept as ALTERs so existing databases upgrade in place).
MIGRATIONS = [
    ("users", "role", "TEXT NOT NULL DEFAULT 'student'"),        # student | staff | admin
    ("documents", "decision", "TEXT"),                            # approved | returned | NULL (waiting)
    ("documents", "decision_comment", "TEXT"),
    ("documents", "decided_by", "INTEGER"),
    # application workflow: draft -> submitted -> review -> approved | returned (-> replaced -> submitted ...) | closed
    ("documents", "state", "TEXT NOT NULL DEFAULT 'draft'"),
    ("documents", "submitted_at", "REAL"),
    ("documents", "student_comment", "TEXT"),
    ("documents", "attempts", "INTEGER NOT NULL DEFAULT 0"),
    ("documents", "version", "INTEGER NOT NULL DEFAULT 1"),
    ("users", "study_group", "TEXT NOT NULL DEFAULT ''"),
]
STATES = ('draft', 'submitted', 'review', 'approved', 'returned', 'closed')
ROLES = ('student', 'staff', 'admin')
SESSION_DAYS = 30


def hash_password(password, salt=None, iterations=240_000):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
    return f'pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}'


def check_password(password, stored):
    try:
        _, iterations, salt, digest = stored.split('$')
        candidate = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(candidate.hex(), digest)
    except (ValueError, TypeError):
        return False


def _token_hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for table, column, kind in MIGRATIONS:
            existing = {r[1] for r in self.db.execute(f'PRAGMA table_info({table})')}
            if column not in existing:
                self.db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {kind}')
        # documents approved before roles existed keep their decision; decided documents get their state
        self.db.execute("UPDATE documents SET decision='approved' WHERE approved=1 AND decision IS NULL")
        self.db.execute("UPDATE documents SET state=decision WHERE decision IN ('approved','returned') AND state='draft'")
        self.db.commit()

    def q(self, sql, args=(), one=False):
        with self.lock:
            cur = self.db.execute(sql, args)
            rows = cur.fetchall()
            self.db.commit()
        rows = [dict(r) for r in rows]
        return (rows[0] if rows else None) if one else rows

    def x(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.lastrowid

    # users
    def create_user(self, email, password, name='', role='student'):
        return self.x('INSERT INTO users(email,name,password,created,role) VALUES(?,?,?,?,?)',
                      (email.lower(), name, hash_password(password), time.time(), role))

    def users(self):
        return self.q('SELECT u.id,u.email,u.name,u.role,u.created,(SELECT COUNT(*) FROM documents d WHERE d.user_id=u.id) AS documents '
                      'FROM users u ORDER BY u.created')

    def set_role(self, user_id, role):
        if role not in ROLES:
            raise ValueError(role)
        self.x('UPDATE users SET role=? WHERE id=?', (role, user_id))

    def setting(self, key, default=None):
        row = self.q('SELECT value FROM settings WHERE key=?', (key,), one=True)
        return row['value'] if row else default

    def set_setting(self, key, value):
        self.x('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))

    def user_by_email(self, email):
        return self.q('SELECT * FROM users WHERE email=?', (email.lower(),), one=True)

    def user(self, user_id):
        return self.q('SELECT * FROM users WHERE id=?', (user_id,), one=True)

    def set_password(self, user_id, password):
        self.x('UPDATE users SET password=? WHERE id=?', (hash_password(password), user_id))
        self.x('DELETE FROM sessions WHERE user_id=?', (user_id,))

    def set_profile(self, user_id, name=None, study_group=None):
        if name is not None:
            self.x('UPDATE users SET name=? WHERE id=?', (name, user_id))
        if study_group is not None:
            self.x('UPDATE users SET study_group=? WHERE id=?', (study_group, user_id))

    def set_auto_approve(self, user_id, value):
        self.x('UPDATE users SET auto_approve=? WHERE id=?', (int(bool(value)), user_id))

    # sessions
    def new_session(self, user_id):
        token = secrets.token_urlsafe(32)
        now = time.time()
        self.x('INSERT INTO sessions VALUES(?,?,?,?)', (_token_hash(token), user_id, now, now + SESSION_DAYS * 86400))
        return token

    def session_user(self, token):
        if not token:
            return None
        row = self.q('SELECT user_id, expires FROM sessions WHERE token_hash=?', (_token_hash(token),), one=True)
        if not row or row['expires'] < time.time():
            return None
        return self.user(row['user_id'])

    def end_session(self, token):
        self.x('DELETE FROM sessions WHERE token_hash=?', (_token_hash(token or ''),))

    # api keys
    def new_api_key(self, user_id, name):
        key = 'dk_live_' + secrets.token_urlsafe(30)
        key_id = self.x('INSERT INTO api_keys(user_id,name,prefix,key_hash,created) VALUES(?,?,?,?,?)',
                        (user_id, name, key[:14], _token_hash(key), time.time()))
        return key_id, key

    def api_keys(self, user_id):
        return self.q('SELECT id,name,prefix,created,last_used FROM api_keys WHERE user_id=? ORDER BY created DESC', (user_id,))

    def delete_api_key(self, user_id, key_id):
        self.x('DELETE FROM api_keys WHERE id=? AND user_id=?', (key_id, user_id))

    def api_key_user(self, key):
        row = self.q('SELECT id, user_id FROM api_keys WHERE key_hash=?', (_token_hash(key or ''),), one=True)
        if not row:
            return None
        self.x('UPDATE api_keys SET last_used=? WHERE id=?', (time.time(), row['id']))
        return self.user(row['user_id'])

    # documents
    def add_document(self, slug, user_id, filename, requested_type, source='web'):
        now = time.time()
        self.x('INSERT INTO documents(slug,user_id,filename,requested_type,status,created,updated,source) '
               'VALUES(?,?,?,?,?,?,?,?)', (slug, user_id, filename, requested_type, 'queued', now, now, source))

    def document(self, slug, user_id=None):
        doc = self.q('SELECT * FROM documents WHERE slug=?', (slug,), one=True)
        if doc is None or (user_id is not None and doc['user_id'] != user_id):
            return None
        doc['verified'] = json.loads(doc['verified'] or '{}')
        return doc

    def documents(self, user_id, limit=500):
        """Documents of one user, or the deanery inbox when user_id is None (everything students submitted)."""
        if user_id is None:
            rows = self.q("SELECT d.*, u.email AS owner_email, u.name AS owner_name, u.study_group AS owner_group FROM documents d "
                          "LEFT JOIN users u ON u.id=d.user_id WHERE d.state != 'draft' "
                          "ORDER BY COALESCE(d.submitted_at, d.created) DESC LIMIT ?", (limit,))
        else:
            rows = self.q('SELECT * FROM documents WHERE user_id=? ORDER BY created DESC LIMIT ?', (user_id, limit))
        for r in rows:
            r['verified'] = json.loads(r['verified'] or '{}')
        return rows

    def update_document(self, slug, **values):
        if 'verified' in values:
            values['verified'] = json.dumps(values['verified'], ensure_ascii=False)
        values['updated'] = time.time()
        sets = ', '.join(f'{k}=?' for k in values)
        self.x(f'UPDATE documents SET {sets} WHERE slug=?', (*values.values(), slug))

    def delete_document(self, slug, user_id=None):
        if user_id is None:
            self.x('DELETE FROM documents WHERE slug=?', (slug,))
        else:
            self.x('DELETE FROM documents WHERE slug=? AND user_id=?', (slug, user_id))

    # application history
    def add_event(self, slug, user_id, kind, **detail):
        self.x('INSERT INTO events(slug,at,user_id,kind,detail) VALUES(?,?,?,?,?)',
               (slug, time.time(), user_id, kind, json.dumps(detail, ensure_ascii=False)))

    def events(self, slug=None):
        sql = ('SELECT e.*, u.email AS user_email, u.name AS user_name, u.role AS user_role FROM events e '
               'LEFT JOIN users u ON u.id=e.user_id')
        rows = self.q(sql + ' WHERE e.slug=? ORDER BY e.at', (slug,)) if slug else self.q(sql + ' ORDER BY e.at')
        for r in rows:
            r['detail'] = json.loads(r['detail'] or '{}')
        return rows

    def add_version(self, slug, n, filename, source, found=None, total=None, note=None):
        self.x('INSERT INTO versions(slug,n,filename,created,source,found,total,note) VALUES(?,?,?,?,?,?,?,?)',
               (slug, n, filename, time.time(), source, found, total, note))

    def versions(self, slug):
        return self.q('SELECT * FROM versions WHERE slug=? ORDER BY n', (slug,))

    # staff invitations (one-time links issued by the administrator)
    def new_invite(self, created_by, role='staff', note='', days=7):
        token = secrets.token_urlsafe(24)
        now = time.time()
        self.x('INSERT INTO invites(token_hash,prefix,role,note,created_by,created,expires) VALUES(?,?,?,?,?,?,?)',
               (_token_hash(token), token[:6], role, note, created_by, now, now + days * 86400))
        return token

    def invite(self, token):
        row = self.q('SELECT * FROM invites WHERE token_hash=?', (_token_hash(token or ''),), one=True)
        if not row or row['revoked'] or row['used_by'] or row['expires'] < time.time():
            return None
        return row

    def use_invite(self, token, user_id):
        self.x('UPDATE invites SET used_by=?, used_at=? WHERE token_hash=?', (user_id, time.time(), _token_hash(token)))

    def invites(self):
        return self.q('SELECT i.prefix,i.role,i.note,i.created,i.expires,i.used_at,i.revoked,u.email AS used_email '
                      'FROM invites i LEFT JOIN users u ON u.id=i.used_by ORDER BY i.created DESC')

    def revoke_invite(self, prefix):
        self.x('UPDATE invites SET revoked=1 WHERE prefix=? AND used_by IS NULL', (prefix,))

    # document types defined in the constructor
    def doc_types(self):
        rows = self.q('SELECT * FROM doc_types ORDER BY created')
        for r in rows:
            r['config'] = json.loads(r['config'])
        return rows

    def save_doc_type(self, key, title, config, user_id):
        self.x('INSERT INTO doc_types(key,title,config,created,created_by) VALUES(?,?,?,?,?) '
               'ON CONFLICT(key) DO UPDATE SET title=excluded.title, config=excluded.config',
               (key, title, json.dumps(config, ensure_ascii=False), time.time(), user_id))

    def delete_doc_type(self, key):
        self.x('DELETE FROM doc_types WHERE key=?', (key,))

    def pending(self):
        return self.q("SELECT slug FROM documents WHERE status IN ('queued','running') ORDER BY created")
