#!/usr/bin/env bash
#
# preflight.sh - このスキルが動く環境か確認する（run.sh preflight から呼ばれる）
#
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

hint_install() {   # $1 = 何を入れるか（git / python / php）
  case "$PLATFORM:$1" in
    win:git)    echo "      → Git for Windows を入れる: winget install Git.Git" ;;
    win:python) echo "      → winget install Python.Python.3.12 （入れたら Claude Code を再起動）" ;;
    win:php)    echo "      → winget install PHP.PHP.8.4 （入れたら Claude Code を再起動）" ;;
    mac:git)    echo "      → xcode-select --install" ;;
    mac:python) echo "      → brew install python" ;;
    mac:php)    echo "      → brew install php" ;;
    *:php)      echo "      → apt なら: sudo apt install php-cli php-xml php-mbstring" ;;
    *)          echo "      → パッケージマネージャで $1 を入れる" ;;
  esac
}

echo "php-upgrade 環境チェック（$PLATFORM）"
echo

# --- git ---
if command -v git >/dev/null 2>&1; then ok "git: $(git --version)"
else ng "git が見つからない（作業前の状態を記録するのに必要）"; hint_install git; fi

# --- Python ---
if [ ${#PY[@]} -gt 0 ]; then ok "Python: ${PY[*]} ($("${PY[@]}" -c 'import sys; print(sys.version.split()[0])'))"
else ng "Python 3.9 以上が見つからない"; hint_install python; fi

# --- PHP（phpcs を動かすため。点検対象のバージョンと一致している必要はない）---
if command -v "$PHP_BIN" >/dev/null 2>&1 || [ -x "$PHP_BIN" ]; then
  PV="$("$PHP_BIN" -r 'echo PHP_VERSION;' 2>/dev/null)"
  if "$PHP_BIN" -r 'exit(version_compare(PHP_VERSION, "7.4", ">=") ? 0 : 1);' 2>/dev/null; then
    ok "PHP: $PV（$PHP_BIN）"
  else
    ng "PHP $PV は古い。点検ツールには 7.4 以上が必要"; hint_install php
  fi
  MISSING="$("${PHPX[@]}" -r 'foreach (["tokenizer","xmlwriter","simplexml","openssl","phar"] as $e) if (!extension_loaded($e)) echo $e," ";' 2>/dev/null)"
  if [ -n "$MISSING" ]; then
    ng "PHP の拡張が足りない: $MISSING"
    [ "$PLATFORM" = "win" ] && echo "      → PHP のフォルダの ext\\ に php_<名前>.dll があるか確認。無ければ PHP を入れ直す（winget install PHP.PHP.8.4）"
  else
    ok "PHP の拡張（tokenizer / xmlwriter / simplexml / openssl / phar）"
  fi
else
  ng "PHP が見つからない（点検ツール phpcs を動かすのに必要）"; hint_install php
  echo "      ※ 別の場所の PHP を使うなら PHP_BIN=/path/to/php を指定"
fi

# --- 点検ツール ---
if [ -f "$TOOLS_DIR/vendor/squizlabs/php_codesniffer/bin/phpcs" ]; then
  ok "点検ツール: $TOOLS_DIR"
else
  warn "点検ツールが未導入 → run.sh setup で入れる（初回のみ。インターネット接続が必要）"
fi

# --- 構文チェック用の PHP（任意）---
if [ -n "${PHP_LINT_BIN:-}" ]; then
  ok "構文チェック用の PHP: $PHP_LINT_BIN（$("$PHP_LINT_BIN" -r 'echo PHP_VERSION;' 2>/dev/null)）"
else
  warn "構文チェック（php -l）は、移行先と同じ版の PHP があるときだけ行う。PHP_LINT_BIN で指定できる（任意）"
fi

# --- WordPress.org API ---
if "${PY[@]:-false}" -c 'import urllib.request,sys; urllib.request.urlopen("https://api.wordpress.org/core/version-check/1.7/", timeout=10); sys.exit(0)' >/dev/null 2>&1; then
  ok "api.wordpress.org に接続できる（プラグインの最新版の確認に使う）"
else
  warn "api.wordpress.org に接続できない。プラグインの最新版が分からないため、すべて点検対象になる"
fi

echo
if [ "$NG" -ne 0 ]; then
  echo "足りないものがあります。上の → の手順で入れてから、もう一度 run.sh preflight を実行してください。"
  exit 1
fi
echo "OK。点検ツールが未導入なら run.sh setup を実行してください。"
