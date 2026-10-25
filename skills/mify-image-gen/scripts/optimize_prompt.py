#!/usr/bin/env python3
"""Prompt optimization via LLM for image generation."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mify_image_client import (
    load_config, load_settings,
    get_system_prompt,
    llm_request, output_json, output_error,
)


def optimize(prompt, mode, config, lang="auto", model=None):
    """Call LLM to optimize a prompt."""
    system_prompt = get_system_prompt(mode, lang=lang, model=model)
    if not system_prompt:
        output_error("System prompt not found in config/prompts.json")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    settings = load_settings()
    result = llm_request(
        messages, config,
        model=settings.get("optimize_model", "deepseek/deepseek-flash"),
        provider=settings.get("optimize_provider", "deepseek"),
    )

    choices = result.get("choices", [])
    if not choices:
        output_error("LLM returned no choices", "Check API key and model availability")

    optimized = choices[0].get("message", {}).get("content", "").strip()
    if not optimized:
        output_error("LLM returned empty content")

    return optimized


def _resolve_prompt(args):
    if args.prompt_file:
        p = Path(args.prompt_file)
        if not p.exists():
            output_error(f"Prompt file not found: {args.prompt_file}")
        return p.read_text(encoding="utf-8").strip()
    return args.prompt


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt")
    group.add_argument("--prompt-file")
    parser.add_argument("--mode", choices=["text2img", "img2img"], default="text2img")
    parser.add_argument("--model", help="Use model-specific system prompt if configured")
    parser.add_argument("--lang", choices=["en", "zh", "auto"], default=None,
                        help="Output language for optimized prompt")
    parser.add_argument("--no-optimize", action="store_true")
    args = parser.parse_args()

    prompt = _resolve_prompt(args)

    # Skip: CLI flag > persistent setting > default (optimize)
    skip = args.no_optimize
    if not skip:
        settings = load_settings()
        skip = settings.get("skip_optimize", False)
    if skip:
        output_json({"original": prompt, "optimized": prompt, "model": "none (skipped)"})
        return

    config = load_config()
    if not config.get("image_api_key"):
        output_error("image_api_key not configured", "Run preflight.py --set-key sk-xxx first")

    # Language: CLI flag > persistent setting > default (auto)
    lang = args.lang
    if not lang:
        settings = load_settings()
        lang = settings.get("prompt_language", "auto")

    settings = load_settings()
    optimized = optimize(prompt, args.mode, config, lang=lang, model=args.model)
    output_json({
        "original": prompt,
        "optimized": optimized,
        "model": settings.get("optimize_model", "deepseek/deepseek-flash"),
        "lang": lang,
    })


if __name__ == "__main__":
    main()
