---
name: mify-image-gen
name_zh: Mify全模型图片生成助手
version: 2.8.0
description: "Use whenever someone asks to 画图/画一张/生成图片/生成插画 or to generate, draw, illustrate, or create images with AI. Covers: text-to-image (描述生成图片, product mockups, concept art, 赛博朋克/水彩/油画风格); image-to-image style transfer (渲染成X风格, 转成白底产品图, 把照片变成梵高画风); batch operations (批量生成多张插画, 批量转换照片风格); and generation settings (修改输出目录, 切换模型, 查看配置, 修改分辨率). Core signal: user wants AI to create new images or apply artistic transformations to existing photos. NOT for: image resize/crop, file format conversion, OCR, matplotlib/charts, or building image upload UI components."
not_for:
  - 不处理图片裁剪、缩放等非AI编辑操作
  - 不支持图片格式转换（如PNG转JPG）
  - 不适用于OCR文字识别
  - 不生成matplotlib图表或数据可视化
  - 不用于构建图片上传UI组件
examples:
  # text2img — 文生图（含中文排版/手账/产品海报/工业爆炸图）
  - 画一张小米SU7的工业爆炸图，零部件悬浮分解，深灰背景配冷白工作室灯光，8K超写实3D渲染
  - 生成一张上海旅游指南手账插画，纯中文排版，融合外滩、东方明珠、豫园、小笼包，暖色水彩与彩铅质感
  - 画一张Chanel CF黑色小羊皮菱格纹手袋的白底产品图，专业棚拍柔光，商业奢侈品电商摄影风格
  # img2img — 图生图（风格迁移 / 超清增强 / 场景改造）
  - 把这张写实肖像转换成卡哇伊贴纸风格，粗黑轮廓线+赛璐璐平涂+白边，严格保持原图构图
  # 多图融合 — multi-image img2img
  - 把第一张图里的人物和第二张图里的手袋自然融合，女性挎着手袋走在巴黎街头，时尚街拍风格
  # 批量生成 — batch（角色一致性多动作 / 主题发散）
  - 基于这张超级赛亚人孙悟空的图，批量生成龟派气功、狂吃大笑、愤怒变身、重伤不屈四个动作
  # 配置类
  - 生成春夏秋冬四季景观各一张，并排插入飞书文档
---

# Mify Image Generation

Generate images via Mify API. Supports text-to-image, image-to-image, and multi-image fusion with DeepSeek Flash prompt optimization. Four providers: volcengine (Doubao-Seedream), tongyi (通义万相), vertex_ai (Gemini), azure_openai (GPT Image 2/2.5).

## Platform Rules

- **Windows (Git Bash):** `cmd.exe /c "python <skill>/scripts/SCRIPT ARGS"`. Direct python call fails in Git Bash.
- **Linux/WSL:** `python3 <skill>/scripts/SCRIPT ARGS`.
- **Non-ASCII args:** Write content to a unique cache file `<skill>/cache/prompt_<timestamp>.txt` (e.g. `prompt_20260425_183012.txt`) with Write tool, then pass `--prompt-file <skill>/cache/prompt_<timestamp>.txt`. Use a unique filename each time to avoid concurrent overwrites.
- **`<skill>`** = the directory containing this SKILL.md.

## Workflow

### 1. Preflight + Welcome

Run once per conversation to check config and get current settings:

**Step 1a**: Run preflight check:
```
preflight.py
```

**Handle env_checks results** — preflight now returns an `env_checks` object with platform detection and 8 runtime checks. Process the results in this order:

1. **If any check has `status: "fail"`** → `ready` will be `false`. Show the user each failed check's error message (it already contains the fix instruction). Common failures:
   - `python_version` fail: Python too old → message tells user how to install for their platform
   - `config_dir` fail: Missing or not writable → message includes permission fix command
   - `models_json` fail: Missing or malformed → message points to skill reinstall URL
   - `stdlib_modules` fail: Broken Python install → message suggests reinstall
2. **If `warnings` array is non-empty** → briefly mention each warning after showing the main status. Warnings are informational (encoding not UTF-8, output dir missing, Windows Store Python stub) — the skill can still function.
3. **If `ready: false` due to `image_api_key` error** → ask user for API key → `preflight.py --set-key sk-xxx`, then re-run.
4. **If all checks pass and `ready: true`** → proceed normally.

Show `env_checks.platform` and `env_checks.python_version` as part of the status summary so the user knows their detected environment.

**Step 1b**: On first trigger in a conversation, or when user asks for help/usage guide, read `<skill>/references/welcome.md` and show its **COMPLETE content** to the user. Do not truncate, summarize, or omit any section — output the entire file as-is.

**Step 1c**: Immediately after welcome, run:
```
show_config.py
```
Show its output directly after the welcome content. This gives the user a clear view of current model, size, optimization, and output settings.

If the user's message already contains a generation request, proceed immediately after showing welcome + config.

### 2. Handle Settings or Model Switch (if applicable)

If the user is requesting a settings change rather than image generation:

**Common commands** (inline quick-reference):

| Intent | Command |
|--------|---------|
| Change default model | `preflight.py --set-model MODEL` |
| View current config | `show_config.py` |
| Skip/enable optimization | `preflight.py --set-skip-optimize true\|false` |
| Set prompt language | `preflight.py --set-prompt-language en\|zh\|auto` |
| img2img 尺寸模式 | `preflight.py --set-img2img-size-mode follow_input\|fixed` |
| padding 策略 | `preflight.py --set-padding true\|false` |

**For all other settings** (output dir, API key, prompts, model-level config) **or model switch flow** ("切换模型"):
→ Read `<skill>/references/advanced-workflows.md` — it contains the full settings command table, two-step model switch flow, and models reference.

### 3. Optimize Prompt (for image generation requests)

Skip this entire step (go straight to Step 4) if: user says "不优化", OR `settings.skip_optimize=true`.
**`--no-optimize` is a flag for `optimize_prompt.py` only — NEVER pass it to `generate_image.py`.**
When skipping optimization, pass the user's **exact original text verbatim** to `generate_image.py` — do not rewrite, expand, embellish, or add detail yourself. The purpose of "不优化" is to see what the model produces from the raw input; any manual enhancement defeats that purpose.

**Step 3a: Context Gathering (before optimization)**

When the user's prompt is short or vague (roughly under 15–20 Chinese characters or 30 English words, with no explicit mention of style, scene, or mood), ask 1–2 context questions before calling the optimizer. This helps produce a result closer to the user's intent on the first try.

**Skip context gathering if:**
- The user said "不优化" / skip_optimize is true
- The prompt already includes style, scene, lighting, or mood details (e.g., "赛博朋克风格的未来城市，霓虹灯光，雨夜")
- The user provided a reference image (img2img mode — the image itself provides context)
- The user's message clearly conveys complete creative intent

**Round 1 — Ask the most impactful missing dimension.** Analyze which dimension is most absent from the user's prompt. Pick ONE from: 艺术风格/媒介, 场景/背景, 画面氛围/情绪. Provide 3–4 auto-generated options tailored to the user's subject, plus a "自己补充" option. Example for "画一只猫":

```
"你想要什么风格？"
- 照片级写实（摄影质感）
- 水彩手绘（柔和笔触）
- 日系动漫（赛璐璐风格）
- 自己补充
```

If user picks an option → incorporate and consider Round 2.
If user picks "自己补充" → wait for user's free-form text input (do NOT show further options), then incorporate and proceed.

**Round 2 (optional) — Ask the second most impactful missing dimension.** Only ask if Round 1 answer doesn't already cover it and the prompt still has a major gap. Same format: 3–4 options + "自己补充". Maximum 2 rounds total — do not ask more.

After gathering context, merge user's answers into the prompt:
`Enhanced prompt = "{original prompt}，{user_answer1}，{user_answer2}"`

Then proceed to call `optimize_prompt.py` with the enhanced prompt.

**Step 3b: Call Optimizer**

Language selection:
- Default: `auto` (LLM judges whether Chinese output is needed based on content — e.g., 水墨画/书法/传统文化 → Chinese prompt, otherwise English)
- User says "用中文prompt" → pass `--lang zh`
- User says "用英文prompt" → pass `--lang en`
- Persistent: `preflight.py --set-prompt-language en|zh|auto`

```
optimize_prompt.py --prompt "text" --mode text2img|img2img [--lang en|zh|auto] [--model MODEL]
```

For non-ASCII prompts, write to cache file first, then use `--prompt-file`. Show the optimized prompt to user before generating.

### 4. Generate Image

If Step 3 was run, pass the optimized prompt from `optimize_prompt.py` output. If Step 3 was skipped (不优化), pass the user's **exact original words unchanged** — do not rephrase, elaborate, or enrich the prompt yourself (use `--prompt-file` for non-ASCII text).

```
generate_image.py --prompt "text" [--image PATH_OR_URL]... [--model NAME] [--size SIZE] [--output-dir DIR] [--provider PROVIDER] [--ref-index N]
```

`generate_image.py` only accepts these flags — do not pass flags from other scripts (like `--no-optimize` or `--lang`).

- `--image` triggers img2img mode. Can be specified multiple times for multi-image input (e.g., style + content fusion). Limits: volcengine 2+, tongyi (Qwen Image 2.0/3.0) max 3, vertex_ai multi, azure_openai (GPT Image 2/2.5) multi.
- Local image files are auto-converted per provider format (data URI or raw base64).
- `--model` / `--size` can be omitted to use defaults from config.
- `--provider` overrides auto-detection (rarely needed).
- Model config params (negative_prompt, prompt_extend, watermark, n, imageSize) are read from persistent config automatically.
- **img2img model check**: If `--image` is used and the script returns an error about unsupported img2img, show the user the supported models list from the error and ask which model to switch to. Do NOT silently switch — let the user choose.
- **尺寸智能处理** (所有模式):
  - **跨格式自动转换**: 用户可用任何格式指定尺寸 — 像素值(1920x1080)、宽高比(16:9)、预设(2K) — 脚本自动转换为当前 provider 的原生格式。
  - **超范围自动适配**: 指定的尺寸超出 API 限制时不报错，自动 fit 到合法范围并在 `auto_size` 中说明。
  - **img2img padding+crop**: 当输入图尺寸小于 API 最小输出要求时（如 1920x1080 用 volcengine），脚本自动对输入图右下侧 zero-padding 到合法尺寸，生成后 crop 回原始尺寸，确保输出与输入完全同分辨率。需要 Pillow，缺失时降级为等比缩放。
  - **img2img 跟随模式**: 默认 `follow_input` — 无 `--size` 时自动匹配输入图尺寸。可通过 `preflight.py --set-img2img-size-mode fixed` 切换为固定使用 config 默认尺寸。
  - 如果 `auto_size` 中 `strategy` 为 `"pad_crop"`, 告知用户使用了 padding+crop 策略。如果有 `warning` 字段（极端比例或大偏差），显示给用户。如果有 `suggest_model`，告知用户可选的更佳模型。
  - **Gemini 特殊**: 不支持自定义像素尺寸，只能通过宽高比+imageSize 档位控制。输出会自动 resize 到输入尺寸（可能有轻微比例调整）。imageSize 根据输入图像素自动选择。
- **Multi-image reference selection**: When multiple `--image` args are used, the **first image** (index 0) determines the output size by default. If the user's prompt clearly indicates a different image is the "content/画面内容" reference (e.g., "将第二张图渲染成第一张图的风格" means image 2 is content), pass `--ref-index N` (0-indexed) to use that image's dimensions instead. If you cannot determine from the prompt, default to `--ref-index 0`.

**When to show model config during generation:**
- If the user specifies a `--model` different from the default, run `show_config.py --model MODEL` and show the config before generating, so the user sees what parameters this model uses.
- If the user provides a parameter value that doesn't match the model's format (e.g., pixel size for Gemini, aspect ratio for tongyi), run `show_config.py --model MODEL --params-only` to show the user what formats are accepted, then ask for correction.
- If the user asks "这个模型支持什么参数" / "what params can I configure", run `show_config.py --model MODEL --params-only`.

### 4b. Batch Generate (if applicable)

For batch operations (批量生成), the most common pattern:
```
batch_generate.py --mode multi_prompt --theme "主题" --count N
```

For all batch modes (multi_image, multi_prompt_ref, matrix) and detailed options:
→ Read `<skill>/references/advanced-workflows.md` § Batch Generate.

### 5. Present Results

Show: generated image URL (or local path for base64 responses), local saved path, original vs optimized prompt comparison, model used, provider, and size.

**If the result JSON contains `size_notice`, MUST display it to the user.** This informs the user about padding/resize decisions made for their image. If there is a `suggest_model` in `auto_size`, also mention it as an alternative.

### 6. Insert into Feishu (if requested)

When the user asks to insert generated images into a feishu document, read `<skill>/references/feishu-image-guide.md` first. Key points: volcengine/tongyi images have HTTP URLs and can be inserted directly via `<image url="..."/>`; Gemini images are local files and must be uploaded via `feishu docx upload-image --file`. For multi-image comparison layouts, use the Markdown table + `upload-image --parent` method documented in the guide.
