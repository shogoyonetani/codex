# HTML → ACF JSON / PHP 生成ツール

HTML内に `data-acf-*` 属性を付けると、

- ACF Local JSON (`acf-group.json`)
- ACF呼び出しコード入りPHP (`template-generated.php`)

を自動生成するCLIです。

## 使い方

```bash
python3 html_to_acf_tool.py sample.html \
  --group-title "Landing Fields" \
  --group-key "group_landing_fields" \
  --post-type "page"
```

## マーカー仕様

### 通常フィールド

`data-acf-field` を持つ要素がフィールドになります。

```html
<h2 data-acf-field="hero_title">見出し</h2>
<p data-acf-field="hero_text" data-acf-type="textarea">説明文</p>
<img data-acf-field="hero_image" src="/dummy.jpg" alt="">
<a data-acf-field="cta_url" href="#">詳細へ</a>
```

- `data-acf-type` 未指定時はタグから推定します。
  - `img` → `image`
  - `a` → `url`
  - 見出しや `p` など → `text`

### リピーター

`data-acf-repeater` を持つ要素を `repeater` として生成します。
中の `data-acf-field` は `sub_fields` になります。

```html
<ul data-acf-repeater="features">
  <li data-acf-field="title">高速</li>
  <li data-acf-field="description" data-acf-type="textarea">説明</li>
</ul>
```

## 出力

- `acf-group.json`: ACFのフィールドグループJSON
- `template-generated.php`: `get_field()/the_field()/have_rows()` で変換済みHTML

画像フィールドがある場合、アクセシビリティ向上のため `*_alt` テキストフィールドを自動追加します。
