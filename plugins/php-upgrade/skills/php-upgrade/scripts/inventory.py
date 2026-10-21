"""サイトの中身を調べる（run.sh inventory [--offline]）。

- サイトの種類（WordPress / Laravel / Symfony / ほか / 素のPHP）
- WordPress なら本体のバージョン、プラグイン・テーマ（ヘッダーから読む）と、
  WordPress.org での最新版・必要なPHP・配布状況
- どのファイルを互換性の点検にかけるか（自作・ディレクトリ外のものだけ）
- UTF-8 でないファイル（Shift_JIS / EUC-JP など。修正時に文字化けさせないため）

wp-config.php / .env は開かない。サーバーには接続しない（WordPress.org の公開APIだけ使う）。
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from common import (OUT, PHP_EXTS, SKIP_DIR_NAMES, ensure_out, is_secret, rel,
                    save_json, today, tools_dir, vtuple)

ap = argparse.ArgumentParser()
ap.add_argument("--offline", action="store_true", help="WordPress.org に問い合わせない")
ap.add_argument("--include-vendor", action="store_true", help="composer の vendor/ も点検対象にする")
a = ap.parse_args()

CACHE = tools_dir() / "api-cache"
ABANDONED_DAYS = 730
WPORG_ALIAS = {("plugin", "hello"): "hello-dolly"}

# WordPress 本体のファイル（ルート直下）
WP_CORE_ROOT_FILES = {
    "index.php", "wp-activate.php", "wp-blog-header.php", "wp-comments-post.php", "wp-config-sample.php",
    "wp-cron.php", "wp-links-opml.php", "wp-load.php", "wp-login.php", "wp-mail.php", "wp-settings.php",
    "wp-signup.php", "wp-trackback.php", "xmlrpc.php",
}
# wp-content の中で点検しないもの
WP_CONTENT_SKIP = {"uploads", "cache", "upgrade", "languages", "backups", "backup", "ai1wm-backups", "updraft", "wflogs"}
# どこにあっても点検しない生成物
GENERATED_DIRS = [("storage", "framework"), ("var", "cache"), ("bootstrap", "cache")]


# ---------------------------------------------------------------- WordPress.org API

def api(url):
    if a.offline:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if key.exists() and time.time() - key.stat().st_mtime < 86400:
        return json.loads(key.read_text(encoding="utf-8"))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "inoken-php-upgrade/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:   # 見つからないときは 404 で JSON が返る
        body = e.read().decode("utf-8", "replace")
    except Exception:
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    key.write_text(json.dumps(data), encoding="utf-8")
    return data


def wporg(kind, slug):
    """kind = plugins | themes。返り値: dict（status = listed / closed / missing / unknown）"""
    q = {"action": f"{kind[:-1]}_information", "request[slug]": slug}
    for f in ("sections", "description", "reviews", "screenshots", "banners", "icons", "contributors",
              "versions", "ratings", "downloadlink", "tags", "donate_link", "compatibility"):
        q[f"request[fields][{f}]"] = "0"
    d = api(f"https://api.wordpress.org/{kind}/info/1.2/?" + urllib.parse.urlencode(q))
    if d is None:
        return {"status": "unknown"}
    if isinstance(d, dict) and d.get("error"):
        if d.get("error") == "closed" or d.get("closed"):
            return {"status": "closed", "name": d.get("name"), "closed_date": d.get("closed_date"),
                    "reason": d.get("reason_text") or d.get("reason")}
        return {"status": "missing"}
    if not isinstance(d, dict) or not d.get("version"):
        return {"status": "missing"}
    lu = d.get("last_updated") or ""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", lu)
    return {"status": "listed", "name": d.get("name"), "latest": d.get("version"),
            "requires_php": d.get("requires_php") or None, "requires_wp": d.get("requires") or None,
            "last_updated": m.group(1) if m else None}


def wp_latest_core():
    d = api("https://api.wordpress.org/core/version-check/1.7/")
    try:
        return d["offers"][0]["current"]
    except Exception:
        return None


# ---------------------------------------------------------------- ファイルの読み取り

def read_head(path, n=8192):
    with open(path, "rb") as f:
        return f.read(n).decode("utf-8", "replace")


def headers(path, names):
    """WordPress 形式のファイルヘッダー（Plugin Name: など）を読む。"""
    txt = read_head(path)
    out = {}
    for name in names:
        m = re.search(r"^[ \t/*#@]*" + re.escape(name) + r":(.*)$", txt, re.M | re.I)
        if m:
            v = re.sub(r"\s*(?:\*/|\?>).*$", "", m.group(1)).strip()
            if v:
                out[name] = v
    return out


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def same_name(a_, b_):
    x, y = norm(a_), norm(b_)
    return bool(x and y) and (x == y or x in y or y in x)


def detect_encoding(path):
    b = Path(path).read_bytes()
    try:
        b.decode("utf-8")
        return "utf-8-bom" if b.startswith(b"\xef\xbb\xbf") else "utf-8"
    except UnicodeDecodeError:
        pass
    for enc in ("cp932", "euc_jp"):
        try:
            b.decode(enc)
            return "shift_jis" if enc == "cp932" else "euc-jp"
        except UnicodeDecodeError:
            continue
    return "unknown"


# ---------------------------------------------------------------- サイトの種類

def composer_packages(base):
    lock = base / "composer.lock"
    pk = {}
    if lock.exists():
        try:
            d = json.loads(lock.read_text(encoding="utf-8"))
            for p in d.get("packages", []) + d.get("packages-dev", []):
                pk[p["name"]] = p.get("version")
        except Exception:
            pass
    return pk


def composer_php_constraint(base):
    cj = base / "composer.json"
    if cj.exists():
        try:
            return json.loads(cj.read_text(encoding="utf-8")).get("require", {}).get("php")
        except Exception:
            return None
    return None


def find_wp_roots():
    roots = []
    for dirpath, dirnames, filenames in os.walk("."):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES and d != "wp-content"]
        depth = Path(dirpath).parts
        if len(depth) > 3:
            dirnames[:] = []
            continue
        if os.path.basename(dirpath) == "wp-includes" and "version.php" in filenames:
            roots.append(Path(os.path.dirname(dirpath) or "."))
            dirnames[:] = []
    return sorted(roots, key=lambda p: len(p.parts))


def wp_version(root):
    m = re.search(r"\$wp_version\s*=\s*'([^']+)'", (root / "wp-includes" / "version.php").read_text("utf-8", "replace"))
    return m.group(1) if m else None


FRAMEWORKS = [
    ("Laravel", "laravel/framework"), ("Symfony", "symfony/http-kernel"), ("CakePHP", "cakephp/cakephp"),
    ("CodeIgniter 4", "codeigniter4/framework"), ("EC-CUBE", "ec-cube/ec-cube"), ("Slim", "slim/slim"),
    ("Laminas", "laminas/laminas-mvc"), ("Yii", "yiisoft/yii2"),
]


def detect_frameworks(base):
    pk = composer_packages(base)
    found = []
    for label, name in FRAMEWORKS:
        if name in pk:
            found.append({"name": label, "package": name, "version": pk[name]})
    if (base / "system" / "core" / "CodeIgniter.php").exists():
        found.append({"name": "CodeIgniter 3", "package": None, "version": None})
    if (base / "data" / "class" / "SC_Initial.php").exists():
        found.append({"name": "EC-CUBE 2", "package": None, "version": None})
    if (base / "lib" / "Cake").exists() or (base / "cake" / "libs").exists():
        found.append({"name": "CakePHP 1/2", "package": None, "version": None})
    return found


# ---------------------------------------------------------------- WordPress の部品

def wp_components(root):
    wc = root / "wp-content"
    comps = []
    pdir = wc / "plugins"
    if pdir.is_dir():
        for e in sorted(pdir.iterdir()):
            main, hdr = None, {}
            cands = [e] if e.is_file() and e.suffix == ".php" else sorted(e.glob("*.php")) if e.is_dir() else []
            for f in cands:
                h = headers(f, ["Plugin Name", "Version", "Requires PHP", "Author", "Update URI"])
                if "Plugin Name" in h:
                    main, hdr = f, h
                    break
            if main is None:
                continue
            slug = e.stem if e.is_file() else e.name
            comps.append({"kind": "plugin", "slug": slug, "path": rel(e), "main": rel(main),
                          "name": hdr.get("Plugin Name"), "version": hdr.get("Version"),
                          "requires_php": hdr.get("Requires PHP"), "author": hdr.get("Author"),
                          "update_uri": hdr.get("Update URI")})
    tdir = wc / "themes"
    if tdir.is_dir():
        for e in sorted(p for p in tdir.iterdir() if p.is_dir()):
            css = e / "style.css"
            if not css.exists():
                continue
            h = headers(css, ["Theme Name", "Version", "Template", "Requires PHP", "Author", "Update URI"])
            comps.append({"kind": "theme", "slug": e.name, "path": rel(e), "main": rel(css),
                          "name": h.get("Theme Name"), "version": h.get("Version"),
                          "parent": h.get("Template"), "requires_php": h.get("Requires PHP"),
                          "author": h.get("Author"), "update_uri": h.get("Update URI")})
    if (wc / "mu-plugins").is_dir():
        comps.append({"kind": "mu-plugins", "slug": "mu-plugins", "path": rel(wc / "mu-plugins"),
                      "name": "mu-plugins（必ず読み込まれるプラグイン）"})
    drop = [rel(f) for f in sorted(wc.glob("*.php")) if f.name != "index.php"] if wc.is_dir() else []
    if drop:
        comps.append({"kind": "dropins", "slug": "dropins", "path": rel(wc), "files": drop,
                      "name": "ドロップイン（wp-content 直下の PHP）"})
    return comps


def classify(c):
    """WordPress.org を引いて、点検するか（scan）と出どころ（origin）を決める。"""
    if c["kind"] in ("mu-plugins", "dropins"):
        c.update(origin="custom", scan=True)
        return
    uri = (c.get("update_uri") or "").lower()
    if uri and "wordpress.org" not in uri and uri not in ("false",):
        c.update(origin="external", scan=True, note="Update URI が WordPress.org 以外（有料・自社配布）")
        return
    # WordPress 同梱の Hello Dolly は、WordPress.org では hello-dolly という名前
    info = wporg(c["kind"] + "s", WPORG_ALIAS.get((c["kind"], c["slug"]), c["slug"]))
    c["wporg"] = info
    st = info["status"]
    if st == "listed" and not same_name(c.get("name"), info.get("name")):
        c.update(origin="custom", scan=True,
                 note=f"WordPress.org に同じフォルダ名の「{info.get('name')}」があるが名前が違う。自作の可能性")
        return
    if st == "listed":
        c["origin"] = "wporg"
        c["outdated"] = bool(c.get("version") and info.get("latest") and vtuple(c["version"]) < vtuple(info["latest"]))
        lu = info.get("last_updated")
        old = False
        if lu:
            y, m, d = (int(x) for x in lu.split("-"))
            old = (datetime.date.today() - datetime.date(y, m, d)).days > ABANDONED_DAYS
        c["abandoned"] = old
        # 更新すれば済むものは点検しない。最新なのに2年以上更新が無いものだけ参考に点検する
        c["scan"] = (not c["outdated"]) and old
        return
    if st == "closed":
        c.update(origin="closed", scan=True, note="WordPress.org で配布停止")
        return
    if st == "unknown":
        c.update(origin="unknown", scan=True, note="WordPress.org に問い合わせできなかった")
        return
    c.update(origin="external", scan=True, note="WordPress.org に無い（自作・有料・配布元が別）")


# ---------------------------------------------------------------- 点検対象のファイル

def component_of(path, wp_root, comps_by_path):
    """ファイルがどの部品に属するか。WordPress 本体なら 'core'。"""
    p = Path(path)
    if wp_root is not None:
        try:
            r = p.relative_to(wp_root)
        except ValueError:
            r = None
        if r is not None:
            parts = r.parts
            if parts and parts[0] in ("wp-admin", "wp-includes"):
                return "core"
            if len(parts) == 1 and parts[0] in WP_CORE_ROOT_FILES:
                return "core"
            if parts and parts[0] == "wp-content":
                if len(parts) >= 2 and parts[1] in WP_CONTENT_SKIP:
                    return "skip"
                if len(parts) >= 3 and parts[1] in ("plugins", "themes"):
                    # プラグインはフォルダ（plugins/slug）か単体ファイル（plugins/hello.php）
                    return comps_by_path.get(rel(wp_root / "wp-content" / parts[1] / parts[2]), "orphan")
                if len(parts) >= 3 and parts[1] == "mu-plugins":
                    return comps_by_path.get(rel(wp_root / "wp-content" / "mu-plugins"), "orphan")
                if len(parts) == 2:
                    return "dropins" if parts[1] != "index.php" else "skip"
                return "orphan"
    if "vendor" in p.parts:
        return "vendor"
    for a_, b_ in GENERATED_DIRS:
        for i in range(len(p.parts) - 1):
            if p.parts[i] == a_ and p.parts[i + 1] == b_:
                return "skip"
    return "site"


def walk_php():
    for dirpath, dirnames, filenames in os.walk("."):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIR_NAMES)
        for fn in sorted(filenames):
            if Path(fn).suffix.lower() in PHP_EXTS and not is_secret(fn):
                yield rel(os.path.join(dirpath, fn))


# ---------------------------------------------------------------- 本体

ensure_out()
base = Path(".")
wp_roots = find_wp_roots()
wp_root = wp_roots[0] if wp_roots else None
inv = {"date": today(), "root": os.path.basename(os.path.abspath(".")), "type": "php",
       "wordpress": None, "frameworks": detect_frameworks(base),
       "composer_php": composer_php_constraint(base), "components": [], "notes": []}

comps = []
if wp_root is not None:
    inv["type"] = "wordpress"
    inv["wordpress"] = {"root": rel(wp_root), "version": wp_version(wp_root), "latest": wp_latest_core()}
    if len(wp_roots) > 1:
        inv["notes"].append("WordPress が複数あります: " + ", ".join(rel(r) for r in wp_roots)
                            + f"。点検したのは {rel(wp_root)} だけです。他はそのフォルダで別に実行してください。")
    comps = wp_components(wp_root)
    for c in comps:
        classify(c)
elif inv["frameworks"]:
    inv["type"] = "framework"

comps_by_path = {c["path"]: c["slug"] if c["kind"] in ("mu-plugins", "dropins") else f"{c['kind']}:{c['slug']}" for c in comps}
scan_ids = {("mu-plugins" if c["kind"] == "mu-plugins" else "dropins" if c["kind"] == "dropins" else f"{c['kind']}:{c['slug']}")
            for c in comps if c.get("scan")}

other_wp = [r for r in wp_roots[1:] if r != wp_root]


def under_other_wp(f):
    return any(Path(f).is_relative_to(r) for r in other_wp)


files, counts, skipped_secret = [], {}, 0
for f in walk_php():
    # 2つ目以降の WordPress は、そのフォルダで別に点検する（本体を自作扱いで点検しないように）
    comp = "other-wordpress" if under_other_wp(f) else component_of(f, wp_root, comps_by_path)
    counts[comp] = counts.get(comp, 0) + 1
    take = comp in scan_ids or comp in ("site", "orphan") or (comp == "vendor" and a.include_vendor)
    if take:
        files.append({"file": f, "component": comp})
for dirpath, dirnames, filenames in os.walk("."):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
    skipped_secret += sum(1 for fn in filenames if is_secret(fn))

# uploads に PHP があるのは、改ざん（バックドア設置）でよくある形
if wp_root is not None and (wp_root / "wp-content" / "uploads").is_dir():
    up_php = [rel(os.path.join(d, f)) for d, _, fs in os.walk(wp_root / "wp-content" / "uploads")
              for f in fs if Path(f).suffix.lower() in PHP_EXTS and f != "index.php"]
    if up_php:
        inv["uploads_php"] = up_php
        inv["notes"].append(f"⚠️ wp-content/uploads の中に PHP ファイルが {len(up_php)} 件あります（例: {', '.join(up_php[:3])}）。"
                            "画像置き場に PHP があるのは改ざんでよくある形です。中身を確認してください（このスキルは実行も修正もしません）。")

enc = {}
for x in files:
    e = detect_encoding(x["file"])
    if e not in ("utf-8",):
        enc.setdefault(e, []).append(x["file"])

inv["components"] = comps
inv["scan_files"] = files
inv["file_counts"] = counts
inv["encodings"] = {k: v for k, v in enc.items()}
inv["secret_files_skipped"] = skipped_secret
if counts.get("vendor") and not a.include_vendor:
    inv["notes"].append(f"composer の vendor/（{counts['vendor']} ファイル）は点検していません。composer の依存は composer update で上げる前提です（--include-vendor で点検対象にできます）。")
save_json(OUT / "inventory.json", inv)

# ---- 画面への要約
print(f"サイト: {inv['root']}（{ {'wordpress': 'WordPress', 'framework': 'フレームワーク', 'php': '素のPHP'}[inv['type']] }）")
if inv["wordpress"]:
    w = inv["wordpress"]
    print(f"  WordPress {w['version']}（最新 {w['latest'] or '不明'}）  場所: {w['root']}")
for fw in inv["frameworks"]:
    print(f"  フレームワーク: {fw['name']} {fw['version'] or ''}")
if inv["composer_php"]:
    print(f"  composer.json の PHP 指定: {inv['composer_php']}")
by = {}
for c in comps:
    by.setdefault(c.get("origin"), []).append(c)
lab = {"wporg": "WordPress.org 配布", "external": "ディレクトリ外（自作・有料）", "custom": "自作",
       "closed": "配布停止", "unknown": "確認できず"}
for k, v in by.items():
    out = [f"{c['slug']}{' ⬆' if c.get('outdated') else ''}" for c in v]
    print(f"  {lab.get(k, k)}: {len(v)} 件  {', '.join(out)}")
print(f"  点検対象: {len(files)} ファイル（本体・更新で済む既製品は除外）")
if enc:
    print("  ⚠️ UTF-8 以外のファイル: " + ", ".join(f"{k} {len(v)} 件" for k, v in enc.items()) + " → 修正時は文字コードを保つこと")
if skipped_secret:
    print(f"  認証情報のファイル {skipped_secret} 件は開かずに除外しました")
for n in inv["notes"]:
    print("  ※ " + n)
