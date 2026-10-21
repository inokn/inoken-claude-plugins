"""認証情報を「伏せる」ための共通部品。

Claude が読むと、読んだ内容は Anthropic のサーバーへ送られる。そこで Claude が読む前に、
手元のスクリプトでパスワードらしき値を印（__PHPUP_SECRET_0001__）に置き換え、本物の値は
作業フォルダの外（点検ツールの置き場所の secrets/）に保存する。アップロード用のファイルを
作るときだけ、本物の値に戻す。

値はバイト列のまま扱う（Shift_JIS のファイルでも壊さない）。
"""
import base64
import json
import os
import re
import uuid
from pathlib import Path

from common import OUT, SKIP_DIR_NAMES, load_json, rel, save_json, tools_dir

PH_RE = re.compile(rb"__PHPUP_SECRET_\d{4}__")
MASKED = OUT / "masked.json"          # 伏せたファイルと印の一覧（値は入れない）

_WORDS = rb"(?:PASS|PASSWD|PASSWORD|PWD|SECRET|API_?KEY|AUTH_?KEY|SECRET_?KEY|PRIVATE_?KEY|TOKEN|SALT)"
# PHP の変数・定数名はゆるく（$dbpass / DBPASS も拾う）
_NAME = rb"[A-Z0-9_]*" + _WORDS + rb"[A-Z0-9_]*"
# JSON / .env / YAML / SetEnv のキーは、単語として現れるものだけ（minipass / getpass などのパッケージ名を拾わない）
_KEY = rb"(?:[A-Z0-9]+[_.-])*" + _WORDS + rb"(?:[_.-][A-Z0-9]+)*"
_Q = rb"(?P<q>['\"])(?P<v>(?:(?!(?P=q)).)+?)(?P=q)"
_ARG = rb"[^,()]+(?:\([^()]*\))?[^,()]*"   # 関数の引数1つ（中に括弧1段まで）

PATTERNS = [
    # define('DB_PASS', '...')
    re.compile(rb"define\s*\(\s*['\"]" + _NAME + rb"['\"]\s*,\s*" + _Q, re.I),
    # const DB_PASS = '...';
    re.compile(rb"\bconst\s+" + _NAME + rb"\s*=\s*" + _Q, re.I),
    # $db_pass = '...'; / $password = "...";
    re.compile(rb"\$" + _NAME + rb"\s*=\s*" + _Q, re.I),
    # $cfg['password'] = '...'; / 'password' => '...'
    re.compile(rb"\[\s*['\"]" + _NAME + rb"['\"]\s*\]\s*=\s*" + _Q, re.I),
    re.compile(rb"['\"]" + _NAME + rb"['\"]\s*=>\s*" + _Q, re.I),
    # mysql_connect / mysqli_connect / new mysqli / new PDO の3番目の引数（パスワード）
    re.compile(rb"(?:mysqli?_connect|mysqli_real_connect|new\s+mysqli|new\s+PDO)\s*\(\s*" + _ARG + rb",\s*" + _ARG + rb",\s*" + _Q, re.I),
    # URL に埋め込んだパスワード（ftp://user:pass@host など）
    re.compile(rb"[a-z][a-z0-9+.-]*://[^/\s:@'\"]+:(?P<v>[^@\s'\"/]+)@", re.I),
    # .htaccess の SetEnv DB_PASS ...
    re.compile(rb"^[ \t]*SetEnv[ \t]+" + _KEY + rb"[ \t]+(?P<q>['\"]?)(?P<v>[^\s'\"]+)(?P=q)", re.I | re.M),
    # .env / .ini / .yml: DB_PASSWORD=... / password: ...
    re.compile(rb"^[ \t]*" + _KEY + rb"[ \t]*[=:][ \t]*(?P<q>['\"]?)(?P<v>[^\s'\"#;]+)(?P=q)", re.I | re.M),
    # JSON: "password": "..."
    re.compile(rb"\"" + _KEY + rb"\"\s*:\s*\"(?P<v>[^\"]+)\"", re.I),
]

TEXT_EXTS = {".php", ".inc", ".phtml", ".php3", ".php4", ".php5", ".php7", ".html", ".htm", ".shtml",
             ".ini", ".yml", ".yaml", ".json", ".conf", ".cnf", ".txt", ".xml", ".neon", ".cgi", ".pl", ".py"}
TEXT_NAMES = {".htaccess", ".env", ".user.ini"}
# 秘密が入らないのに誤検知しやすいもの（依存関係の一覧・見本の設定）
SKIP_NAMES = {"package-lock.json", "package.json", "composer.lock", "yarn.lock", "pnpm-lock.yaml", "wp-config-sample.php"}
PLACEHOLDER_VALUES = {b"password_here", b"username_here", b"database_name_here", b"put your unique phrase here",
                      b"your-password", b"your_password", b"yourpassword", b"changeme", b"password", b"secret", b"xxxx", b"****"}
SKIP_DIRS_MASK = SKIP_DIR_NAMES | {"vendor", "uploads", "cache", "wp-admin", "wp-includes", "languages"}
MAX_BYTES = 2_000_000


def candidate_files():
    for dirpath, dirnames, filenames in os.walk("."):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS_MASK)
        for fn in sorted(filenames):
            p = Path(dirpath, fn)
            if fn in SKIP_NAMES or fn.endswith((".lock", ".map", ".min.js")):
                continue
            if (p.suffix.lower() in TEXT_EXTS or fn in TEXT_NAMES or fn.startswith(".env")) and p.stat().st_size <= MAX_BYTES:
                yield p


def _usable(v):
    """伏せる値として妥当か（空・変数・すでに伏せた印・プレースホルダらしきものは除く）。"""
    if not v or len(v) < 3 or PH_RE.fullmatch(v):
        return False
    if b"$" in v or v.strip(b"*x ") == b"" or v.lower() in (b"null", b"true", b"false", b"none") or v.lower() in PLACEHOLDER_VALUES:
        return False
    return True


def find_values(data):
    """データの中の、伏せるべき値の位置（開始, 終了）の一覧。"""
    spans = []
    for pat in PATTERNS:
        for m in pat.finditer(data):
            v = m.group("v")
            if _usable(v):
                spans.append(m.span("v"))
    # 重なりを除く
    spans.sort()
    out = []
    for s, e in spans:
        if out and s < out[-1][1]:
            continue
        out.append((s, e))
    return out


def string_literals_on_line(data, line_no):
    """指定した行の文字列リテラル（'...' / "..."）の中身の位置。人が「この行にパスワードがある」と指定したとき用。"""
    lines = data.split(b"\n")
    if not 1 <= line_no <= len(lines):
        return []
    start = sum(len(x) + 1 for x in lines[:line_no - 1])
    line = lines[line_no - 1]
    spans = []
    for m in re.finditer(_Q, line):
        before, after = line[:m.start()], line[m.end():]
        # 定数の名前（define('DB_USER', …) の1つ目）と配列のキー（'user' => / ['user']）は伏せない
        if re.search(rb"define\s*\(\s*$", before, re.I) or re.match(rb"\s*(=>|\])", after):
            continue
        if _usable(m.group("v")):
            spans.append((start + m.start("v"), start + m.end("v")))
    if not spans:   # クォートが無い形式（.env / SetEnv など）は、= か空白の後ろを値とみなす
        m = re.search(rb"[=:\s]\s*(?P<v>[^\s'\"#;]+)\s*\r?$", line)
        if m and _usable(m.group("v")):
            spans = [(start + m.start("v"), start + m.end("v"))]
    return spans


# ---------------------------------------------------------------- 保存場所（作業フォルダの外）

def state():
    st = load_json(MASKED)
    if st is None:
        st = {"site_id": uuid.uuid4().hex, "next": 1, "files": {}}
    return st


def store_path(st):
    return tools_dir() / "secrets" / f"{st['site_id']}.json"


def load_store(st):
    p = store_path(st)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_store(st, store):
    p = store_path(st)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(store), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, p)


def mask_spans(path, data, spans, st, store):
    """data の spans を印に置き換えて path に書く。置き換えた数を返す。"""
    if not spans:
        return 0
    out, pos, ids = [], 0, []
    for s, e in spans:
        ph = f"__PHPUP_SECRET_{st['next']:04d}__"
        st["next"] += 1
        store[ph] = base64.b64encode(data[s:e]).decode()
        out += [data[pos:s], ph.encode()]
        pos = e
        ids.append(ph)
    out.append(data[pos:])
    Path(path).write_bytes(b"".join(out))
    key = rel(path)
    st["files"].setdefault(key, [])
    st["files"][key] += ids
    return len(ids)


def unmask_bytes(data, store, where=""):
    """印を本物の値に戻す。知らない印があれば ValueError。"""
    def rep(m):
        ph = m.group(0).decode()
        if ph not in store:
            raise ValueError(f"{where}: 元の値が見つからない印があります: {ph}")
        return base64.b64decode(store[ph])
    return PH_RE.sub(rep, data)


def save_state(st):
    save_json(MASKED, st)
