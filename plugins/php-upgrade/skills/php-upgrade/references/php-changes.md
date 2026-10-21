# PHP 7.0 → 8.5 で壊れる書き方と直し方

修正フェーズ（SKILL.md フェーズ5）で参照する。`scan.json` の指摘を直すときは、まずここで直し方の型を確かめる。
細かい仕様は php.net の移行ガイド（`https://www.php.net/manual/ja/migration80.php` など、`migration70`〜`migration85`）が正。

**直すときの原則**

- 今の版でも移行先でも動く書き方にする（戻し方＝「PHPを元に戻す」が使えるように）。PHP 7.x を残すサイトでも動く範囲で書く
- 1箇所ずつ最小限に直す。ついでのリファクタリングや整形はしない（差分が読めなくなる）
- 直した箇所は `run.sh scan` で消えたことを確かめる

---

## 1. 点検で見つかるもの（PHPCompatibility が指摘する）

### 7.0 で削除

| 見つかったもの | 直し方 |
|---|---|
| `mysql_*()`（mysql_connect / mysql_query / mysql_fetch_* など） | `mysqli_*()` に置き換える。下の「mysql → mysqli」を参照 |
| `ereg()` / `eregi()` | `preg_match('/…/')` / `preg_match('/…/i')`。区切り文字 `/` が正規表現の中にあれば `#…#` などに替える |
| `ereg_replace()` / `eregi_replace()` | `preg_replace('/…/', …)` / `'/…/i'` |
| `split()` / `spliti()` | 固定文字なら `explode()`、正規表現なら `preg_split('/…/')` |
| `preg_replace()` の `/e` 修飾子 | `preg_replace_callback()` に書き換え |
| `$HTTP_RAW_POST_DATA` | `file_get_contents('php://input')` |
| `=& new` | `= new` |
| `<% %>` / `<script language="php">` | `<?php ?>` |
| `mssql_*()` | `sqlsrv_*()` か PDO（拡張の入れ替えが要る。人に相談） |
| `call_user_method()` | `call_user_func([$obj, 'method'])` |

### 7.2 で削除（mcrypt）

| 見つかったもの | 直し方 |
|---|---|
| `mcrypt_*()` | `openssl_encrypt()` / `openssl_decrypt()`。**既存の暗号化データが読めなくなる**ので、勝手に書き換えず人に相談 |

### 8.0 で削除

| 見つかったもの | 直し方 |
|---|---|
| `each()` | `while (list($k, $v) = each($a))` → `foreach ($a as $k => $v)`。`reset()` と組み合わせている場合も foreach で置き換えられる |
| `create_function('$x', 'return $x*2;')` | `function ($x) { return $x * 2; }` |
| `$str{0}` / `$arr{0}`（波かっこの添字） | `$str[0]` / `$arr[0]` |
| `(real)` | `(float)` |
| `(unset) $x` | `$x = null` |
| `get_magic_quotes_gpc()` / `get_magic_quotes_runtime()` | 常に false なので、`if (get_magic_quotes_gpc()) { … }` のブロックごと削除（中の stripslashes は不要になる） |
| `money_format()` | `number_format($n)`（日本円なら `'¥' . number_format($n)`） |
| `__autoload()` | `spl_autoload_register(function ($class) { … })` |
| クラス名と同じ名前のメソッド（PHP4 形式のコンストラクタ） | `function __construct(…)` に改名。子クラスが `parent::クラス名()` を呼んでいれば `parent::__construct()` に |
| ネストした三項演算子 `a ? b : c ? d : e` | かっこで明示する `(a ? b : c) ? d : e`（意図を確かめる） |
| `$php_errormsg` / `track_errors` | `error_get_last()['message']` |
| 必須の引数より前に任意の引数（`function f($a = 1, $b)`） | 非推奨。`$a` のデフォルト値を外すか、引数の順を見直す（呼び出し側も確認） |

### 8.1 で非推奨

| 見つかったもの | 直し方 |
|---|---|
| `strftime()` / `gmstrftime()` | `date()`。`strftime('%Y年%m月%d日')` → `date('Y年m月d日')`。曜日の日本語は `['日','月','火','水','木','金','土'][date('w')]` |
| `FILTER_SANITIZE_STRING` | 出力時の `htmlspecialchars()` に置き換える（入力時に削るのをやめる）。意味が変わるので処理の流れを確認 |
| `date_sunrise()` / `date_sunset()` | `date_sun_info()` |
| `mhash*()` | `hash()` |

### 8.2 で非推奨

| 見つかったもの | 直し方 |
|---|---|
| `"${var}"` / `"${expr}"` | `"{$var}"` |
| `utf8_encode($s)` / `utf8_decode($s)` | `mb_convert_encoding($s, 'UTF-8', 'ISO-8859-1')` / 逆向き。**日本語のサイトでは誤用が多い**（Shift_JIS を UTF-8 にしたつもりのコードは、もともと壊れている）。用途を確かめて `mb_convert_encoding($s, 'UTF-8', 'SJIS-win')` が正しいことが多い |
| `mb_convert_encoding($s, 'HTML-ENTITIES', 'UTF-8')` | `mb_encode_numericentity($s, [0x80, 0x10FFFF, 0, 0x1FFFFF], 'UTF-8')` |
| `"self::method"` / `"parent::method"` 形式のコールバック | `[self::class, 'method']` / `[static::class, 'method']` |

### 8.3 で非推奨

| 見つかったもの | 直し方 |
|---|---|
| 引数なしの `get_class()` / `get_parent_class()` | `self::class` / `get_parent_class($this)` |
| `assert_options()` | ini 設定（`zend.assertions`）へ |

### 8.4 で非推奨・削除

| 見つかったもの | 直し方 |
|---|---|
| 暗黙の nullable 型 `function f(string $s = null)` | `function f(?string $s = null)`（7.1 以上で動く） |
| `trigger_error(…, E_USER_ERROR)` | 例外を投げるか `exit` |
| `E_STRICT` 定数 | 削除（`error_reporting(E_ALL & ~E_STRICT)` → `error_reporting(E_ALL)`） |
| `fputcsv()` / `fgetcsv()` / `str_getcsv()` の `$escape` を省略 | 引数で明示する（従来どおりなら `'\\'`、RFC どおりなら `''`） |
| `mysqli_ping()` / `mysqli_refresh()` / `mysqli_kill()` | 削除するか、接続し直す処理に |
| `imap_*()` / `oci_*()` / `pspell_*()` | **拡張が本体から外れた**。サーバーで PECL 版を入れられるか人に確認（コード側では直せない） |

### 8.5 で非推奨（主なもの。最新は php.net の migration85 を確認）

| 見つかったもの | 直し方 |
|---|---|
| バッククォート `` `ls` `` | `shell_exec('ls')` |
| `(boolean)` / `(integer)` / `(double)` / `(binary)` | `(bool)` / `(int)` / `(float)` / `(string)` |
| `case 1;`（コロンでなくセミコロン） | `case 1:` |
| 配列の添字に null（`$a[null]`） | `$a['']` |
| `curl_close()` / `finfo_close()` / `xml_parser_free()` / `imagedestroy()` | 何もしない関数になったので削除してよい（8.0 未満でも動かす必要があるなら残す） |

---

## 2. mysql → mysqli（いちばん多い）

```php
// 前
$link = mysql_connect($host, $user, $pass);
mysql_select_db($db, $link);
mysql_query("SET NAMES utf8", $link);
$r = mysql_query("SELECT * FROM t WHERE id = " . mysql_real_escape_string($id));
while ($row = mysql_fetch_assoc($r)) { … }
$n = mysql_num_rows($r);
$one = mysql_result($r, 0, 'name');
mysql_close($link);

// 後
$link = mysqli_connect($host, $user, $pass, $db);
mysqli_set_charset($link, 'utf8');            // SET NAMES の代わり（文字化け防止のため元の文字コードに合わせる）
$r = mysqli_query($link, "SELECT * FROM t WHERE id = " . mysqli_real_escape_string($link, $id));
while ($row = mysqli_fetch_assoc($r)) { … }
$n = mysqli_num_rows($r);
mysqli_data_seek($r, 0); $one = mysqli_fetch_assoc($r)['name'];
mysqli_close($link);
```

- **引数の順が逆**: `mysql_query($sql, $link)` → `mysqli_query($link, $sql)`。`mysqli_real_escape_string` も接続が先
- **接続を省略できない**: mysql_* は直前の接続を暗黙に使えたが、mysqli は毎回 `$link` が要る。関数の中で使っているなら `global $link;` を足すか、引数で渡す
- `mysql_insert_id()` → `mysqli_insert_id($link)`、`mysql_error()` → `mysqli_error($link)`、`mysql_affected_rows()` → `mysqli_affected_rows($link)`
- `mysql_fetch_array($r, MYSQL_ASSOC)` → `mysqli_fetch_array($r, MYSQLI_ASSOC)`（定数名も変わる）
- 呼び出し箇所が多いなら、共通の接続ファイル（`db.php` など）を直してから、各ファイルを順に置き換える
- **SQL インジェクション対策（プリペアドステートメント化）は、この移行ではやらない**。範囲が広がって検証が終わらなくなる。気づいた危ない箇所は `report.md` に追記して、別の作業として人に提案する

---

## 3. 点検では見つからない落とし穴（実行時にしか分からない）

PHPCompatibility はコードを読むだけなので、次は見つけられない。**自作コードを直すときは、次の検索で該当しそうな箇所も確認する**（Grep で自作の範囲だけを対象に）。

| 何が起きるか | いつから | 探し方 | 直し方 |
|---|---|---|---|
| **mysqli が失敗時に例外を投げるようになり、画面が真っ白になる** | 8.1 | `mysqli_connect` / `new mysqli` | 従来どおりの動きにするなら、接続の直前に `mysqli_report(MYSQLI_REPORT_OFF);` を1行足す（7.x でも無害） |
| 宣言していないプロパティへの代入が非推奨（ログが埋まる） | 8.2 | `class ` を含むファイルで `$this->xxx =` | クラスにプロパティを宣言する（`public $xxx;`）。数が多ければクラスの前に `#[\AllowDynamicProperties]` |
| 組み込み関数に null を渡すと非推奨（`strlen(null)` など） | 8.1 | `$_GET` / `$_POST` / DB の値をそのまま `trim` / `strlen` / `htmlspecialchars` / `str_replace` に渡している所 | `trim($_POST['x'] ?? '')`、`htmlspecialchars((string)$v)` |
| 配列でない値の `count()` が TypeError | 8.0 | `count(` | `is_countable($x) ? count($x) : 0`、または値を配列で初期化する |
| 数値と文字列の比較の結果が変わる（`0 == 'abc'` が true → false） | 8.0 | `== 0` / `== '0'` / `switch` で数値と文字列が混ざる所 | 意図を確かめて `===` か明示的な型変換に |
| 未定義の定数が Error になる（以前は文字列として動いた） | 8.0 | `$arr[key]`（クォートなしのキー） | `$arr['key']` |
| 引数が足りない呼び出しが Error になる | 7.1 | 自作関数の定義と呼び出し | 呼び出し側を直すか、引数にデフォルト値を付ける |
| GD / curl が resource でなくオブジェクトになり、`is_resource()` が false | 8.0 | `is_resource(` | `$img !== false` / `$ch instanceof CurlHandle` などに |
| ArrayAccess / Iterator / Countable / JsonSerializable を実装したクラスで、戻り値の型がないと非推奨 | 8.1 | `implements ArrayAccess` など | メソッドの前に `#[\ReturnTypeWillChange]`（7.x では無視される） |
| `.htaccess` の `php_flag` / `php_value` でサイト全体が 500 エラー | — | `inventory.json` の `htaccess_php` | 削除された設定（magic_quotes_gpc など）は行ごと消す。PHP が php-fpm / CGI で動くサーバーでは `php_flag` 自体が使えないので、必要な設定は `.user.ini` に移す（`php_value mbstring.internal_encoding SJIS` → `.user.ini` に `default_charset = "Shift_JIS"` など、意味を確かめて） |
| `htmlspecialchars()` の既定がシングルクォートも変換するように | 8.1 | — | 通常は安全側の変化なので直さない |
| 未定義の変数・添字の Notice が Warning に格上げ | 8.0 | — | 表示設定によっては画面に出る。検証環境のログで確認 |

---

## 4. 文字コード

`inventory.json` の `encodings` に載っているファイル（Shift_JIS / EUC-JP）は、**必ず次の手順で直す**。そのまま編集すると、日本語が壊れてサイトが文字化けする。

```bash
"$SK/scripts/run.sh" recode open path/to/file.php    # 元の文字コードを記録して UTF-8 に
# … Read / Edit で修正 …
"$SK/scripts/run.sh" recode close path/to/file.php   # 元の文字コードに戻す
```

`close` で戻せない文字（Shift_JIS にない文字）を入れてしまったら止まるので、その文字を直してから `close` し直す。
`finalize` は `close` し忘れがあると止まる。
