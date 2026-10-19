#!/usr/bin/env bash
#
# check.sh - 実装HTMLをChromeでレンダリングし、カンプの仕様JSONと突き合わせる
#
#   ./check.sh <index.html> <comp.spec.json> [幅(既定1440)] [--no-anchor] [--threshold 0.5]
#
# パスはカレントディレクトリ基準（絶対パスでもよい）。
# --threshold で「ズレの大きい順」に出す基準（既定4px）を変えられる。仕上げは 0.5 にして残りを全部見る。
#
# 出力: ズレの一覧（Δy/Δx）、横アンカーの判定、実装のフルページPNG（HTMLの隣に .check.png）
#
# アンカー判定のために、指定幅ともう一段広い幅の2回レンダリングする。
# カンプ幅だけでは右端基準と中央基準が同じ座標になり区別できないため。--no-anchor で省略可。
#
# 依存はすべて同じ scripts/ 内で完結する。初回のみ `npm install` が必要。
# Chrome / Edge の場所は環境変数 CHROME_PATH で上書きできる。
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_env.sh
. "$HERE/_env.sh"
need_py

ANCHOR="true"
THRESHOLD=()
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --no-anchor) ANCHOR="false"; shift ;;
    --threshold) THRESHOLD=(--threshold "${2:?--threshold には数値が必要です}"); shift 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
set -- "${ARGS[@]}"

HTML="${1:?実装HTMLのパスを指定してください}"
SPEC="${2:?カンプの spec.json を指定してください}"
WIDTH="${3:-1440}"

[ -f "$HTML" ] || { echo "HTMLが見つかりません: $HTML" >&2; exit 1; }
[ -f "$SPEC" ] || { echo "仕様JSONが見つかりません: $SPEC" >&2; exit 1; }
[ -d "$HERE/node_modules/puppeteer-core" ] || {
  echo "puppeteer-core が未インストールです。次を実行してください:" >&2
  echo "  cd \"$HERE\" && npm install" >&2
  exit 1
}

HTML_ABS="$(cd "$(dirname "$HTML")" && pwd)/$(basename "$HTML")"
OUT="${HTML_ABS%.html}.check.json"

# file:// の組み立ては web2spec.js 側で行う（Windows の C:/… を正しく URL にするため）
( cd "$HERE" && node web2spec.js "$(to_native "$HTML_ABS")" "$WIDTH" "$(to_native "$OUT")" >/dev/null )

"${PY[@]}" "$(to_native "$HERE/compare.py")" "$(to_native "$SPEC")" "$(to_native "$OUT")" ${THRESHOLD[@]+"${THRESHOLD[@]}"}

if [ "$ANCHOR" = "true" ] && [ -f "$HERE/anchors.py" ]; then
  WIDE=$((WIDTH + 300))
  OUT2="${HTML_ABS%.html}.check-wide.json"
  ( cd "$HERE" && node web2spec.js "$(to_native "$HTML_ABS")" "$WIDE" "$(to_native "$OUT2")" >/dev/null )
  rm -f "${OUT2%.json}.png"
  echo
  "${PY[@]}" "$(to_native "$HERE/anchors.py")" "$(to_native "$OUT")" "$(to_native "$OUT2")" "$(to_native "$SPEC")" || true
fi

echo
echo "実装のスクリーンショット: ${OUT%.json}.png"
