#!/usr/bin/env bash
#
# ai2spec.sh - Illustrator の .ai をコーディング用の仕様JSON + 参照PNG に落とす
#
#   ./ai2spec.sh design.ai              # 開いて書き出し → design_spec/
#   ./ai2spec.sh --current              # いま Illustrator で開いている最前面のドキュメント
#   ./ai2spec.sh design.ai -o ./spec    # 出力先を指定
#   ./ai2spec.sh design.ai --no-png --scale 3 --max 20000 --hidden
#
# 出力: <outdir>/<name>.spec.json と <outdir>/<name>_ab1@2x.png
#
# macOS は osascript、Windows（Git Bash）/ WSL は PowerShell + COM で Illustrator を動かす。
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_env.sh
. "$SCRIPT_DIR/_env.sh"
JSX="$SCRIPT_DIR/ai2json.jsx"
APP="Adobe Illustrator"

SRC=""
OUTDIR=""
PNG="true"
SCALE="2"
MAXITEMS="5000"
HIDDEN="false"

usage() { sed -n '3,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --current)      SRC=""; shift ;;
    -o|--out)       OUTDIR="${2:?-o には出力先ディレクトリが必要です}"; shift 2 ;;
    --no-png)       PNG="false"; shift ;;
    --scale)        SCALE="${2:?--scale には倍率が必要です}"; shift 2 ;;
    --max)          MAXITEMS="${2:?--max には数値が必要です}"; shift 2 ;;
    --hidden)       HIDDEN="true"; shift ;;
    -h|--help)      usage 0 ;;
    -*)             echo "不明なオプション: $1" >&2; usage 1 ;;
    *)              SRC="$1"; shift ;;
  esac
done

[ -f "$JSX" ] || { echo "ai2json.jsx が見つかりません: $JSX" >&2; exit 1; }

if [ -n "$SRC" ]; then
  [ -f "$SRC" ] || { echo "ファイルがありません: $SRC" >&2; exit 1; }
  SRC="$(cd "$(dirname "$SRC")" && pwd)/$(basename "$SRC")"
fi
if [ -n "$OUTDIR" ]; then
  mkdir -p "$OUTDIR"
  OUTDIR="$(cd "$OUTDIR" && pwd)"
fi

# JSX に渡すオプションをブートストラップとして組み立てる。
# パスに日本語が含まれても壊れないよう、UTF-8 で書いて Illustrator 側も UTF-8 で読む。
jsesc() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }

BOOTDIR="$(mktemp -d -t ai2spec.XXXXXX)"
BOOT="$BOOTDIR/boot.jsx"
trap 'rm -rf "$BOOTDIR"' EXIT
{
  printf 'var A2J = { outDir: %s, png: %s, pngScale: %s, maxItems: %s, includeHidden: %s, round: 2 };\n' \
    "$( [ -n "$OUTDIR" ] && printf '"%s"' "$(jsesc "$(to_ai "$OUTDIR")")" || printf 'null' )" \
    "$PNG" "$SCALE" "$MAXITEMS" "$HIDDEN"
  # Windows では開く処理も JSX 側で行う（COM の Open は省略可能引数の扱いが不安定なため）
  if [ "$PLATFORM" != "mac" ] && [ -n "$SRC" ]; then
    printf 'app.open(new File("%s"));\n' "$(jsesc "$(to_ai "$SRC")")"
  fi
  printf 'var __f = new File("%s");\n' "$(jsesc "$(to_ai "$JSX")")"
  printf '__f.encoding = "UTF-8"; __f.open("r"); var __s = __f.read(); __f.close();\n'
  printf 'eval(__s);\n'
} > "$BOOT"

case "$PLATFORM" in
  mac)
    RESULT="$(osascript - "$BOOT" "$SRC" <<'OSA'
on run argv
  set bootPath to item 1 of argv
  set aiPath to item 2 of argv
  set jsCode to (read (POSIX file bootPath) as «class utf8»)
  tell application "Adobe Illustrator"
    activate
    if aiPath is not "" then
      open (POSIX file aiPath)
    end if
    with timeout of 900 seconds
      set res to do javascript jsCode
    end timeout
  end tell
  return res
end run
OSA
)"
    ;;
  win|wsl)
    RES_FILE="$BOOTDIR/result.txt"
    "$PS" -NoProfile -ExecutionPolicy Bypass -File "$(to_ai "$SCRIPT_DIR/ai_run.ps1")" \
      "$(to_ai "$BOOT")" "$(to_ai "$RES_FILE")" >/dev/null 2>&1 || true
    RESULT="$(cat "$RES_FILE" 2>/dev/null || echo "ERR	Illustrator の呼び出しに失敗しました（ai_run.ps1）")"
    ;;
  *)
    echo "この OS では Illustrator を操作できません（macOS / Windows が必要）" >&2
    exit 1
    ;;
esac

case "$RESULT" in
  OK*)
    JSON="$(from_ai "$(printf '%s' "$RESULT" | cut -f2)")"
    PNGS="$(printf '%s' "$RESULT" | cut -f3)"
    echo "JSON: $JSON"
    if [ -n "$PNGS" ]; then
      printf '%s\n' "$PNGS" | tr '|' '\n' | while IFS= read -r p; do echo "PNG:  $(from_ai "$p")"; done
    fi
    # 何に対して揃っているか（アンカー）の手がかりを JSON に追記して表示する。
    # カンプ幅だけ見ていると右端基準と中央基準の区別がつかないため、ここで先に確定させる。
    if [ -f "$SCRIPT_DIR/alignment.py" ] && [ ${#PY[@]} -gt 0 ]; then
      echo
      "${PY[@]}" "$(to_native "$SCRIPT_DIR/alignment.py")" "$(to_native "$JSON")" || true
    fi
    ;;
  *)
    echo "$RESULT" >&2
    if [ "$PLATFORM" = "win" ] || [ "$PLATFORM" = "wsl" ]; then
      echo "ヒント: Illustrator を先に手で起動し、ダイアログ（ログイン・更新案内など）を閉じてから再実行する。" >&2
      echo "        Illustrator が複数バージョン入っているなら AI_PROGID=Illustrator.Application.<版> で指定する。" >&2
    fi
    exit 1
    ;;
esac
