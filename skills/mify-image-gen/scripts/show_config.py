#!/usr/bin/env python3
"""Display image generation config in human-readable format.

Usage:
  show_config.py              # Show default model config + global settings
  show_config.py --model NAME # Show specific model config + global settings
  show_config.py --model NAME --params-only  # Show only model params (for error hints)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mify_image_client import (
    load_settings, get_default_model, detect_provider,
    get_model_config, get_configurable_params, get_img2img_models,
    get_supported_models, get_output_dir, get_model_prompt,
    output_error,
)

LANG_LABELS = {"en": "en (英文)", "zh": "zh (中文)", "auto": "auto (自动判断)"}

PARAM_LABELS = {
    "size": "尺寸",
    "imageSize": "分辨率",
    "watermark": "水印",
    "negative_prompt": "负面提示词",
    "prompt_extend": "Prompt 扩展",
    "n": "生成数量",
    "quality": "质量",
    "output_format": "输出格式",
    "output_compression": "JPEG 压缩质量",
    "input_fidelity": "输入保真度",
    "background": "背景",
}

SIZE_HINTS = {
    "volcengine_maas": "可选: 2K, 4K, 或 WxH (如 3840x2160, 像素范围 3.7M-16.8M)",
    "tongyi": "可选: W*H (如 2048*2048, 1664*928, 1104*1472)",
    "vertex_ai": "可选: 1:1, 16:9, 9:16, 4:3, 3:4",
    "azure_openai": "可选: WxH，16倍数，总像素0.66M-8.29M，最长边≤3840，比例≤3:1",
}

# 按模型覆盖 SIZE_HINTS (用于尺寸约束与同 provider 其他模型不同的模型)
MODEL_SIZE_HINTS = {
    "Doubao-Seedream-5.0-pro": "可选: 1K, 2K, 或 WxH (如 2560x1440, 像素范围 0.9M-6.6M)",
    "Doubao-Seedream-5.0-lite": "可选: 2K, 3K, 4K, 或 WxH (如 3840x2160, 像素范围 3.7M-16.8M)",
    "qwen-image-3.0": "可选: W*H (如 2048*2048, 4096*1000, 像素范围 0.26M-6.6M)",
    "qwen-image-3.0-pro": "可选: W*H (如 2048*2048, 4096*1000, 像素范围 0.26M-6.6M)",
}

IMAGESIZE_HINT = "可选: 1K, 2K, 4K"

PARAM_HINTS = {
    "watermark": "true/false",
    "negative_prompt": "文本，如: 模糊,低质量,畸形",
    "prompt_extend": "true/false (API 自动扩展 prompt)",
    "n": "Tongyi 1-6；Azure 1-10",
    "quality": "low/medium/high/auto (Mify 实测)",
    "output_format": "png/jpeg (Mify 实测)",
    "output_compression": "0-100，仅 JPEG",
    "input_fidelity": "high/low",
    "background": "transparent/opaque/auto",
}


def format_param_value(key, value):
    if isinstance(value, bool):
        return "开启" if value else "关闭"
    if key == "negative_prompt":
        return f'"{value}"' if value else "(空)"
    return str(value)


def show_model_params(model, provider, params):
    """Show model-specific configurable parameters with hints."""
    lines = [
        f"{model} ({provider}) 可配置参数",
    ]
    size_hint = MODEL_SIZE_HINTS.get(model) or SIZE_HINTS.get(provider, "")
    total = len(params)
    for i, key in enumerate(params):
        value = params[key]
        label = PARAM_LABELS.get(key, key)
        display = format_param_value(key, value)
        is_last = (i == total - 1)
        prefix = "└─" if is_last else "├─"

        hint = ""
        if key == "size" and size_hint:
            hint = f"  [{size_hint}]"
        elif key == "imageSize":
            hint = f"  [{IMAGESIZE_HINT}]"
        elif key in PARAM_HINTS:
            hint = f"  [{PARAM_HINTS[key]}]"

        lines.append(f"{prefix} {label}: {display}{hint}")

    print("\n".join(lines))


def show_full_config(model, provider, params, settings):
    """Show full config: model params + global settings."""
    img2img_models = get_img2img_models()
    supports_img2img = model in img2img_models
    output_dir = get_output_dir()
    skip_opt = settings.get("skip_optimize", False)
    opt_model = settings.get("optimize_model", "deepseek/deepseek-flash")
    lang = settings.get("prompt_language", "auto")

    prompt_preview = get_model_prompt(model, "text2img")
    if len(prompt_preview) > 50:
        prompt_preview = prompt_preview[:50] + "..."

    lines = [
        "当前配置",
        f"├─ 模型: {model} ({provider})",
        f"├─ 图生图: {'支持' if supports_img2img else '不支持'}",
    ]

    size_hint = MODEL_SIZE_HINTS.get(model) or SIZE_HINTS.get(provider, "")
    for key in params:
        value = params[key]
        label = PARAM_LABELS.get(key, key)
        display = format_param_value(key, value)
        hint = ""
        if key == "size" and size_hint:
            hint = f"  [{size_hint}]"
        elif key == "imageSize":
            hint = f"  [{IMAGESIZE_HINT}]"
        lines.append(f"├─ {label}: {display}{hint}")

    lines.append(f"├─ Prompt 优化: {'关闭' if skip_opt else f'开启 ({opt_model})'}")
    lines.append(f"├─ Prompt 语言: {LANG_LABELS.get(lang, lang)}")
    lines.append(f"├─ 输出目录: {output_dir}")
    lines.append(f"└─ 系统提示词: {prompt_preview}")

    print("\n".join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", help="Show config for a specific model instead of default")
    parser.add_argument("--params-only", action="store_true",
                        help="Show only model configurable params (for error hints)")
    args = parser.parse_args()

    model = args.model or get_default_model()
    supported = get_supported_models()
    if model not in supported:
        output_error(f"Unsupported model: {model}", f"Supported: {', '.join(supported)}")

    provider = detect_provider(model)
    params = get_configurable_params(model)
    settings = load_settings()

    if args.params_only:
        show_model_params(model, provider, params)
    else:
        show_full_config(model, provider, params, settings)


if __name__ == "__main__":
    main()
