#!/usr/bin/env bash
#
# setup-tools.sh - 点検ツール（phpcs + PHPCompatibility）を入れる（run.sh setup から呼ばれる）
#
# 入れる先は $TOOLS_DIR（既定 ~/.cache/inoken-php-upgrade）。プラグイン本体のフォルダは
# 自動更新で置き換わるので、そこには置かない。composer が無ければ composer.phar を取ってくる。
# 何度実行してもよい（2回目以降は更新になる）。
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_env.sh
. "$HERE/_env.sh"

command -v "$PHP_BIN" >/dev/null 2>&1 || [ -x "$PHP_BIN" ] || { echo "PHP が見つかりません。run.sh preflight を先に実行してください。" >&2; exit 1; }

mkdir -p "$TOOLS_DIR"
cp "$HERE/composer.json" "$TOOLS_DIR/composer.json"
cd "$TOOLS_DIR"

COMPOSER=()
if command -v composer >/dev/null 2>&1; then
  COMPOSER=(composer)
else
  if [ ! -f composer.phar ]; then
    echo "composer.phar を取得しています..."
    "${PHPX[@]}" -r '
      $url = "https://getcomposer.org/download/latest-stable/composer.phar";
      $bin = file_get_contents($url);
      $sum = trim(explode(" ", file_get_contents($url . ".sha256sum"))[0]);
      if ($bin === false || hash("sha256", $bin) !== $sum) { fwrite(STDERR, "composer.phar の取得または検証に失敗しました\n"); exit(1); }
      file_put_contents("composer.phar", $bin);'
  fi
  COMPOSER=("${PHPX[@]}" composer.phar)
fi

# zip 拡張も unzip / 7z も無いと配布用アーカイブを展開できないので、git から取ってくる
OPTS=(--no-interaction --no-progress)
if ! "${PHPX[@]}" -r 'exit(extension_loaded("zip") ? 0 : 1);' 2>/dev/null \
   && ! command -v unzip >/dev/null 2>&1 && ! command -v 7z >/dev/null 2>&1; then
  OPTS+=(--prefer-source)
fi

if [ -f composer.lock ]; then
  "${COMPOSER[@]}" update "${OPTS[@]}"
else
  "${COMPOSER[@]}" install "${OPTS[@]}"
fi

echo
"$PHP_BIN" vendor/squizlabs/php_codesniffer/bin/phpcs -i
echo "点検ツールを入れました: $TOOLS_DIR"
