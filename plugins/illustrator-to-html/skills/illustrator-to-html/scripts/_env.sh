# _env.sh - 各 .sh から source する。OS差（macOS / Windows Git Bash / WSL）をここで吸収する。
#
#   PLATFORM   mac | win | wsl | other
#   PY         使える Python 3 のコマンド（配列）。"${PY[@]}" で呼ぶ
#   to_native  パスを Python / node に渡せる形にする（Windows では C:/… 形式）
#   to_ai / from_ai  Illustrator とのパスの受け渡し
#   PS         Windows PowerShell の実行ファイル（win / wsl のみ）
#
# Windows の python3 / python は Microsoft Store を開くだけのスタブのことがあるので、
# 「実行して本当に Python 3 が返るか」で選ぶ。

case "$(uname -s)" in
  Darwin)                PLATFORM="mac" ;;
  MINGW*|MSYS*|CYGWIN*)  PLATFORM="win" ;;
  Linux)
    if grep -qi microsoft /proc/version 2>/dev/null; then PLATFORM="wsl"; else PLATFORM="other"; fi ;;
  *)                     PLATFORM="other" ;;
esac

# Windows の Python が日本語や記号（✓ Δ など）を cp932 で出して化けたり落ちたりしないように
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

PY=()
for _c in "python3" "python" "py -3"; do
  # shellcheck disable=SC2086
  if command -v ${_c%% *} >/dev/null 2>&1 && \
     ${_c} -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    read -r -a PY <<< "$_c"
    break
  fi
done
unset _c

to_native() {   # node / Python に渡すパス（WSL ではどちらも Linux 側で動くのでそのまま）
  case "$PLATFORM" in
    win) cygpath -m "$1" ;;
    *)   printf '%s' "$1" ;;
  esac
}

to_ai() {       # Illustrator（ExtendScript）に渡すパス
  case "$PLATFORM" in
    win) cygpath -m "$1" ;;
    wsl) wslpath -m "$1" ;;
    *)   printf '%s' "$1" ;;
  esac
}

from_ai() {     # Illustrator が返したパスをシェルで扱える形に戻す
  case "$PLATFORM" in
    win) cygpath -u "$1" ;;
    wsl) wslpath -u "$1" ;;
    *)   printf '%s' "$1" ;;
  esac
}

PS=""
case "$PLATFORM" in
  win) PS="powershell.exe" ;;
  wsl) PS="/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe" ;;
esac

need_py() {
  if [ ${#PY[@]} -eq 0 ]; then
    echo "Python 3 が見つかりません。preflight.sh を実行して導入手順を確認してください。" >&2
    exit 1
  fi
}
