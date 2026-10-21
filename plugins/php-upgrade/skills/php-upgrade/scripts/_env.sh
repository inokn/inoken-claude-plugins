# _env.sh - run.sh から source する。OS差（macOS / Windows Git Bash / WSL / Linux）をここで吸収する。
#
#   PLATFORM   mac | win | wsl | other
#   PY         使える Python 3 のコマンド（配列）。"${PY[@]}" で呼ぶ
#   PHP_BIN    点検ツール（phpcs）を動かす PHP。環境変数で上書きできる
#   TOOLS_DIR  点検ツールの置き場所（プラグインの自動更新で消えないよう、プラグインの外に置く）
#   TOOLS_DIR_NATIVE  同じ場所を Python に渡せる形で（Windows では C:/… 形式）
#   to_native  パスを Python / PHP に渡せる形にする
#   PHPX       拡張を補った PHP の呼び出し（配列。Windows の php.ini 無しに対応）
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
export PLATFORM

# Windows の Python が日本語を cp932 で出して化けたり落ちたりしないように
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

PY=()
for _c in "python3" "python" "py -3"; do
  # shellcheck disable=SC2086
  if command -v ${_c%% *} >/dev/null 2>&1 && \
     ${_c} -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    read -r -a PY <<< "$_c"
    break
  fi
done
unset _c

to_native() {   # Python / PHP（Windows ではネイティブの exe）に渡すパス。Windows では C:/… 形式
  case "$PLATFORM" in
    win) cygpath -m "$1" ;;
    *)   printf '%s' "$1" ;;
  esac
}

export PHP_BIN="${PHP_BIN:-php}"
export TOOLS_DIR="${PHP_UPGRADE_TOOLS:-$HOME/.cache/inoken-php-upgrade}"
TOOLS_DIR_NATIVE="$(to_native "$TOOLS_DIR")"
export TOOLS_DIR_NATIVE

# PHPX = 拡張を補った PHP の呼び出し（配列）。"${PHPX[@]}" で呼ぶ
# winget で入れた Windows の PHP は php.ini が無く、openssl / mbstring / zip が読み込まれない。
# php.ini を書き換えずに、実行のたびに -d で同じフォルダの ext/ から読み込む。
PHPX=("$PHP_BIN")
if [ "$PLATFORM" = "win" ] && command -v "$PHP_BIN" >/dev/null 2>&1; then
  _ext="$(dirname "$(command -v "$PHP_BIN")")/ext"
  for _e in openssl mbstring zip; do
    if ! "$PHP_BIN" -r "exit(extension_loaded('$_e') ? 0 : 1);" 2>/dev/null && [ -f "$_ext/php_$_e.dll" ]; then
      [ "${#PHPX[@]}" -eq 1 ] && PHPX+=(-d "extension_dir=$(to_native "$_ext")")
      PHPX+=(-d "extension=$_e")
    fi
  done
  unset _ext _e
fi

need_py() {
  if [ ${#PY[@]} -eq 0 ]; then
    echo "Python 3 が見つかりません。run.sh preflight を実行して導入手順を確認してください。" >&2
    exit 1
  fi
}
