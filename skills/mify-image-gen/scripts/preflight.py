#!/usr/bin/env python3
"""Preflight check and config management for Mify Image Generation."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mify_image_client import (
    load_credentials, load_settings, load_prompts,
    save_credential, save_setting, save_prompt,
    get_output_dir, get_supported_models, get_default_model,
    get_model_config, save_model_config, get_model_info,
    get_model_prompt, save_model_prompt, detect_provider,
    get_all_providers, output_json, output_error,
)

_SKILL_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _SKILL_ROOT / "config"
_CACHE_DIR = _SKILL_ROOT / "cache"


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def detect_platform():
    """Detect the runtime platform.

    Returns one of: windows_powershell, windows_gitbash, linux, wsl, macos, unknown.
    """
    if sys.platform == "win32":
        if os.environ.get("MSYSTEM"):
            return "windows_gitbash"
        return "windows_powershell"
    if sys.platform == "darwin":
        return "macos"
    # Linux or WSL
    try:
        with open("/proc/version", "r") as f:
            content = f.read().lower()
            if "microsoft" in content or "wsl" in content:
                return "wsl"
    except (FileNotFoundError, PermissionError):
        pass
    return "linux"


# ---------------------------------------------------------------------------
# Individual checks — each returns {"name", "status", "detail"?, ...}
# ---------------------------------------------------------------------------

def _check_python_version(platform):
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if v < (3, 6):
        hints = {
            "windows_powershell": "Install Python 3.11+ from https://www.python.org/downloads/ — check 'Add Python to PATH' during install.",
            "windows_gitbash": "Install Python 3.11+ from https://www.python.org/downloads/ — check 'Add Python to PATH' during install.",
            "linux": "Run: sudo apt install python3 (Debian/Ubuntu) or sudo yum install python3 (RHEL/CentOS).",
            "wsl": "Run: sudo apt install python3 (inside WSL).",
            "macos": "Run: brew install python3.",
        }
        fix = hints.get(platform, "Install Python 3.6+.")
        return {
            "name": "python_version", "status": "fail", "detail": ver,
            "error": f"Python {ver} detected, minimum 3.6 required. {fix}",
        }
    return {"name": "python_version", "status": "pass", "detail": ver}


def _check_encoding():
    enc = getattr(sys.stdout, "encoding", None) or "unknown"
    if enc.lower().replace("-", "") != "utf8":
        return {
            "name": "encoding_support", "status": "warn", "detail": enc,
            "warning": f"Console encoding is {enc}, not UTF-8. Non-ASCII prompts may not display correctly.",
        }
    return {"name": "encoding_support", "status": "pass", "detail": enc}


def _check_stdlib_modules():
    required = [
        "urllib.request", "base64", "pathlib", "mimetypes", "re", "datetime",
    ]
    missing = []
    for mod in required:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return {
            "name": "stdlib_modules", "status": "fail",
            "detail": ", ".join(missing),
            "error": f"Required stdlib modules not importable: {', '.join(missing)}. Python installation may be incomplete — reinstall Python.",
        }
    return {"name": "stdlib_modules", "status": "pass"}


def _check_config_dir(platform):
    if not _CONFIG_DIR.is_dir():
        return {
            "name": "config_dir", "status": "fail",
            "detail": str(_CONFIG_DIR),
            "error": f"Config directory not found: {_CONFIG_DIR}. The skill may not be installed correctly. Re-install from https://micode.mioffice.cn/#/skills/1029",
        }
    # Writability check
    try:
        test_file = _CONFIG_DIR / ".env_check_tmp"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
    except OSError:
        hints = {
            "linux": f"Run: chmod 755 {_CONFIG_DIR}",
            "wsl": f"Run: chmod 755 {_CONFIG_DIR}",
        }
        fix = hints.get(platform, "Check folder permissions.")
        return {
            "name": "config_dir", "status": "fail",
            "detail": str(_CONFIG_DIR),
            "error": f"Config directory is not writable: {_CONFIG_DIR}. {fix}",
        }
    return {"name": "config_dir", "status": "pass", "detail": str(_CONFIG_DIR)}


def _check_models_json():
    models_path = _CONFIG_DIR / "models.json"
    if not models_path.is_file():
        return {
            "name": "models_json", "status": "fail",
            "detail": str(models_path),
            "error": f"models.json not found: {models_path}. Re-install the skill from https://micode.mioffice.cn/#/skills/1029",
        }
    try:
        with open(models_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "providers" not in data or "models" not in data:
            return {
                "name": "models_json", "status": "fail",
                "detail": "missing providers or models key",
                "error": f"models.json is malformed (missing 'providers' or 'models'). Re-install the skill.",
            }
    except (json.JSONDecodeError, OSError) as e:
        return {
            "name": "models_json", "status": "fail",
            "detail": str(e),
            "error": f"models.json failed to load: {e}. Re-install the skill.",
        }
    return {"name": "models_json", "status": "pass"}


def _check_output_dir():
    out_dir = Path(get_output_dir())
    if out_dir.is_dir():
        return {"name": "output_dir", "status": "pass", "detail": str(out_dir)}
    # Check if parent exists (dir will be auto-created on first generation)
    parent = out_dir.parent
    if parent.is_dir():
        return {
            "name": "output_dir", "status": "warn", "detail": str(out_dir),
            "warning": f"Output directory {out_dir} does not exist yet. It will be created automatically on first generation.",
        }
    return {
        "name": "output_dir", "status": "warn", "detail": str(out_dir),
        "warning": f"Output directory {out_dir} and its parent do not exist. Verify the path is correct via: preflight.py --set-output-dir PATH",
    }


def _check_cache_dir():
    if _CACHE_DIR.is_dir():
        return {"name": "cache_dir", "status": "pass", "detail": str(_CACHE_DIR)}
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return {"name": "cache_dir", "status": "pass", "detail": str(_CACHE_DIR)}
    except OSError as e:
        return {
            "name": "cache_dir", "status": "warn", "detail": str(e),
            "warning": f"Cannot create cache directory {_CACHE_DIR}: {e}. Non-ASCII prompt caching will not work.",
        }


def _check_pillow():
    try:
        from PIL import Image
        ver = getattr(Image, "__version__", "unknown")
        return {"name": "pillow", "status": "pass", "detail": ver}
    except ImportError:
        return {
            "name": "pillow", "status": "warn",
            "warning": (
                "Pillow 未安装，img2img 的 padding/crop/resize 功能不可用，将降级为等比缩放。"
                "安装: pip install Pillow"
            ),
        }


def _check_windows_python_path():
    exe = sys.executable or ""
    if "WindowsApps" in exe:
        return {
            "name": "windows_python_path", "status": "warn", "detail": exe,
            "warning": (
                f"Python appears to be the Microsoft Store stub ({exe}). "
                "Install Python from https://www.python.org/downloads/ and ensure it appears before WindowsApps in your PATH."
            ),
        }
    return {"name": "windows_python_path", "status": "pass", "detail": exe}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_env_checks():
    """Run all environment checks and return aggregated results."""
    platform = detect_platform()
    checks = []
    errors = []
    warnings = []

    # Universal checks
    for check_fn in [
        lambda: _check_python_version(platform),
        _check_encoding,
        _check_stdlib_modules,
        lambda: _check_config_dir(platform),
        _check_models_json,
        _check_output_dir,
        _check_cache_dir,
        _check_pillow,
    ]:
        result = check_fn()
        checks.append(result)
        if result.get("error"):
            errors.append(result["error"])
        if result.get("warning"):
            warnings.append(result["warning"])

    # Windows-specific checks
    if platform in ("windows_powershell", "windows_gitbash"):
        result = _check_windows_python_path()
        checks.append(result)
        if result.get("warning"):
            warnings.append(result["warning"])

    return {
        "platform": platform,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_executable": sys.executable or "unknown",
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser(description="Mify Image Gen config")
    parser.add_argument("--set-key", help="Set API key")
    parser.add_argument("--set-output-dir", help="Set output directory")
    parser.add_argument("--set-model", help="Set default model")
    parser.add_argument("--set-optimize-model", help="Set LLM model for prompt optimization")
    parser.add_argument("--set-text2img-prompt", help="Set global text2img system prompt")
    parser.add_argument("--set-img2img-prompt", help="Set global img2img system prompt")

    parser.add_argument("--get-model-config", metavar="MODEL",
        help="Get full config for a model (defaults + user overrides + system prompt)")
    parser.add_argument("--set-model-config", nargs=2, metavar=("MODEL", "JSON"),
        help="Set model config overrides, e.g. --set-model-config qwen-image-2.0 '{\"size\":\"1536*2688\"}'")
    parser.add_argument("--set-model-prompt", nargs=3, metavar=("MODEL", "MODE", "TEXT"),
        help="Set model-level system prompt, MODE is text2img or img2img")
    parser.add_argument("--set-skip-optimize", choices=["true", "false"],
        help="Persist skip prompt optimization setting")
    parser.add_argument("--set-prompt-language", choices=["en", "zh", "auto"],
        help="Set default prompt output language")
    parser.add_argument("--set-img2img-size-mode", choices=["follow_input", "fixed"],
        help="img2img output size mode: follow_input (match input image) or fixed (use config default)")
    parser.add_argument("--set-padding", choices=["true", "false"],
        help="Enable/disable padding strategy for size-mismatched img2img")
    args = parser.parse_args()

    # Apply settings
    if args.set_key:
        save_credential("image_api_key", args.set_key)
    if args.set_output_dir is not None:
        save_setting("image_output_dir", args.set_output_dir)
    if args.set_model:
        supported = get_supported_models()
        if args.set_model not in supported:
            output_error(f"Unsupported model: {args.set_model}", f"Supported: {', '.join(supported)}")
        save_setting("default_model", args.set_model)
    if args.set_skip_optimize:
        save_setting("skip_optimize", args.set_skip_optimize == "true")
    if args.set_prompt_language:
        save_setting("prompt_language", args.set_prompt_language)
    if args.set_img2img_size_mode:
        save_setting("img2img_size_mode", args.set_img2img_size_mode)
    if args.set_padding:
        save_setting("padding_enabled", args.set_padding == "true")
    if args.set_optimize_model:
        save_setting("optimize_model", args.set_optimize_model)
    if args.set_text2img_prompt:
        save_prompt("text2img", args.set_text2img_prompt)
    if args.set_img2img_prompt:
        save_prompt("img2img", args.set_img2img_prompt)

    # Set model-level config
    if args.set_model_config:
        model_name, json_str = args.set_model_config
        supported = get_supported_models()
        if model_name not in supported:
            output_error(f"Unsupported model: {model_name}", f"Supported: {', '.join(supported)}")
        try:
            overrides = json.loads(json_str)
        except json.JSONDecodeError as e:
            output_error(f"Invalid JSON: {e}")
        save_model_config(model_name, overrides)
        output_json({"ok": True, "model": model_name, "saved": overrides})
        return

    # Set model-level system prompt
    if args.set_model_prompt:
        model_name, mode, text = args.set_model_prompt
        if mode not in ("text2img", "img2img"):
            output_error(f"Invalid mode: {mode}", "Use 'text2img' or 'img2img'")
        supported = get_supported_models()
        if model_name not in supported:
            output_error(f"Unsupported model: {model_name}", f"Supported: {', '.join(supported)}")
        save_model_prompt(model_name, mode, text)
        output_json({"ok": True, "model": model_name, "mode": mode, "prompt": text[:100] + "..." if len(text) > 100 else text})
        return

    # Get model config (detailed)
    if args.get_model_config:
        model_name = args.get_model_config
        supported = get_supported_models()
        if model_name not in supported:
            output_error(f"Unsupported model: {model_name}", f"Supported: {', '.join(supported)}")
        info = get_model_info(model_name)
        output_json(info)
        return

    # Default: preflight check
    env_result = run_env_checks()
    errors = list(env_result.get("errors", []))

    creds = load_credentials()
    settings = load_settings()

    api_key = creds.get("image_api_key", "").strip()
    if not api_key:
        errors.append("image_api_key not configured")
    elif not api_key.startswith("sk-"):
        errors.append("image_api_key should start with 'sk-'")

    default_model = get_default_model()
    provider = detect_provider(default_model)
    model_config = get_model_config(default_model)

    prompts_preview = {}
    for mode in ("text2img", "img2img"):
        p = get_model_prompt(default_model, mode)
        prompts_preview[mode] = (p[:60] + "...") if len(p) > 60 else p

    output_json({
        "ready": len(errors) == 0,
        "errors": errors,
        "env_checks": {
            "platform": env_result["platform"],
            "python_version": env_result["python_version"],
            "python_executable": env_result["python_executable"],
            "checks": env_result["checks"],
            "warnings": env_result.get("warnings", []),
        },
        "output_dir": get_output_dir(),
        "default_model": default_model,
        "current_model_provider": provider,
        "current_model_config": model_config,
        "optimize_model": settings.get("optimize_model", "deepseek/deepseek-flash"),
        "skip_optimize": settings.get("skip_optimize", False),
        "prompt_language": settings.get("prompt_language", "auto"),
        "supported_models": get_supported_models(),
        "providers": get_all_providers(),
        "system_prompt_preview": prompts_preview,
    })


if __name__ == "__main__":
    main()
