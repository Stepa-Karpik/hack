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
"""
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
    def create_user(self, email, password, name=''):
        return self.x('INSERT INTO users(email,name,password,created) VALUES(?,?,?,?)',
                      (email.lower(), name, hash_password(password), time.time()))

    def user_by_email(self, email):
        return self.q('SELECT * FROM users WHERE email=?', (email.lower(),), one=True)

    def user(self, user_id):
        return self.q('SELECT * FROM users WHERE id=?', (user_id,), one=True)

    def set_password(self, user_id, password):
        self.x('UPDATE users SET password=? WHERE id=?', (hash_password(password), user_id))
        self.x('DELETE FROM sessions WHERE user_id=?', (user_id,))

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

    def documents(self, user_id, limit=200):
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

    def delete_document(self, slug, user_id):
        self.x('DELETE FROM documents WHERE slug=? AND user_id=?', (slug, user_id))

    def pending(self):
        return self.q("SELECT slug FROM documents WHERE status IN ('queued','running') ORDER BY created")
