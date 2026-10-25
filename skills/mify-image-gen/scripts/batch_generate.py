#!/usr/bin/env python3
"""Batch image generation with multiple modes."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mify_image_client import (
    load_config, load_settings, get_default_model,
    llm_request, generate_one,
    output_json, output_error,
)


def diversify_theme(theme, count, config):
    """Use LLM to generate diverse prompts around a theme."""
    messages = [
        {"role": "system", "content": (
            f"Generate exactly {count} diverse, creative image generation prompts "
            f"around the theme: '{theme}'. Each prompt should explore a different "
            f"angle, style, or composition. Return a JSON array of English strings, "
            f"nothing else. No markdown formatting."
        )},
        {"role": "user", "content": theme},
    ]
    settings = load_settings()
    result = llm_request(
        messages, config,
        model=settings.get("optimize_model", "deepseek/deepseek-flash"),
        provider=settings.get("optimize_provider", "deepseek"),
    )
    text = result["choices"][0]["message"]["content"].strip()
    import re
    match = re.search(r'\[.*\]', text, re.S)
    if not match:
        raise RuntimeError(f"LLM did not return a JSON array: {text[:200]}")
    prompts = json.loads(match.group())
    if not isinstance(prompts, list) or not all(isinstance(p, str) for p in prompts):
        raise RuntimeError(f"LLM returned invalid prompts format: {text[:200]}")
    return prompts


def collect_images(images_dir):
    """Collect image files from a directory."""
    d = Path(images_dir)
    if not d.is_dir():
        raise RuntimeError(f"Not a directory: {images_dir}")
    exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
    files = sorted(str(f) for f in d.iterdir() if f.suffix.lower() in exts)
    if not files:
        raise RuntimeError(f"No image files found in: {images_dir}")
    return files


def resolve_prompts(args, config):
    """Resolve prompts from --prompts-file or --theme."""
    if args.prompts_file:
        p = Path(args.prompts_file)
        if not p.exists():
            raise RuntimeError(f"Prompts file not found: {args.prompts_file}")
        data = json.loads(p.read_text(encoding="utf-8"))
        prompts = data.get("prompts", data) if isinstance(data, dict) else data
        if not isinstance(prompts, list):
            raise RuntimeError("Prompts file must contain a JSON array or {\"prompts\": [...]}")
        return prompts
    elif args.theme:
        print(json.dumps({"status": "diversifying_theme", "theme": args.theme,
                          "count": args.count}), file=sys.stderr)
        return diversify_theme(args.theme, args.count, config)
    else:
        raise RuntimeError("Either --prompts-file or --theme is required for this mode")


def resolve_single_prompt(args):
    """Resolve single prompt from --prompt or --prompt-file."""
    if args.prompt_file:
        p = Path(args.prompt_file)
        if not p.exists():
            raise RuntimeError(f"Prompt file not found: {args.prompt_file}")
        return p.read_text(encoding="utf-8").strip()
    elif args.prompt:
        return args.prompt
    else:
        raise RuntimeError("--prompt or --prompt-file is required for this mode")


def build_tasks(mode, args, config):
    """Build task list based on mode."""
    if mode == "multi_prompt":
        prompts = resolve_prompts(args, config)
        return [{"prompt": p, "images": None} for p in prompts]

    elif mode == "multi_image":
        prompt = resolve_single_prompt(args)
        if not args.images_dir:
            raise RuntimeError("--images-dir is required for multi_image mode")
        images = collect_images(args.images_dir)
        return [{"prompt": prompt, "images": [img]} for img in images]

    elif mode == "multi_prompt_ref":
        prompts = resolve_prompts(args, config)
        if not args.image:
            raise RuntimeError("--image is required for multi_prompt_ref mode")
        return [{"prompt": p, "images": [args.image]} for p in prompts]

    elif mode == "matrix":
        prompts = resolve_prompts(args, config)
        if not args.images_dir:
            raise RuntimeError("--images-dir is required for matrix mode")
        images = collect_images(args.images_dir)
        tasks = []
        for p in prompts:
            for img in images:
                tasks.append({"prompt": p, "images": [img]})
        return tasks

    else:
        raise RuntimeError(f"Unknown mode: {mode}")


def batch_run(tasks, model, output_dir, size=None, provider=None):
    """Execute generation tasks sequentially with progress reporting."""
    results = []
    for i, task in enumerate(tasks):
        print(json.dumps({"progress": i + 1, "total": len(tasks),
                          "prompt": task["prompt"][:60]}), file=sys.stderr)
        try:
            r = generate_one(
                prompt=task["prompt"],
                model=model,
                images=task.get("images"),
                size=size,
                output_dir=output_dir,
                provider=provider,
            )
            r["task_index"] = i
            r["status"] = "success"
        except Exception as e:
            r = {"task_index": i, "status": "failed", "error": str(e),
                 "prompt": task["prompt"][:80]}
        results.append(r)

    success = sum(1 for r in results if r["status"] == "success")
    return {
        "results": results,
        "summary": {
            "total": len(tasks),
            "success": success,
            "failed": len(tasks) - success,
        },
    }


def main():
    default_model = get_default_model()

    parser = argparse.ArgumentParser(description="Batch image generation")
    parser.add_argument("--mode", required=True,
                        choices=["multi_prompt", "multi_image", "multi_prompt_ref", "matrix"])

    prompt_group = parser.add_mutually_exclusive_group()
    prompt_group.add_argument("--prompts-file", help="JSON file with prompts array")
    prompt_group.add_argument("--theme", help="Theme for LLM prompt diversification")
    parser.add_argument("--count", type=int, default=4, help="Number of prompts to generate from theme")

    parser.add_argument("--prompt", help="Single prompt (for multi_image mode)")
    parser.add_argument("--prompt-file", help="Single prompt file (non-ASCII)")
    parser.add_argument("--image", help="Single reference image path")
    parser.add_argument("--images-dir", help="Directory of source images")

    parser.add_argument("--model", default=default_model)
    parser.add_argument("--size")
    parser.add_argument("--output-dir")
    parser.add_argument("--provider")
    args = parser.parse_args()

    try:
        config = load_config()
        if not config.get("image_api_key"):
            output_error("image_api_key not configured", "Run preflight.py --set-key sk-xxx first")

        tasks = build_tasks(args.mode, args, config)

        print(json.dumps({"status": "starting_batch", "mode": args.mode,
                          "task_count": len(tasks), "model": args.model}), file=sys.stderr)

        result = batch_run(
            tasks=tasks,
            model=args.model,
            output_dir=args.output_dir,
            size=args.size,
            provider=args.provider,
        )

        if args.output_dir:
            result_path = Path(args.output_dir) / "batch_result.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

        output_json(result)

    except (RuntimeError, ValueError, FileNotFoundError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
