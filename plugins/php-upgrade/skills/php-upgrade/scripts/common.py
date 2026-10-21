"""php-upgrade の各スクリプトで共有する小物。

カレントディレクトリ＝サイトのルート。出力はすべて ./.php-upgrade/ に置く。
"""
import datetime
import json
import os
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
OUT = Path(".php-upgrade")

# 点検しないディレクトリ（どこにあっても）
SKIP_DIR_NAMES = {".git", ".php-upgrade", "node_modules", ".svn", ".idea", ".vscode", "templates_c"}
# 読まない・点検しないファイル（認証情報が入る）
SECRET_NAMES = {"wp-config.php", ".env"}
PHP_EXTS = {".php", ".inc", ".phtml", ".php3", ".php4", ".php5", ".php7"}


def tools_dir():
    """点検ツールの置き場所。run.sh が Python に渡せる形（TOOLS_DIR_NATIVE）で教えてくれる。"""
    d = os.environ.get("TOOLS_DIR_NATIVE") or os.environ.get("PHP_UPGRADE_TOOLS")
    return Path(d) if d else Path.home() / ".cache" / "inoken-php-upgrade"


def die(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def today():
    return datetime.date.today().isoformat()


def load_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def targets():
    return load_json(SKILL_DIR / "references" / "targets.json")


def vtuple(v):
    """'8.2.32' -> (8, 2, 32)。数字以外は無視する。"""
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])


def branch(v):
    t = vtuple(v)
    return f"{t[0]}.{t[1]}" if len(t) >= 2 else str(t[0])


def require(path, hint):
    data = load_json(OUT / path)
    if data is None:
        die(f"{OUT / path} がありません。先に {hint} を実行してください。")
    return data


def is_secret(name):
    return name in SECRET_NAMES or name.startswith(".env.")


def ensure_out():
    OUT.mkdir(exist_ok=True)
    # 出力フォルダ自体をサイトのファイルとして扱わない
    gi = OUT / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n", encoding="utf-8")


def notes():
    """Claude（や人）が .php-upgrade/確認事項.md に書いた確認事項。「- 」で始まる行を1件として読む。"""
    p = OUT / "確認事項.md"
    if not p.exists():
        return []
    return [ln[2:].strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.startswith("- ") and ln[2:].strip()]


def rel(p):
    return Path(os.path.relpath(p, ".")).as_posix()
