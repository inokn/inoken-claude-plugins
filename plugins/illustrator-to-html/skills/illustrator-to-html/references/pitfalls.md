# 実装時に踏んだ落とし穴

実際に .ai → HTML を一本通したときに出たズレと原因。検証ループで Δy/Δx が出たら、まずここを疑う。

## 縦に累積するズレ（Δy）

| 症状 | 原因 | 対処 |
|---|---|---|
| リストの列が40px右にずれる | `ol` のブラウザ既定 `padding-left: 40px` | リセットに `ol` を含める。`ul, ol, dl, dd { margin:0; padding:0 }` |
| 帯・セクションが数十px高い | パディングを目分量で置いている | カンプの矩形の高さを実測し、`見出しベースライン − 帯上端` から逆算する |
| 行の間隔だけ合わない | `line-height` の既定値 | カンプの `leading` をそのまま `line-height` に入れる（px指定） |
| カード間の余白が0になる | `gap` を付けた要素の子が1つしかない（`.inner` でラップしている） | grid/flex は実際に並ぶ要素の親に付ける |

**ズレは上から順に潰す。** 下流のズレは上流の累積なので、一番上のセクションから合わせる。

## 横のズレ（Δx）

| 症状 | 原因 | 対処 |
|---|---|---|
| 和文が最大30pxほど短い | `font-feature-settings: "palt"` | カンプ（Illustrator）は詰めていない。合わせるなら外す |
| 特定の文字列だけ一定量ずれる | カンプにアイコンフォントが含まれていない | 元デザインのアイコン分の余白。実装側の誤りではないので**直さない**。報告する |
| 見出しだけ位置が違う | セクション内のインデント | カンプの x を content 左端と比較する（例: 本文カラム180に対し見出し204 = 24pxインデント） |
| 字幅そのものが違う | フォントが解決できずフォールバックしている | PostScript名から和文名を先頭に置く（下表） |

### PostScript名 → CSSフォントスタック

カンプの `tokens.fonts` に出る名前（PostScript名）をそのまま `font-family` に書いても当たらない。
**同じ游ゴシックでも、Mac で作ったカンプは `YuGo-*`、Windows で作ったカンプは `YuGothic-*` になる。**
公開するサイトは Mac / iPhone / Windows の全部で見られるので、どちらのカンプでも両方の名前を並べる。

| カンプの表記 | CSS |
|---|---|
| `YuGo-Medium` / `YuGo-Bold`（Mac） | `"游ゴシック体", YuGothic, "Yu Gothic", "Hiragino Sans", sans-serif` |
| `YuGothic-Regular` / `-Medium` / `-Bold`（Windows） | `"Yu Gothic Medium", "游ゴシック Medium", YuGothic, "游ゴシック体", "Hiragino Sans", sans-serif`（Bold は同じスタックに `font-weight:700`） |
| `YuMin-Medium` / `YuMin-Demibold`（Mac） | `"游明朝体", YuMincho, "Yu Mincho", "Hiragino Mincho ProN", serif` |
| `YuMincho-Regular` / `-Demibold`（Windows） | `"Yu Mincho", "游明朝", YuMincho, "游明朝体", "Hiragino Mincho ProN", serif` |
| `Meiryo` / `Meiryo-Bold`（Windows） | `Meiryo, "メイリオ", "Hiragino Sans", sans-serif`（Mac にメイリオは無いので字幅は合わない。報告する） |
| `BIZ-UDPGothic` 系（Windows） | `"BIZ UDPGothic", "Hiragino Sans", sans-serif` |
| `HiraginoSans-W3`〜`W6` | `"Hiragino Sans", "Hiragino Kaku Gothic ProN", sans-serif` |
| `HiraMinProN-W3` / `W6` | `"Hiragino Mincho ProN", serif` |
| `NotoSansJP-*` / `SourceHanSans-*`（Adobe Fonts 等） | Webフォント（Google Fonts の Noto Sans JP 等）を読み込む。環境依存が無くなるので一番確実 |

**Windows の游ゴシックの罠:** `font-family: "Yu Gothic"` だけ書くと Windows では細い Regular が当たり、
カンプ（Medium）より線が細く見える。Medium は `"Yu Gothic Medium"` という別ファミリー名なので先頭に置く。

和文名を先頭に置かないと家族名が一致せず別フォントに落ちて字幅が変わる。
**字幅が合っているかは `compare.py` の Δx で分かる**（フォントが正しければ字幅は完全一致する）。

## 重なり順

- **カンプの重なり順は信用しすぎない。** 変換はDOM順で積んでいるだけなので、CSSの `z-index` による前後関係は保持されない。
- 写真と帯が重なっている箇所は、カンプのPNGを実際に見て前後を判断する。判断がついたら報告に書く。
- プレースホルダに `position: relative` を付けると、後続の静的要素より前面に来て文字が隠れる。重ねる側に `position: relative; z-index: 1` を明示する。

## メディアクエリ

- 基底で `position: absolute; top: …` を使った要素をメディアクエリで `position: relative` に変えると、**基底の `top` が復活して要素が下にずれる**。`top: auto; left: auto` も併せて打ち消す。
- 基底の `height` をインライン `style` で書くとメディアクエリで上書きできない。クラスにする。
- `line-height: 1` の見出しは1行前提。折り返す幅では `1.4`〜`1.5` に戻す。

## カンプ側の読み方

- テキストの `box` は**字形の実インク範囲**。配置の基準は `baseline`（行頭ベースライン）。
- `kind: "POINTTEXT"` は1行、`"AREATEXT"` は折り返しのある本文。後者は `box.w` が本文の折り返し幅。
- `tokens.colors` は使用頻度順。上位数色がそのままCSSカスタムプロパティになる。`roles` で用途（fill/text/stroke）が分かる。
- グラデーションの角度はカンプに含まれない（Illustrator DOMの制約）。PNGを見て向きを決める。
- 角丸 `cornerRadius` はパス形状からの推定値。

## 埋め込み画像をHTMLに使う

`.ai` に埋め込まれた画像はHTMLで使える。**画質の心配はほぼ要らない**（実測値は下記）。

### まず元ファイルを探す

**`.ai` は埋め込んだ画像の元ファイルのパスを覚えている。** `ai2spec.sh` で読むと
Raster アイテムの `file` に出る。手元にあればそれを使うのが最善で、
元の形式・元のバイトのまま（JPEGはJPEGのまま軽い）。

```bash
"$SK/scripts/ai2spec.sh" design.ai -o ./spec --no-png
python3 "$SK/scripts/assets.py" ./spec/design.spec.json -o ./assets    # Windows は py -3
```

同じ画像を複数箇所で使っていても1回だけコピーされる。

### 元ファイルが無いときだけ .ai から取り出す

`.ai` は PDF互換で保存されていれば PDF として中身を読める。

```bash
cp design.ai design.pdf
pdfimages -list design.pdf                    # 何が入っているか
pdfimages -all  design.pdf ./raw/img          # 取り出す
python3 assets.py spec.json -o ./assets --extracted ./raw
```

抽出物には名前が無いので、`assets.py` が出す箱の寸法と見比べて手で割り当てる。

Windows には `pdfimages` が標準で入っていない。元ファイルが見つからないときは、
Illustrator で該当画像を選んで「書き出し > スクリーン用に書き出し」で書き出してもらう方が早い。

### 画質（実測）

| 元 | 埋め込み → 抽出の結果 |
|---|---|
| PNG | **1ピクセルも違わない完全一致**。原寸配置・縮小配置とも |
| JPEG | PSNR **53.6dB**。差は全画素の28%に±1階調のみ、8x8ブロック境界に偏りなし＝**再圧縮ではなくデコーダの丸め** |

- **縮小して配置してもダウンサンプルされない。** 800×600 を 200×150pt に置いても
  埋め込まれるのは 800×600 のまま（実効 288ppi になるだけ）。Retina 用の素材として使える
- 同じ画像を2箇所で使っても埋め込みは1つ

### ただしファイルは膨らむ

JPEG は**デコードされて可逆で格納される**ので、`.ai` の中では元より大きくなる。
抽出すると PNG で出てくるため、Web に載せる前に再エンコードが要る。

```
元JPEG(q95)         91,594 bytes
.aiから抽出したPNG   435,151 bytes    ← 4.7倍
再エンコード q90      62,234 bytes    元JPEGとのPSNR 51.7dB
再エンコード q85      40,751 bytes    元JPEGとのPSNR 50.9dB
```

再エンコードしても元JPEGとの差は50dB超（人間の目では区別不能）。
**世代劣化を気にするより、元ファイルを探す方が先。**

## 出力するHTMLの方針

カンプは絶対座標の集合だが、**絶対配置で再現しない**。通常フローで組み、
カンプ幅で数値が一致するように余白を決める。理由は、絶対配置だとレスポンシブにできず、
文言が変わった瞬間に破綻するため。

- 本文カラム幅は、繰り返し要素の x と w から割り出す（例: x=180 で w=1080 なら `max-width:1080px` 中央寄せ）
- 全幅の帯は矩形の w がアートボード幅と一致しているもの
- 繰り返しの矩形（カード・ボタン）は grid/flex にする。`gap` はカンプの x の差から算出
