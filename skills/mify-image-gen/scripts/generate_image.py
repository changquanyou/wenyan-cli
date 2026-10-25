#!/usr/bin/env python3
"""CLI for image generation: text-to-image and image-to-image."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mify_image_client import (
    get_default_model, generate_one, output_json, output_error,
)


def main():
    default_model = get_default_model()

    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt")
    group.add_argument("--prompt-file")
    parser.add_argument("--image", action="append", help="Reference image(s) for img2img, repeatable")
    parser.add_argument("--model", default=default_model)
    parser.add_argument("--size", help="Override model default size")
    parser.add_argument("--output-dir")
    parser.add_argument("--provider", help="Override auto-detected provider")
    parser.add_argument("--ref-index", type=int, default=0,
                        help="Index of reference image for auto-sizing (default: 0)")
    parser.add_argument("--mask", help="Mask image for inpainting (white=edit area)")
    args = parser.parse_args()

    if args.prompt_file:
        p = Path(args.prompt_file)
        if not p.exists():
            output_error(f"Prompt file not found: {args.prompt_file}")
        prompt = p.read_text(encoding="utf-8").strip()
    else:
        prompt = args.prompt

    try:
        result = generate_one(
            prompt=prompt,
            model=args.model,
            images=args.image,
            size=args.size,
            output_dir=args.output_dir,
            provider=args.provider,
            ref_index=args.ref_index,
            mask=args.mask,
        )
        output_json(result)
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
