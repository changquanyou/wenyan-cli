# Advanced Workflows & Reference

## Settings Commands

If the user is requesting a settings change rather than image generation:

| User Intent | Command |
|-------------|---------|
| Change output directory | `preflight.py --set-output-dir PATH` |
| Change default model | `preflight.py --set-model MODEL` |
| Change API key | `preflight.py --set-key KEY` |
| Change global text2img prompt | `preflight.py --set-text2img-prompt TEXT` |
| Change global img2img prompt | `preflight.py --set-img2img-prompt TEXT` |
| Get model full config | `preflight.py --get-model-config MODEL` |
| Set model config params | `preflight.py --set-model-config MODEL '{"param":"value"}'` |
| Set model-level prompt | `preflight.py --set-model-prompt MODEL MODE TEXT` |
| Skip/enable prompt optimization | `preflight.py --set-skip-optimize true\|false` |
| Set prompt output language | `preflight.py --set-prompt-language en\|zh\|auto` |
| View current config | `show_config.py` |
| View specific model config | `show_config.py --model MODEL` |
| View model params only | `show_config.py --model MODEL --params-only` |

## Model Switch — Two-Step Selection

When user says "切换模型" (without specifying which model):

**Step 1: Choose provider (AskUserQuestion with 4 options)**

Show four provider options, each listing its available models:
- 火山引擎 (volcengine_maas): Doubao-Seedream-5.0-pro, Doubao-Seedream-5.0-lite, Doubao-Seedream-4.5, Doubao-Seedream-4.0
- 通义万相 (tongyi): qwen-image-2.0, qwen-image-2.0-pro, qwen-image-3.0, qwen-image-3.0-pro, wan2.6-t2i, z-image-turbo
- Gemini (vertex_ai): gemini-2.5-flash-image, gemini-3-pro-image, gemini-3.1-flash-image
- OpenAI (azure_openai): gpt-image-2, gpt-image-2.5-flare, gpt-image-2.5-sunburst

**Step 2: Choose model (numbered list, user replies with number)**

After user selects a provider, list all models under that provider numbered 1-N. User replies with a number.

Example for tongyi:
```
请选择模型（回复数字）：
1. qwen-image-2.0
2. qwen-image-2.0-pro
3. qwen-image-3.0
4. qwen-image-3.0-pro
5. wan2.6-t2i
6. z-image-turbo
```

**Step 3: Confirm and display config**

After model is selected:
1. Run `preflight.py --set-model MODEL`
2. Run `show_config.py --model MODEL` to display the model's full config to the user
3. Ask user: "是否需要修改配置？" If yes → show `show_config.py --model MODEL --params-only` and ask which param to change → `preflight.py --set-model-config MODEL '{"param":"value"}'`
4. If user says no → confirm default config, proceed

**Shortcut**: If user directly says "用 qwen-image-2.0" (specifies model name), skip Steps 1-2, go directly to Step 3.

## Batch Generate

For batch operations, use `batch_generate.py`:

```
batch_generate.py --mode MODE [options]
```

| User Intent | Command |
|-------------|---------|
| 围绕主题批量生成 | `batch_generate.py --mode multi_prompt --theme "主题" --count N` |
| 提供 prompts 批量生成 | `batch_generate.py --mode multi_prompt --prompts-file prompts.json` |
| 同一要求处理批量图片 | `batch_generate.py --mode multi_image --prompt "text" --images-dir ./photos/` |
| 同一参考图多种风格 | `batch_generate.py --mode multi_prompt_ref --prompts-file pf.json --image ref.jpg` |
| 全组合矩阵 | `batch_generate.py --mode matrix --prompts-file pf.json --images-dir ./photos/` |

- `--theme` uses LLM to auto-generate diverse prompts around the theme (mutually exclusive with `--prompts-file`).
- `--prompts-file` expects `{"prompts": ["prompt1", "prompt2", ...]}` or a plain JSON array.
- `--count N` controls how many prompts to generate from theme (default 4).
- Results are saved to `batch_result.json` in the output directory.

## Models & Providers Reference

### 输出尺寸规格 (实测验证)

| Model | Provider | 输出尺寸 | 默认 | 可配参数 | text2img | img2img |
|-------|----------|---------|------|---------|----------|---------|
| Doubao-Seedream-5.0-lite | volcengine_maas | 2K/3K/4K 或 WxH (总像素 3.7M\~16.8M, 比例 1:16\~16:1) | 2K | watermark | Y | Y |
| Doubao-Seedream-5.0-pro | volcengine_maas | 1K/2K 或 WxH (总像素 0.9M\~6.6M, 比例 1:16\~16:1) | 2K | watermark | Y | Y |
| Doubao-Seedream-4.5 | volcengine_maas | 2K/4K 或 WxH (同上像素范围) | 2K | watermark | Y | Y |
| Doubao-Seedream-4.0 | volcengine_maas | 2K/4K 或 WxH (同上像素范围) | 2K | watermark | Y | Y |
| qwen-image-2.0 | tongyi | W\*H (总像素 262K\~4.2M, API自动对齐16倍数) | 2048\*2048 | negative_prompt, prompt_extend, n(1-6) | Y | Y |
| qwen-image-2.0-pro | tongyi | 总像素 262K~4.2M，API自动对齐16倍数 | 2048\*2048 | negative_prompt, prompt_extend, n(1-6) | Y | Y |
| qwen-image-3.0 | tongyi | 总像素 262K~6.5M；支持1-3张参考图；显式4096*1000实测保持原尺寸 | 2048\*2048 | negative_prompt, prompt_extend, n(1-6) | Y | Y |
| qwen-image-3.0-pro | tongyi | 总像素 262K~6.5M；显式4096*1000已实测可用并保持原尺寸；尺寸适配路径按16倍数处理 | 2048\*2048 | negative_prompt, prompt_extend, n(1-6) | Y | Y |
| wan2.6-t2i | tongyi | W\*H (总像素 590K\~2.07M) | 1280\*1280 | negative_prompt, prompt_extend, watermark | Y | N |
| z-image-turbo | tongyi | W\*H (各边 512\~2048) | 1024\*1024 | negative_prompt, prompt_extend | Y | N |
| gemini-2.5-flash-image | vertex_ai | 10种宽高比, imageSize 仅 1K | 1:1 / 1K | imageSize(仅1K) | Y | Y |
| gemini-3-pro-image | vertex_ai | 9种宽高比, imageSize 1K/2K/4K | 1:1 / 2K | imageSize(1K/2K/4K) | Y | Y |
| gemini-3.1-flash-image | vertex_ai | 10种宽高比(含21:9), imageSize 1K/2K/4K | 1:1 / 2K | imageSize(1K/2K/4K) | Y | Y |
| gpt-image-2 | azure_openai | WxH (16倍数, 最长边≤3840, 比例≤3:1, 总像素 655K\~8.29M) | 1536x1024 | size, quality, n, output_format, output_compression, input_fidelity, background | Y (含多图融合) | Y |
| gpt-image-2.5-flare | azure_openai | 同上；速度优先；支持透明背景、蒙版、多图融合 | 1536x1024 | quality(low/medium/high/auto), n(1-10), PNG/JPEG, input_fidelity, background | Y | Y |
| gpt-image-2.5-sunburst | azure_openai | 同上；质量与连续编辑优先；支持透明背景、蒙版、多图融合 | 1536x1024 | quality(low/medium/high/auto), n(1-10), PNG/JPEG, input_fidelity, background | Y | Y |

**volcengine 预设分辨率:** 2K=2048², 3K=3072²(仅5.0-lite), 4K=4096²

**tongyi 推荐分辨率:** 1:1(1024\*1024), 2:3(768\*1152), 3:2(1152\*768), 3:4(960\*1280), 4:3(1280\*960), 9:16(720\*1280), 16:9(1280\*720), 21:9(1344\*576)

**tongyi 尺寸适配路径通常按 16 的倍数处理**（如 1920\*1080 → 适配为 1920\*1088）；qwen-image-3.0/3.0-pro 显式指定 `4096*1000` 已实测保持 `4096*1000` 输出

**GPT Image 2.5 Mify 实测限制:** 当前 Mify 路由接受 quality=`low`/`medium`/`high`/`auto`、output_format=`png`/`jpeg`。厂商直连文档中的 xhigh/max/WebP 不作为本 skill 的可用能力声明。

**gemini-2.5-flash 宽高比:** 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9

**gemini-3-pro-image 宽高比:** 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9 (无 21:9)

**gemini-3.1-flash 宽高比:** 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9 (同 2.5-flash, 但支持 1K/2K/4K)

**Gemini 不支持自定义像素尺寸**，只能通过 aspectRatio + imageSize 控制。

### img2img 输入图限制 (实测验证)

所有 provider 对 img2img 输入图尺寸**无限制** (64x64 \~ 4096x4096 均实测通过)。API 自动缩放输入图，输出尺寸完全由输出参数控制。

img2img 模式下未指定 `--size` 时，输出尺寸自动匹配输入图（适配到 provider 输出约束范围内）。
