# 生成图片插入飞书文档

用户要求将 mify-image-gen 生成的图片插入飞书文档时，按本指南操作。

## 判断插入方式

`generate_image.py` 输出 JSON 包含 `url` 和 `local_path` 两个字段。根据 provider 不同，可用字段不同：

| Provider | `url` 字段 | `local_path` 字段 | 插入方式 |
|----------|-----------|-------------------|---------|
| volcengine (Doubao 系列) | HTTP URL | 有 | 用 URL 直接插入 |
| tongyi (qwen 系列) | HTTP URL | 有 | 用 URL 直接插入 |
| vertex_ai (Gemini 系列) | 无 | 有（base64 已存为文件） | 用本地文件上传 |

## 单张图片插入

**有 URL 时（volcengine / tongyi）：**

```bash
feishu docx update <doc_url> --mode append -c '<image url="IMAGE_URL" align="center"/>'
```

**无 URL 时（Gemini）：**

```bash
feishu docx upload-image <doc_token> --file <local_path>
```

若需插入到指定位置而非末尾：

```bash
feishu docx upload-image <doc_token> --file <local_path> --parent <block_id>
```

## 多图并排插入（表格布局）

多张图片需要并排对比时，唯一可行方案是「Markdown 表格 + upload-image --parent」四步法。`<lark-table>` 和 `<grid>` 内嵌图片均会导致结构坍塌，不可用。

**Step 1** — 创建表格结构（表头放标签，数据行用 `.` 占位）：

```bash
feishu docx update <doc_token> --mode append -c '
| 标签A | 标签B | 标签C |
|-------|-------|-------|
| . | . | . |
'
```

**Step 2** — 获取数据行单元格 block_id：

```bash
feishu docx blocks <doc_token>
# 找 block_type=31 (table) → table.cells 按行主序排列
# cells[0..N-1] = 表头行, cells[N..2N-1] = 数据行 (N=列数)
```

**Step 3** — 上传图片到单元格：

```bash
# URL 图片
feishu docx upload-image <doc_token> --url "IMAGE_URL" --parent <cell_block_id>

# 本地文件
feishu docx upload-image <doc_token> --file <local_path> --parent <cell_block_id>
```

**Step 4** — 删除占位文本（cell 的 children 中 block_type=2 的块）：

```bash
feishu docx delete-block <doc_token> <placeholder_text_block_id>
```

每表建议不超过 3 列。超过的部分分成多个表格（如 6 张图 → 2 个 3 列表格）。

## 注意事项

- `<image token="xxx"/>` 仅用于读取，写入时图片不显示 — 必须用 URL 或 upload-image
- `![](file:///...)` 本地路径不会被 feishu CLI 上传 — 用 `upload-image --file` 代替
- 单次写入大量图片可能报 "too many Page operations" — 分批写入，每批 10-15 张
- 图片单张不超过 10MB，表格内图片会自动缩放适配列宽
- block_type 速查：31=table, 32=table_cell, 2=text, 27=image
