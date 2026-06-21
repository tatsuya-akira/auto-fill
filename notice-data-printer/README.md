# Notice Data Printer

Tool này làm bước **print/preview data trước** khi đưa qua Chrome extension autofill.
Nó không fill form, không submit form. Bản này dùng `tldextract` để parse domain chính xác hơn, thay vì hard-code các suffix như `co.za`, `com.au`, `com.br`.

## Cài dependency

```bash
pip install -r requirements.txt
```

Tool dùng `tldextract.TLDExtract(suffix_list_urls=())`, nên không cần gọi network lúc chạy. Nó dùng Public Suffix List snapshot đi kèm package.

## Chạy GUI

Mac/Linux:

```bash
python3 gui_notice_data.py
```

Windows:

```bat
python gui_notice_data.py
```

Hoặc double-click `run_gui.bat` trên Windows / chạy `./run_gui.sh` trên Mac/Linux.

### GUI làm gì?

1. Chọn notice template.
2. Paste URL hoặc load `urls.txt`, mỗi dòng một URL.
3. Paste claim/evidence hoặc load `claims.txt`, mỗi dòng một claim.
4. Điền optional fields như `User / seller override`, `Name on label`, `Domain override`. Nếu `User / seller override` để trống, tool tự dùng hostname từ URL đầu tiên.
5. Preview tự render realtime, không cần bấm Render. Các tab chính:
   - `Notice text (built-in)`: preview bản cứng/built-in, không áp dụng user placeholder map.
   - `Full JSON payload`: JSON cuối cùng, có `builtin_notice_text`, kết quả từ `Placeholder map`, và kết quả từ `Raw rules JSON`.
   - `Fill values only`
   - `Placeholder map`: module riêng để add/edit rule bằng UI và xem kết quả sau khi áp dụng rule ở khung dưới cùng.
   - `Raw rules JSON`: module riêng để gõ JSON trực tiếp, có khung kết quả riêng ở dưới và render realtime. Nó không sync qua lại với `Placeholder map`.
   - `Image check`
6. Bấm **Save JSON**, **Save mapped TXT**, **Copy mapped**, **Copy built-in**, hoặc **Copy JSON**.

GUI vẫn giữ logic nhiều URL:

- `urls`: URL gốc bạn nhập hoặc load từ file.
- `action_urls`: URL dùng để thay vào `[LIST URL FOR SPECIFIC ACTION]`; nếu có nhiều URL thì tự thêm homepage/root lên đầu.
- `action_url_list`: bản nhiều dòng để render vào notice.

## Placeholder map vs Raw rules JSON

Hai tab này là **hai module riêng**:

- `Placeholder map`: dùng nút Add/Edit/Delete để tạo rule bằng UI. Kết quả nằm ở khung `Notice result after applying placeholder map` trong cùng tab.
- `Raw rules JSON`: gõ JSON trực tiếp, ví dụ:

```json
{
  "[DOMAIN]": "haha.com",
  "DOMAIN": "haha.com",
  "[USER]": "haha"
}
```

Kết quả của Raw rules JSON nằm ở khung `Notice result after applying Raw rules JSON` ngay dưới ô JSON. Nếu JSON hợp lệ, preview cập nhật realtime. Nếu JSON lỗi cú pháp, tool giữ kết quả hợp lệ trước đó trong khi bạn đang sửa.

Cả hai module đều có priority giống nhau trong preview riêng của nó:

```txt
1. Rule có value không rỗng
2. Built-in fallback: [DOMAIN], DOMAIN, [USER], [the seller], [NAME ON PRODUCT LABEL], URL list
3. Nếu vẫn thiếu thì giữ placeholder dạng [] để dễ thấy
```

## Chạy CLI

GUI chỉ là lớp giao diện phía trên. CLI vẫn dùng được như cũ.

## Template hiện có

```bash
python print_notice_data.py --list-templates
```

Các template được lấy từ file bạn đưa:

- `sponsor` - IP rights / Zepbound sponsor-style notice
- `unapproved_retatrutide` - Retatrutide unapproved product notice
- `newtag` - compounded tirzepatide misleading claims notice
- `us_newtag` - US new tag / platform notice with `[USER]`
- `us_label` - US label violation / name on product label notice

## Một URL

```bash
python print_notice_data.py --template unapproved --url https://mounjarosa.co.za
```

## Nhiều URL bằng file TXT

Tạo file TXT, mỗi dòng một URL:

```txt
https://slimvials.com/collections/all-products
https://slimvials.com/products/mounjaro%C2%AE-injectable-pen-copy-copy-copy
https://slimvials.com/products/retatrutide-synedica
https://slimvials.com/products/vls-retatrutide-20-mg-prefilled-pen
```

Có thể dùng dòng trống hoặc comment bắt đầu bằng `#`; tool sẽ bỏ qua.

Chạy:

```bash
python print_notice_data.py \
  --template us_label \
  --urls-file examples/urls.txt \
  --name-on-label slimvials
```

Khi có nhiều URL, tool tạo 2 field khác nhau:

- `urls`: các URL gốc từ file TXT.
- `action_urls`: danh sách dùng để thay vào `[LIST URL FOR SPECIFIC ACTION]`; mặc định tự thêm homepage/root lên đầu.

Ví dụ output:

```json
{
  "urls": [
    "https://slimvials.com/collections/all-products",
    "https://slimvials.com/products/retatrutide-synedica"
  ],
  "action_urls": [
    "https://slimvials.com",
    "https://slimvials.com/collections/all-products",
    "https://slimvials.com/products/retatrutide-synedica"
  ],
  "action_url_list": "https://slimvials.com\nhttps://slimvials.com/collections/all-products\nhttps://slimvials.com/products/retatrutide-synedica"
}
```

Trong notice text, placeholder `[LIST URL FOR SPECIFIC ACTION]` sẽ thành nhiều dòng:

```txt
https://slimvials.com
https://slimvials.com/collections/all-products
https://slimvials.com/products/retatrutide-synedica
```

## Nhiều URL bằng nhiều flag `--url`

```bash
python print_notice_data.py \
  --template us_label \
  --url https://slimvials.com/collections/all-products \
  --url https://slimvials.com/products/retatrutide-synedica \
  --name-on-label slimvials
```

## Print text notice only

```bash
python print_notice_data.py --template unapproved --urls-file examples/retatrutide-urls.txt --format text
```

## Claims / evidence lines

```bash
python print_notice_data.py \
  --template newtag \
  --url https://example.com/post/123 \
  --claim "Same active ingredient as Mounjaro and Zepbound." \
  --claim "Clinically proven weight loss support."
```

Hoặc dùng file TXT:

```bash
python print_notice_data.py \
  --template newtag \
  --url https://example.com/post/123 \
  --claims-file examples/claims.txt
```

## Case JSON input

```bash
python print_notice_data.py --case examples/multi-us-label.json
```

## Save output

```bash
python print_notice_data.py \
  --case examples/single-retatrutide.json \
  --save-json output/case-data.json \
  --save-text output/notice.txt
```

## Domain parsing

Tool tự derive các field sau từ URL đầu tiên:

```json
{
  "hostname": "mounjarosa.co.za",
  "domain": "mounjarosa.co.za",
  "domain_label": "mounjarosa",
  "homepage_url": "https://mounjarosa.co.za",
  "user": "mounjarosa.co.za"
}
```

`user` mặc định lấy `hostname`. Nếu URL là subdomain, ví dụ `https://shop.example.co.za/path`, thì `hostname`/`user` sẽ là `shop.example.co.za`, còn `domain` vẫn là `example.co.za`. Nếu ô `User / seller override` trong GUI để trống thì render tự dùng hostname; nhập tay vào ô đó nếu muốn override.

Ví dụ khác:

```txt
https://shop.slimvials.com/products/x      -> slimvials.com / slimvials
https://a.b.example.com.au/product        -> example.com.au / example
```

Nếu cần override domain thủ công:

```bash
python print_notice_data.py --template unapproved --url https://x.y.example.com.au/path --domain example.com.au
```

## Output chính

```json
{
  "case_data": {},
  "rendered": {
    "subject": "...",
    "notice_text": "..."
  },
  "extension_payload": {
    "fill_values": {
      "domain": "...",
      "url": "...",
      "urls": [],
      "action_urls": [],
      "action_url_list": "...",
      "subject": "...",
      "notice_text": "..."
    },
    "mapping_ready": true
  },
  "unresolved_placeholders": []
}
```

## Placeholder map trên GUI

Tab **Notice text (built-in)** luôn hiển thị bản cứng/built-in của template, chưa áp dụng rule JSON. Sau khi add rule trong tab **Placeholder map** hoặc sửa trực tiếp tab **Raw rules JSON**, kết quả cuối cùng sẽ hiện ở khung dưới cùng tên **Notice result after applying placeholder map**.

Tab **Raw rules JSON** giờ chỉ chứa phần rules, không còn `profile_name` hay `template_match`. Bạn sửa JSON trực tiếp, nếu JSON hợp lệ thì mapped preview tự render realtime. Dạng khuyến nghị:

```json
{
  "[DOMAIN]": "hehe.com",
  "[USER]": "hehe",
  "[the seller]": "hehe",
  "[NAME ON PRODUCT LABEL]": "hehe-label"
}
```

Tool cũng vẫn đọc được dạng list nếu cần:

```json
[
  {"[DOMAIN]": "hehe.com"},
  {"[USER]": "hehe"}
]
```

Và vẫn tương thích với dạng cũ có wrapper `rules`, nhưng GUI sẽ hiển thị/sync lại về raw rules object gọn ở trên.

### Built-in rules vẫn được giữ

Tool vẫn tự xử lý các rule gắn cứng như fallback sau khi JSON rule có giá trị được áp dụng:

```txt
[DOMAIN]                  -> domain chính từ tldextract
DOMAIN                    -> domain chính trong subject/title
[USER]                    -> hostname từ URL đầu tiên nếu ô user/seller để trống
[the seller]              -> hostname từ URL đầu tiên
[NAME ON PRODUCT LABEL]   -> domain_label, ví dụ slimvials.com -> slimvials
[LIST URL FOR SPECIFIC ACTION] -> action_url_list, mỗi URL một dòng
```

User-defined rules trong **Placeholder map** có **độ ưu tiên cao hơn** built-in rules nếu rule đó có giá trị không rỗng. Nếu value rỗng, tool bỏ qua rule đó và dùng built-in fallback. Ví dụ:

```json
{
  "[DOMAIN]": "hehe.com"
}
```

sẽ ép `[DOMAIN]` thành `hehe.com` thay vì domain tự derive.

### UI trong tab Placeholder map

Cách đọc UI mới:

- **Built-in auto values**: xem các giá trị fallback tự derive từ URL/domain, ví dụ `[DOMAIN]`, `[USER]`, `[the seller]`.
- **User rules**: danh sách rule bạn tự thêm; nếu value có dữ liệu thì nó override built-in.
- **Resolved rule preview**: xem rule nào đang thay giá trị gì.
- **Notice result after applying placeholder map**: xem notice cuối cùng sau khi áp dụng rule.

Có các nút:

- **Add rule**: thêm placeholder rule mới.
- **Edit** hoặc double-click rule: sửa rule.
- **Duplicate**: nhân bản rule.
- **Delete**: xóa rule.
- **Move up / Move down**: đổi thứ tự rule.
- **Raw rules JSON** tab: sửa JSON trực tiếp; valid JSON sẽ update rules và render realtime.

Mỗi rule có:

```txt
Placeholder: exact text trong template, ví dụ [DOMAIN]
Value: giá trị thay vào, có thể dùng {{domain}}, {{hostname}}, {{domain_label}}, {{action_url_list}}
```

Ví dụ rule động:

```json
{
  "[NAME ON PRODUCT LABEL]": "{{domain_label}}"
}
```

Có sẵn ví dụ tại:

```txt
placeholder_maps/example-placeholder-map.json
```

### CLI với placeholder map

```bash
python print_notice_data.py \
  --template us_label \
  --url https://mounjarosa.co.za \
  --placeholder-map placeholder_maps/example-placeholder-map.json \
  --format text
```

## Data field dùng cho placeholder map / extension sau này

Trong `extension_payload.fill_values`, rule có thể dùng các field này trong dạng `{{...}}`:

- `domain`
- `hostname`
- `host`
- `seller_hostname`
- `url`
- `urls`
- `action_urls`
- `homepage_url`
- `url_list`
- `action_url_list`
- `subject`
- `notice_text`
- `user`
- `claims_text`
- `name_on_product_label`
- `domain_label`
- `recipient_type`

Ví dụ value trong rule:

```txt
{{hostname}}
{{domain_label}}
{{action_url_list}}
```

## Unicode preview note

This GUI version decodes visible JSON-style Unicode escape sequences such as `\u2019`, `\u2013`, and `\u00ae` before rendering the preview. The Notice tab should display normal punctuation like `’`, `–`, and `®` instead of backslash-u text.
