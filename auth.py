import hashlib, json, os, secrets, time
from functools import wraps
from flask import session, redirect, url_for, request, jsonify

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
AUTH_PATH = os.path.join(DATA_DIR, '.project_auth.json')
SECRET_PATH = os.path.join(DATA_DIR, '.project_session_secret')
os.makedirs(DATA_DIR, exist_ok=True)

PBKDF2_ROUNDS = 240_000


def _load():
    try:
        with open(AUTH_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def configured():
    return bool(_load() and _load().get('password_hash'))


def _hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()
    return salt, digest


def set_password(password):
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError('Password must be at least 8 characters.')
    salt, digest = _hash(password)
    tmp = AUTH_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'algorithm':'PBKDF2-HMAC-SHA256','iterations':PBKDF2_ROUNDS,'salt':salt,'password_hash':digest,'updated_at':time.time()}, f, indent=2)
    os.replace(tmp, AUTH_PATH)


def verify_password(password):
    data = _load()
    if not data:
        return False
    try:
        _, digest = _hash(password, data['salt'])
        return secrets.compare_digest(digest, data['password_hash'])
    except Exception:
        return False


def ensure_secret(app):
    if os.path.exists(SECRET_PATH):
        try:
            with open(SECRET_PATH, 'r', encoding='utf-8') as f:
                app.secret_key = f.read().strip()
                if app.secret_key:
                    return
        except Exception:
            pass
    secret = secrets.token_hex(32)
    with open(SECRET_PATH, 'w', encoding='utf-8') as f:
        f.write(secret)
    app.secret_key = secret


def login_user():
    session.clear()
    session['authenticated'] = True
    session['login_at'] = time.time()


def logout_user():
    session.clear()


def is_authenticated():
    return bool(session.get('authenticated'))


def protected(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_authenticated():
            if request.path.startswith('/api/'):
                return jsonify({'success':False,'error':'Authentication required','auth_required':True}), 401
            return redirect(url_for('login', next=request.full_path))
        return view(*args, **kwargs)
    return wrapper
