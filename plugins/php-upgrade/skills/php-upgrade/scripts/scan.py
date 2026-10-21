"""互換性を点検する（run.sh scan [--force]）。

- 移行先が同じ系列内のパッチ更新（例: 8.2.32 → 8.2.35）なら、PHPの動きは変わらないので点検を省く
- 系列をまたぐときは、inventory が選んだファイルだけを PHPCompatibility（testVersion=移行先の系列）で点検する
- 移行先と同じ系列の PHP が手元にあれば（PHP_LINT_BIN か PHP_BIN）、php -l で構文も確かめる

結果は .php-upgrade/scan.json。メッセージは PHPCompatibility の英語のまま残し、分類だけ日本語にする。
"""
import argparse
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import OUT, branch, die, require, save_json, today, tools_dir

ap = argparse.ArgumentParser()
ap.add_argument("--force", action="store_true", help="パッチ更新でも点検する")
a = ap.parse_args()

tgt = require("target.json", "run.sh target <今のPHP版>")
inv = require("inventory.json", "run.sh inventory")
PHP = os.environ.get("PHP_BIN", "php")
TOOLS = tools_dir()
PHPCS = TOOLS / "vendor" / "squizlabs" / "php_codesniffer" / "bin" / "phpcs"

CATEGORY = {
    "FunctionUse": "関数の使い方", "ParameterValues": "引数の値", "Classes": "クラス", "Syntax": "構文",
    "TextStrings": "文字列", "Variables": "変数", "Operators": "演算子", "IniDirectives": "php.ini の設定",
    "Extensions": "拡張機能", "LanguageConstructs": "言語構造", "ControlStructures": "制御構文",
    "Keywords": "予約語", "Constants": "定数", "FunctionDeclarations": "関数の宣言", "FunctionNameRestrictions": "関数名",
    "Interfaces": "インターフェース", "TypeCasts": "型変換", "Generators": "ジェネレーター", "Lists": "list()",
    "MethodUse": "メソッドの使い方", "Miscellaneous": "その他", "Upgrade": "その他", "Attributes": "属性",
    "Namespaces": "名前空間", "Numbers": "数値", "Lint": "構文エラー",
}


def category(source):
    parts = (source or "").split(".")
    return CATEGORY.get(parts[1] if len(parts) > 1 else "", "その他")


files = [x["file"] for x in inv["scan_files"]]
comp_of = {x["file"]: x["component"] for x in inv["scan_files"]}
res = {"date": today(), "target": tgt["target"], "testVersion": tgt["target_branch"], "skipped": False,
       "standard": None, "files": len(files), "lint": None, "issues": [], "tool_errors": []}

if tgt["mode"] in ("none", "patch") and not a.force:
    res["skipped"] = True
    res["skip_reason"] = ("すでに修正版" if tgt["mode"] == "none"
                          else f"同じ系列内（{tgt['current']} → {tgt['target']}）のパッチ更新なので、PHPの動きは変わらない")
    save_json(OUT / "scan.json", res)
    print(f"点検を省きました: {res['skip_reason']}")
    raise SystemExit(0)

if not PHPCS.exists():
    die("点検ツールが入っていません。run.sh setup を実行してください。")
if not files:
    save_json(OUT / "scan.json", res)
    print("点検対象のファイルがありません（本体と更新で済む既製品だけでした）。")
    raise SystemExit(0)

# ---- PHPCompatibility
std = "PHPCompatibilityWP" if inv["type"] == "wordpress" else "PHPCompatibility"
res["standard"] = std
flist = OUT / "scan-files.txt"
flist.write_text("\n".join(files) + "\n", encoding="utf-8")
rep = OUT / "phpcs.json"
cmd = [PHP, "-d", "memory_limit=2G", str(PHPCS), f"--standard={std}", "--runtime-set", "testVersion", tgt["target_branch"],
       "--report=json", f"--report-file={rep}", f"--file-list={flist}", "--basepath=.", "-q", "--no-colors", "-s"]
if os.name != "nt":
    cmd.append("--parallel=4")
print(f"点検中: {len(files)} ファイル（{std} / PHP {tgt['target_branch']}）...")
p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
# phpcs は指摘があると終了コード 1 / 2 を返す。レポートが出ていれば正常
if not rep.exists():
    die("点検ツールが失敗しました:\n" + (p.stderr or p.stdout)[-3000:])
data = json.loads(rep.read_text(encoding="utf-8", errors="replace") or "{}")
for fname, info in data.get("files", {}).items():
    f = Path(fname).as_posix()
    for m in info.get("messages", []):
        src = m.get("source", "")
        if src.startswith("Internal."):
            res["tool_errors"].append({"file": f, "message": m.get("message")})
            continue
        res["issues"].append({"file": f, "line": m.get("line"), "type": m.get("type"), "source": src,
                              "category": category(src), "message": m.get("message"),
                              "component": comp_of.get(f, "site")})

# ---- php -l（移行先と同じ系列の PHP があるときだけ）
def php_branch(binpath):
    try:
        out = subprocess.run([binpath, "-r", "echo PHP_VERSION;"], capture_output=True, text=True, timeout=20).stdout
        return branch(out) if out else None
    except Exception:
        return None


lint_bin = None
for cand in [os.environ.get("PHP_LINT_BIN"), PHP]:
    if cand and php_branch(cand) == tgt["target_branch"]:
        lint_bin = cand
        break

if lint_bin:
    def lint(f):
        r = subprocess.run([lint_bin, "-d", "display_errors=1", "-d", "error_reporting=-1", "-l", f],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        return f, r.returncode, (r.stdout + r.stderr).strip()

    bad = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for f, code, out in ex.map(lint, files):
            msgs = [ln for ln in out.splitlines() if ln and not ln.startswith("No syntax errors")]
            if code != 0 or any("Deprecated" in ln or "Fatal" in ln for ln in msgs):
                bad += 1
                for ln in msgs or [out]:
                    if "Errors parsing" in ln:
                        continue
                    m = re.search(r" on line (\d+)", ln)
                    res["issues"].append({"file": f, "line": int(m.group(1)) if m else None,
                                          "type": "ERROR" if code != 0 or "Fatal" in ln else "WARNING",
                                          "source": "Lint.php-l", "category": "構文エラー" if code != 0 else "非推奨（php -l）",
                                          "message": ln.strip(), "component": comp_of.get(f, "site")})
    res["lint"] = {"php": lint_bin, "files_with_problems": bad}
else:
    res["lint"] = None

# php -l の指摘のうち、PHPCompatibility が同じ行ですでに指摘しているものは重複なので落とす
seen = {(i["file"], i["line"]) for i in res["issues"] if not i["source"].startswith("Lint.")}
res["issues"] = [i for i in res["issues"] if not (i["source"].startswith("Lint.") and (i["file"], i["line"]) in seen)]
res["issues"].sort(key=lambda x: (x["component"], x["file"], x["line"] or 0))
save_json(OUT / "scan.json", res)

E = sum(1 for i in res["issues"] if i["type"] == "ERROR")
W = sum(1 for i in res["issues"] if i["type"] == "WARNING")
print(f"結果: エラー {E} 件（移行先で動かない）／ 警告 {W} 件（非推奨。動くが将来消える）")
by = {}
for i in res["issues"]:
    k = (i["component"], i["type"])
    by[k] = by.get(k, 0) + 1
for (c, t), n in sorted(by.items()):
    print(f"  {c}: {'エラー' if t == 'ERROR' else '警告'} {n}")
if res["tool_errors"]:
    print(f"  ⚠️ 点検ツールが読めなかったファイル: {len(res['tool_errors'])} 件（scan.json の tool_errors）")
print("構文チェック（php -l）: " + (f"実施（{lint_bin}）" if lint_bin else "省略（移行先と同じ系列の PHP が無い）"))
