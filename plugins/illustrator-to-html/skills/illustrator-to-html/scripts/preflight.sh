#!/usr/bin/env bash
#
# preflight.sh - このスキルが動く環境か確認する
#
#   ./preflight.sh
#
# macOS と Windows（Claude Code の Git Bash）に対応。
# 足りないものがあれば、何をすればいいかを出して終了コード1で終わる。
#
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_env.sh
. "$HERE/_env.sh"
NG=0

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
ng()   { printf '  \033[31m✗\033[0m %s\n' "$1"; NG=1; }

echo "illustrator-to-html 前提チェック"
echo

# --- OS / Illustrator ---
case "$PLATFORM" in
  mac)
    ok "macOS"
    AI_APP="$(ls -d /Applications/Adobe\ Illustrator*/Adobe\ Illustrator.app 2>/dev/null | tail -1)"
    if [ -n "$AI_APP" ]; then ok "Adobe Illustrator: $AI_APP"
    else ng "Adobe Illustrator が見つからない（フェーズ1の .ai 読み取りに必要）"; fi
    command -v osascript >/dev/null 2>&1 && ok "osascript" || ng "osascript が無い"
    ;;
  win|wsl)
    [ "$PLATFORM" = "win" ] && ok "Windows（Git Bash）" || ok "Windows（WSL）"
    if [ -n "$PS" ] && command -v "$PS" >/dev/null 2>&1 || [ -x "$PS" ]; then
      ok "PowerShell"
      PROGID="${AI_PROGID:-Illustrator.Application}"
      AI_EXE="$("$PS" -NoProfile -Command "\$c=(Get-ItemProperty 'Registry::HKEY_CLASSES_ROOT\\$PROGID\\CLSID' -EA SilentlyContinue).'(default)'; if(\$c){(Get-ItemProperty ('Registry::HKEY_CLASSES_ROOT\\CLSID\\'+\$c+'\\LocalServer32') -EA SilentlyContinue).'(default)'}" 2>/dev/null | tr -d '\r')"
      if [ -n "$AI_EXE" ]; then
        ok "Adobe Illustrator（COM: $PROGID）: ${AI_EXE% /Automation}"
      else
        ng "Adobe Illustrator が見つからない（COM: $PROGID 未登録）。Illustrator を一度起動してから再確認。複数版あるなら AI_PROGID で指定"
      fi
    else
      ng "PowerShell が見つからない"
    fi
    ;;
  *)
    ng "macOS か Windows が必要（Illustrator を操作するため）。現在: $(uname -s)"
    ;;
esac

# --- Chrome / Edge ---
BROWSER=""
CANDS=("${CHROME_PATH:-}")
case "$PLATFORM" in
  mac) CANDS+=("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
               "/Applications/Chromium.app/Contents/MacOS/Chromium"
               "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge") ;;
  win) CANDS+=("/c/Program Files/Google/Chrome/Application/chrome.exe"
               "/c/Program Files (x86)/Google/Chrome/Application/chrome.exe"
               "${LOCALAPPDATA:+$(cygpath -u "$LOCALAPPDATA")/Google/Chrome/Application/chrome.exe}"
               "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
               "/c/Program Files/Microsoft/Edge/Application/msedge.exe") ;;
  *)   CANDS+=("/usr/bin/google-chrome" "/usr/bin/chromium" "/usr/bin/chromium-browser") ;;
esac
for p in "${CANDS[@]}"; do
  [ -n "$p" ] && [ -f "$p" ] && { BROWSER="$p"; break; }
done
if [ -n "$BROWSER" ]; then
  ok "ブラウザ: $BROWSER"
else
  ng "Chrome / Edge が見つからない（フェーズ4の検証に必要）。CHROME_PATH で指定可"
fi

# --- node / npm ---
for c in node npm; do
  if command -v "$c" >/dev/null 2>&1; then ok "$c: $(command -v "$c")"
  else
    case "$PLATFORM" in
      win) ng "$c が無い →  winget install OpenJS.NodeJS.LTS （入れたら Claude Code を再起動）" ;;
      *)   ng "$c が無い" ;;
    esac
  fi
done

# --- Python ---
if [ ${#PY[@]} -gt 0 ]; then
  ok "Python: ${PY[*]} ($("${PY[@]}" -c 'import sys; print("%d.%d" % sys.version_info[:2])'))"
  if "${PY[@]}" -c 'import PIL' >/dev/null 2>&1; then ok "Pillow（pixdiff.py 用）"
  else warn "Pillow が無い（pixdiff.py の画素照合だけ使えない）→  ${PY[*]} -m pip install --user Pillow"; fi
else
  case "$PLATFORM" in
    win) ng "Python 3 が無い →  winget install Python.Python.3.12 （python3 が Microsoft Store を開くだけなら、それはスタブなので無視してよい）" ;;
    *)   ng "Python 3 が無い" ;;
  esac
fi

# --- 依存パッケージ ---
if [ -d "$HERE/node_modules/puppeteer-core" ]; then
  ok "puppeteer-core"
else
  ng "puppeteer-core 未インストール →  cd \"$HERE\" && npm install"
fi

# --- 和文フォント（実装精度の話。無くても動く） ---
# system_profiler へのパイプは grep -q の早期終了で SIGPIPE になり
# pipefail と組むと誤検知するので、フォントファイルを直接探す。
case "$PLATFORM" in
  mac) FONTLIST="$(ls /System/Library/Fonts /System/Library/Fonts/Supplemental /Library/Fonts "$HOME/Library/Fonts" 2>/dev/null || true)" ;;
  win) FONTLIST="$(ls /c/Windows/Fonts "${LOCALAPPDATA:+$(cygpath -u "$LOCALAPPDATA")/Microsoft/Windows/Fonts}" 2>/dev/null || true)" ;;
  wsl) FONTLIST="$(ls /mnt/c/Windows/Fonts 2>/dev/null || true)" ;;
  *)   FONTLIST="" ;;
esac
if printf '%s' "$FONTLIST" | grep -qi "yugoth\|yumin\|hiragino\|ヒラギノ\|meiryo"; then
  ok "和文フォント（游ゴシック / 游明朝 / ヒラギノ / メイリオ）"
else
  warn "游ゴシック・游明朝・ヒラギノ・メイリオが見当たらない。references/pitfalls.md のフォント対応表は環境に合わせて読み替えること"
fi

echo
if [ "$NG" -eq 0 ]; then
  echo "問題なし。"
else
  echo "上の ✗ を解消してから使ってください。"
fi
exit "$NG"
