#!/usr/bin/env python3
"""
Shared Mify Image API client module.

All config is loaded from <skill>/config/ directory.
All HTTP via Python stdlib (urllib.request). No third-party dependencies.
"""

import base64
import io
import json
import math
import mimetypes
import re
import struct
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Fix console encoding on Windows (GBK -> UTF-8)
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    for _stream_name in ("stdout", "stderr"):
        _stream = getattr(sys, _stream_name)
        if hasattr(_stream, "buffer"):
            setattr(
                sys,
                _stream_name,
                io.TextIOWrapper(_stream.buffer, encoding="utf-8", errors="replace"),
            )
    if hasattr(sys.stdin, "buffer"):
        sys.stdin = io.TextIOWrapper(
            sys.stdin.buffer, encoding="utf-8", errors="replace"
        )

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

MIFY_MODEL_API = "http://model.mify.ai.srv/v1"
MIFY_MODEL_API_SGP = "http://model-sgp.mify.ai.srv/v1"

_SKILL_SCRIPTS_DIR = Path(__file__).resolve().parent
_SKILL_ROOT_DIR = _SKILL_SCRIPTS_DIR.parent
_CONFIG_DIR = _SKILL_ROOT_DIR / "config"
_CACHE_DIR = _SKILL_ROOT_DIR / "cache"


# ---------------------------------------------------------------------------
# Model registry — loaded from config/models.json (single source of truth)
# ---------------------------------------------------------------------------

_REGISTRY = None


def _load_model_registry():
    """Load and validate model registry. Cached after first call."""
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY
    path = _CONFIG_DIR / "models.json"
    reg = _load_json(path)
    if not reg:
        raise RuntimeError(f"Model registry not found: {path}")
    _validate_registry(reg)
    _REGISTRY = reg
    return _REGISTRY


def _validate_registry(reg):
    providers = reg.get("providers", {})
    models = reg.get("models", {})
    for model_name, entry in models.items():
        pid = entry.get("provider")
        if pid not in providers:
            raise RuntimeError(
                f"models.json: model '{model_name}' references unknown provider '{pid}'"
            )
        if "defaults" not in entry:
            raise RuntimeError(
                f"models.json: model '{model_name}' missing 'defaults'"
            )


def get_provider_config(provider_id):
    reg = _load_model_registry()
    return reg["providers"].get(provider_id, {})


def get_model_entry(model):
    reg = _load_model_registry()
    return reg["models"].get(model)


def detect_provider(model_name):
    entry = get_model_entry(model_name)
    return entry["provider"] if entry else None


def get_api_host(provider_id):
    return get_provider_config(provider_id).get("host", MIFY_MODEL_API)


def get_all_providers():
    reg = _load_model_registry()
    result = {}
    for model_name, entry in reg["models"].items():
        result.setdefault(entry["provider"], []).append(model_name)
    return result


def get_supported_models():
    reg = _load_model_registry()
    return list(reg["models"].keys())


def get_img2img_models():
    reg = _load_model_registry()
    return [m for m, e in reg["models"].items() if e.get("supports_img2img")]


# ---------------------------------------------------------------------------
# Config management — all reads from <skill>/config/
# ---------------------------------------------------------------------------

def _load_json(path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_credentials():
    return _load_json(_CONFIG_DIR / "credentials.json")


def load_settings():
    return _load_json(_CONFIG_DIR / "settings.json")


def load_prompts():
    return _load_json(_CONFIG_DIR / "prompts.json")


def load_config():
    cfg = load_settings()
    cfg.update(load_credentials())
    return cfg


def save_credential(field, value):
    path = _CONFIG_DIR / "credentials.json"
    data = _load_json(path)
    data[field] = value
    _save_json(path, data)


def save_setting(field, value):
    path = _CONFIG_DIR / "settings.json"
    data = _load_json(path)
    data[field] = value
    _save_json(path, data)


def save_prompt(mode, text):
    path = _CONFIG_DIR / "prompts.json"
    data = _load_json(path)
    data[mode] = text
    _save_json(path, data)


def get_output_dir(override=None):
    if override:
        return override
    settings = load_settings()
    d = settings.get("image_output_dir", "").strip()
    return d if d else str(_CACHE_DIR)


def get_default_model():
    return load_settings().get("default_model", "Doubao-Seedream-4.5")


def get_default_size():
    return load_settings().get("default_size", "2K")


def get_model_config(model):
    """Merged config: models.json defaults <- user overrides from settings.json."""
    entry = get_model_entry(model)
    defaults = dict(entry["defaults"]) if entry else {}
    settings = load_settings()
    user_overrides = settings.get("model_configs", {}).get(model, {})
    defaults.update(user_overrides)
    return defaults


def save_model_config(model, overrides):
    path = _CONFIG_DIR / "settings.json"
    data = _load_json(path)
    if "model_configs" not in data:
        data["model_configs"] = {}
    if model not in data["model_configs"]:
        data["model_configs"][model] = {}
    data["model_configs"][model].update(overrides)
    _save_json(path, data)


def _prompt_keys(mode, lang):
    """Return candidate keys in priority order for a given mode+lang."""
    if lang == "zh":
        return [f"{mode}_zh", mode]
    elif lang == "auto":
        return [f"{mode}_auto", mode]
    return [mode]


def get_model_prompt(model, mode):
    prompts = load_prompts()
    model_specific = prompts.get("model_prompts", {}).get(model, {}).get(mode)
    if model_specific:
        return model_specific
    provider = detect_provider(model)
    if provider:
        pp = prompts.get("provider_prompts", {}).get(provider, {})
        p = pp.get(f"{mode}_auto") or pp.get(mode)
        if p:
            return p
    return prompts.get(mode, "")


def get_system_prompt(mode, lang="auto", model=None):
    """Get system prompt for optimization, respecting language and model overrides.
    Priority: model-specific > provider-specific > lang-specific > global default."""
    prompts = load_prompts()
    if model:
        model_specific = prompts.get("model_prompts", {}).get(model, {}).get(mode)
        if model_specific:
            return model_specific
        provider = detect_provider(model)
        if provider:
            pp = prompts.get("provider_prompts", {}).get(provider, {})
            for key in _prompt_keys(mode, lang):
                if key in pp:
                    return pp[key]
    for key in _prompt_keys(mode, lang):
        if key in prompts:
            return prompts[key]
    return prompts.get(mode, "")


def save_model_prompt(model, mode, text):
    path = _CONFIG_DIR / "prompts.json"
    data = _load_json(path)
    if "model_prompts" not in data:
        data["model_prompts"] = {}
    if model not in data["model_prompts"]:
        data["model_prompts"][model] = {}
    data["model_prompts"][model][mode] = text
    _save_json(path, data)


def get_configurable_params(model):
    entry = get_model_entry(model)
    if not entry:
        return {}
    provider_cfg = get_provider_config(entry["provider"])
    param_names = provider_cfg.get("configurable_params", [])
    current = get_model_config(model)
    return {p: current.get(p) for p in param_names}


def get_model_info(model):
    provider = detect_provider(model)
    config = get_model_config(model)
    params = get_configurable_params(model)
    entry = get_model_entry(model)
    settings = load_settings()
    is_customized = model in settings.get("model_configs", {})
    return {
        "model": model,
        "provider": provider,
        "config": config,
        "configurable_params": list(params.keys()),
        "supports_img2img": entry.get("supports_img2img", False) if entry else False,
        "system_prompt": {
            "text2img": get_model_prompt(model, "text2img"),
            "img2img": get_model_prompt(model, "img2img"),
        },
        "is_customized": is_customized,
    }


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def image_request(body, config, provider_id="volcengine_maas", timeout=180, endpoint=None):
    api_base = get_api_host(provider_id)
    path = endpoint or "/images/generations"
    url = f"{api_base}{path}"
    api_key = config.get("image_api_key", "")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Model-Provider-Id": provider_id,
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"Image API error {e.code}: {error_body[:500]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Image API connection error: {e.reason}") from e


def llm_request(messages, config, model=None, provider=None, timeout=60):
    settings = load_settings()
    model = model or settings.get("optimize_model", "deepseek/deepseek-flash")
    provider = provider or settings.get("optimize_provider", "deepseek")

    url = f"{MIFY_MODEL_API}/chat/completions"
    api_key = config.get("image_api_key", "")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Model-Provider-Id": provider,
        "Content-Type": "application/json",
    }
    body = {"model": model, "messages": messages}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"LLM API error {e.code}: {error_body[:500]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM API connection error: {e.reason}") from e


# ---------------------------------------------------------------------------
# Size validation — per provider
# ---------------------------------------------------------------------------

_SIZE_WXH = re.compile(r'^(\d+)[xX](\d+)$')
_SIZE_STAR = re.compile(r'^(\d+)\*(\d+)$')
_SIZE_EITHER = re.compile(r'^(\d+)[xX*](\d+)$')

_VOLC_MIN_PX = 3686400
_VOLC_MAX_PX = 16777216
_VOLC_PRESETS_ALL = {"2K", "4K"}
_VOLC_PRESETS_5LITE = {"2K", "3K", "4K"}
# Doubao-Seedream-5.0-pro: 预设仅 1K/2K (官方文档), 自定义尺寸像素范围更窄
# 官方文档 max=4624220, API 实测 max=6624220 (2560*2560=6553600 可用), 取 API 实测值
_VOLC_PRESETS_5PRO = {"1K", "2K"}
_VOLC_MIN_PX_5PRO = 921600
_VOLC_MAX_PX_5PRO = 6624220

_TONGYI_MIN_AREA = 262144
_TONGYI_MAX_AREA = 4194304
_TONGYI_MAX_AREA_3 = 6553600  # qwen-image-3.0/3.0-pro: Mify tested range
_WAN_MIN_AREA = 589824
_WAN_MAX_AREA = 2073600

_VERTEX_RATIOS_FLASH = {
    "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
_VERTEX_RATIOS_PRO = {
    "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9"}
_VERTEX_ASPECT_RATIOS = _VERTEX_RATIOS_FLASH | _VERTEX_RATIOS_PRO
_VERTEX_IMAGE_SIZES_FLASH = {"1K"}
_VERTEX_IMAGE_SIZES_PRO = {"1K", "2K", "4K"}


def _validate_size_volcengine(size_str, model=None):
    if model == "Doubao-Seedream-5.0-pro":
        presets = _VOLC_PRESETS_5PRO
        min_px, max_px = _VOLC_MIN_PX_5PRO, _VOLC_MAX_PX_5PRO
    elif model == "Doubao-Seedream-5.0-lite":
        presets = _VOLC_PRESETS_5LITE
        min_px, max_px = _VOLC_MIN_PX, _VOLC_MAX_PX
    else:
        presets = _VOLC_PRESETS_ALL
        min_px, max_px = _VOLC_MIN_PX, _VOLC_MAX_PX
    if size_str.upper() in presets:
        return size_str.upper()
    m = _SIZE_WXH.match(size_str)
    if not m:
        raise ValueError(
            f"Invalid volcengine size: {size_str}. "
            f"Use {', '.join(sorted(presets))} or 'WxH' (e.g., 3840x2160)")
    w, h = int(m.group(1)), int(m.group(2))
    total = w * h
    ratio = w / h
    if total < min_px or total > max_px:
        raise ValueError(f"Pixel count {total} out of range [{min_px}, {max_px}]")
    if ratio < 1/16 or ratio > 16:
        raise ValueError(f"Aspect ratio {ratio:.2f} out of range [1/16, 16]")
    return f"{w}x{h}"


def _validate_size_tongyi(size_str, model=None):
    m = _SIZE_EITHER.match(size_str)
    if not m:
        raise ValueError(f"Invalid tongyi size: {size_str}. Use 'W*H' format (e.g., 2048*2048)")
    w, h = int(m.group(1)), int(m.group(2))
    canonical = f"{w}*{h}"

    if model in ("qwen-image-2.0", "qwen-image-2.0-pro"):
        area = w * h
        if area < _TONGYI_MIN_AREA or area > _TONGYI_MAX_AREA:
            raise ValueError(
                f"{model} total pixels must be {_TONGYI_MIN_AREA}~{_TONGYI_MAX_AREA}, "
                f"got {canonical} ({area} px)")
    elif model in ("qwen-image-3.0", "qwen-image-3.0-pro"):
        area = w * h
        if area < _TONGYI_MIN_AREA or area > _TONGYI_MAX_AREA_3:
            raise ValueError(
                f"{model} total pixels must be {_TONGYI_MIN_AREA}~{_TONGYI_MAX_AREA_3}, "
                f"got {canonical} ({area} px)")
    elif model == "wan2.6-t2i":
        area = w * h
        if area < _WAN_MIN_AREA or area > _WAN_MAX_AREA:
            raise ValueError(
                f"wan2.6-t2i total pixels must be {_WAN_MIN_AREA}~{_WAN_MAX_AREA}, "
                f"got {canonical} ({area} px)")
    elif model == "z-image-turbo":
        if not (512 <= w <= 2048 and 512 <= h <= 2048):
            raise ValueError(f"z-image-turbo size must be 512*512 ~ 2048*2048 per dimension, got {canonical}")
    return canonical


def _validate_size_vertex_ai(size_str, model=None):
    if model == "gemini-2.5-flash-image":
        valid = _VERTEX_RATIOS_FLASH
    elif model == "gemini-3-pro-image":
        valid = _VERTEX_RATIOS_PRO
    elif model == "gemini-3.1-flash-image":
        valid = _VERTEX_RATIOS_FLASH
    else:
        valid = _VERTEX_ASPECT_RATIOS
    if size_str in valid:
        return size_str
    raise ValueError(
        f"Invalid vertex_ai aspect ratio: {size_str}. Use one of: {', '.join(sorted(valid))}"
    )


# ---------------------------------------------------------------------------
# Size fitting — auto-size for img2img (map arbitrary WxH to valid provider size)
# ---------------------------------------------------------------------------

def _round_even(n):
    return max(2, int(n) // 2 * 2)


def _round_16(n):
    return max(16, round(n / 16) * 16)


def _floor_16(n):
    return max(16, int(n) // 16 * 16)


def _max_size_within_area(w, h, max_area):
    scale = math.sqrt(max_area / (w * h))
    base_w = _floor_16(w * scale)
    base_h = _floor_16(h * scale)
    best = None
    for dw in (0, 16):
        for dh in (0, 16):
            cw, ch = base_w + dw, base_h + dh
            if cw * ch <= max_area:
                if best is None or cw * ch > best[0] * best[1]:
                    best = (cw, ch)
    return best or (base_w, base_h)


def _scale_up_to_min(w, h, min_area, max_area, max_edge=None, max_ratio=None, align=2):
    """Scale up (w, h) to meet min_area while preserving aspect ratio.
    Returns (new_w, new_h) or None if constraints can't be satisfied."""
    if w <= 0 or h <= 0:
        return None
    ratio = w / h
    if max_ratio:
        if ratio > max_ratio:
            ratio = max_ratio
        elif ratio < 1 / max_ratio:
            ratio = 1 / max_ratio

    scale = math.sqrt(min_area / (w * h))
    nw = w * scale
    nh = h * scale

    if align == 16:
        nw = max(16, _round_16(nw))
        nh = max(16, _round_16(nh))
    else:
        nw = max(2, _round_even(nw))
        nh = max(2, _round_even(nh))

    if max_edge and max(nw, nh) > max_edge:
        return None
    if nw * nh > max_area:
        return None
    if nw * nh >= min_area:
        return (nw, nh)
    for dw in (0, align):
        for dh in (0, align):
            cw, ch = nw + dw, nh + dh
            if cw * ch >= min_area and cw * ch <= max_area:
                if not max_edge or max(cw, ch) <= max_edge:
                    return (cw, ch)
    return None


# Cross-format conversion tables (ratio → recommended pixel sizes)
_RATIO_RE = re.compile(r'^(\d+):(\d+)$')

_RATIO_TO_VOLC = {
    "1:1": "2048x2048", "16:9": "2560x1440", "9:16": "1440x2560",
    "4:3": "2240x1680", "3:4": "1680x2240", "3:2": "2352x1568",
    "2:3": "1568x2352", "5:4": "2160x1728", "4:5": "1728x2160",
    "21:9": "3360x1440",
}
_RATIO_TO_TONGYI = {
    "1:1": "1024*1024", "16:9": "1280*720", "9:16": "720*1280",
    "4:3": "1280*960", "3:4": "960*1280", "3:2": "1152*768",
    "2:3": "768*1152", "5:4": "1152*928", "4:5": "928*1152",
    "21:9": "1344*576",
}


def _parse_wh(size_str):
    """Extract (w, h) from 'WxH', 'W*H', or ratio 'W:H' formats. Returns (None, None) on failure."""
    m = _SIZE_EITHER.match(size_str)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _normalize_size(size_str, provider_id, model=None):
    """Convert user size input to provider's native format.
    E.g. '1920x1080' → '16:9' for vertex_ai, '16:9' → '2560x1440' for volcengine."""
    if not size_str:
        return size_str

    # vertex_ai: convert pixel values to aspect ratio
    if provider_id == "vertex_ai":
        w, h = _parse_wh(size_str)
        if w and h:
            fit = _fit_size_vertex_ai(w, h, model)
            return fit["size"]

    # volcengine: convert ratio to pixel preset
    if provider_id == "volcengine_maas" and _RATIO_RE.match(size_str):
        return _RATIO_TO_VOLC.get(size_str, size_str)

    # tongyi: convert ratio to pixel preset, also accept WxH → W*H
    if provider_id == "tongyi":
        if _RATIO_RE.match(size_str):
            return _RATIO_TO_TONGYI.get(size_str, size_str)
        m = _SIZE_WXH.match(size_str)
        if m:
            return f"{m.group(1)}*{m.group(2)}"

    # azure_openai: convert ratio to WxH, accept W*H → WxH
    if provider_id == "azure_openai":
        if _RATIO_RE.match(size_str):
            return _RATIO_TO_AZURE.get(size_str, size_str)
        m = _SIZE_STAR.match(size_str)
        if m:
            return f"{m.group(1)}x{m.group(2)}"

    return size_str


def _fit_size_volcengine(w, h, model=None):
    original = (w, h)
    ratio = w / h
    resized = False
    reasons = []
    warning = None
    strategy = "direct"
    pad_to = None
    crop_to = None

    # 5.0-pro 像素范围更窄 (921600~6624220), 其他模型 3686400~16777216
    if model == "Doubao-Seedream-5.0-pro":
        min_px, max_px = _VOLC_MIN_PX_5PRO, _VOLC_MAX_PX_5PRO
    else:
        min_px, max_px = _VOLC_MIN_PX, _VOLC_MAX_PX

    # Step 1: clamp extreme aspect ratio
    if ratio > 16:
        h = max(_round_even(w / 16), 2)
        resized = True
        reasons.append(f"宽高比 {original[0]}:{original[1]}={ratio:.1f} 超出16:1, 已调整")
        strategy = "scale_down"
    elif ratio < 1 / 16:
        w = max(_round_even(h / 16), 2)
        resized = True
        reasons.append(f"宽高比 {original[0]}:{original[1]}=1:{1/ratio:.1f} 超出1:16, 已调整")
        strategy = "scale_down"

    # Step 2: handle pixel count
    px = w * h
    if px < min_px:
        scaled = _scale_up_to_min(w, h, min_px, max_px, max_ratio=16, align=2)
        if scaled:
            w, h = scaled
            resized = True
            strategy = "scale_up"
            reasons.append(f"像素 {px:,} < {min_px:,}, 保持宽高比放大到 {w}x{h}")
        else:
            resized = True
            strategy = "use_default"
            reasons.append(f"像素 {px:,} < {min_px:,}, 使用模型默认输出尺寸")
    elif px > max_px:
        scale = math.sqrt(max_px / px)
        w = _round_even(w * scale)
        h = _round_even(h * scale)
        resized = True
        strategy = "scale_down"
        reasons.append(f"像素 {px:,} > {max_px:,}, 等比缩小到 {w}x{h}")

    if strategy == "use_default":
        return {
            "size": None, "original": original, "fitted": None,
            "pad_to": None, "crop_to": None, "roi": None,
            "resized": resized, "strategy": strategy,
            "reason": "; ".join(reasons) if reasons else None,
            "warning": None,
        }

    # Step 3: extreme ratio warning
    final_ratio = w / h if h > 0 else 1
    if final_ratio > 4 or final_ratio < 1 / 4:
        warning = f"宽高比 {w}:{h} ≈ {final_ratio:.1f}:1 较极端，生成质量可能受影响"
    if pad_to and crop_to:
        pad_area = pad_to[0] * pad_to[1] - crop_to[0] * crop_to[1]
        total_area = pad_to[0] * pad_to[1]
        if pad_area > total_area * 0.5:
            warning = (warning + "; " if warning else "") + \
                f"padding面积占比 {pad_area/total_area*100:.0f}%>50%, 画面质量可能受影响"

    roi = original if pad_to else None

    return {
        "size": f"{w}x{h}", "original": original, "fitted": (w, h),
        "pad_to": pad_to, "crop_to": crop_to, "roi": roi,
        "resized": resized, "strategy": strategy,
        "reason": "; ".join(reasons) if reasons else None,
        "warning": warning,
    }


_TONGYI_ROI_MIN_DIM = 1024

def _fit_size_tongyi(w, h, model=None):
    original = (w, h)
    area = w * h
    resized = False
    reasons = []
    warning = None
    strategy = "direct"
    pad_to = None
    crop_to = None

    # qwen-image-3.0/3.0-pro 按 Mify 实测总像素上限 6553600 处理；
    # max_edge 仅用于小尺寸输入放大，避免放大结果超过安全边界。
    is_3x = model in ("qwen-image-3.0", "qwen-image-3.0-pro")
    max_area = _TONGYI_MAX_AREA_3 if is_3x else _TONGYI_MAX_AREA
    max_edge = 2560 if is_3x else 2048

    if max(w, h) < _TONGYI_ROI_MIN_DIM:
        min_target = _TONGYI_ROI_MIN_DIM * _TONGYI_ROI_MIN_DIM
        scaled = _scale_up_to_min(w, h, min_target, max_area, max_edge=max_edge, align=16)
        if scaled:
            resized = True
            strategy = "scale_up"
            reasons.append(
                f"输出尺寸 {w}*{h} 短边<{_TONGYI_ROI_MIN_DIM}, "
                f"保持宽高比放大到 {scaled[0]}*{scaled[1]}")
            w, h = scaled
        else:
            resized = True
            strategy = "use_default"
            reasons.append(
                f"输出尺寸 {w}*{h} 短边<{_TONGYI_ROI_MIN_DIM}, "
                f"通义模型小尺寸输出存在 ROI 裁切, 使用模型默认输出尺寸")
            return {
                "size": None, "original": original, "fitted": None,
                "pad_to": None, "crop_to": None, "roi": None,
                "resized": resized, "strategy": strategy,
                "reason": "; ".join(reasons) if reasons else None,
                "warning": None,
            }

    if strategy != "scale_up" and area < _TONGYI_MIN_AREA:
        scaled = _scale_up_to_min(w, h, _TONGYI_MIN_AREA, max_area, max_edge=max_edge, align=16)
        if scaled:
            resized = True
            strategy = "scale_up"
            w, h = scaled
            reasons.append(f"总像素 {area:,} < {_TONGYI_MIN_AREA:,}, 保持宽高比放大到 {w}*{h}")
        else:
            resized = True
            strategy = "use_default"
            reasons.append(f"总像素 {area:,} < {_TONGYI_MIN_AREA:,}, 使用模型默认输出尺寸")
            return {
                "size": None, "original": original, "fitted": None,
                "pad_to": None, "crop_to": None, "roi": None,
                "resized": resized, "strategy": strategy,
                "reason": "; ".join(reasons) if reasons else None,
                "warning": None,
            }
    elif area > max_area:
        w, h = _max_size_within_area(w, h, max_area)
        resized = True
        strategy = "scale_down"
        reasons.append(f"总像素 {area:,} > {max_area:,}, 等比缩小到 {w}*{h}")
    else:
        w = _round_16(w)
        h = _round_16(h)
        if (w, h) != original:
            resized = True
            reasons.append(f"对齐到16倍数: {original[0]}*{original[1]} → {w}*{h}")

    final_ratio = w / h if h > 0 else 1
    if final_ratio > 4 or final_ratio < 1 / 4:
        warning = f"宽高比 {w}:{h} ≈ {final_ratio:.1f}:1 较极端，生成质量可能受影响"
    if pad_to and crop_to:
        pad_area = pad_to[0] * pad_to[1] - crop_to[0] * crop_to[1]
        total_area = pad_to[0] * pad_to[1]
        if pad_area > total_area * 0.5:
            warning = (warning + "; " if warning else "") + \
                f"padding面积占比 {pad_area/total_area*100:.0f}%>50%, 画面质量可能受影响"

    roi = original if pad_to else None

    return {
        "size": f"{w}*{h}", "original": original, "fitted": (w, h),
        "pad_to": pad_to, "crop_to": crop_to, "roi": roi,
        "resized": resized, "strategy": strategy,
        "reason": "; ".join(reasons) if reasons else None,
        "warning": warning,
    }


_VERTEX_RATIO_MAP = {
    "1:1": 1.0,
    "2:3": 2 / 3,
    "3:2": 3 / 2,
    "3:4": 3 / 4,
    "4:3": 4 / 3,
    "4:5": 4 / 5,
    "5:4": 5 / 4,
    "9:16": 9 / 16,
    "16:9": 16 / 9,
    "21:9": 21 / 9,
}

# Gemini exact output pixels per ratio+tier (from official docs, all 16-multiples)
# 2K = 1K * 2, 4K = 1K * 4
_GEMINI_OUTPUT_PX_PRO = {
    "1:1":  {"1K": (1024, 1024), "2K": (2048, 2048), "4K": (4096, 4096)},
    "2:3":  {"1K": (848, 1264),  "2K": (1696, 2528), "4K": (3392, 5056)},
    "3:2":  {"1K": (1264, 848),  "2K": (2528, 1696), "4K": (5056, 3392)},
    "3:4":  {"1K": (896, 1200),  "2K": (1792, 2400), "4K": (3584, 4800)},
    "4:3":  {"1K": (1200, 896),  "2K": (2400, 1792), "4K": (4800, 3584)},
    "4:5":  {"1K": (928, 1152),  "2K": (1856, 2304), "4K": (3712, 4608)},
    "5:4":  {"1K": (1152, 928),  "2K": (2304, 1856), "4K": (4608, 3712)},
    "9:16": {"1K": (768, 1376),  "2K": (1536, 2752), "4K": (3072, 5504)},
    "16:9": {"1K": (1376, 768),  "2K": (2752, 1536), "4K": (5504, 3072)},
}
_GEMINI_OUTPUT_PX_FLASH = {
    "1:1":  (1024, 1024), "2:3":  (832, 1248),  "3:2":  (1248, 832),
    "3:4":  (864, 1184),  "4:3":  (1184, 864),  "4:5":  (896, 1152),
    "5:4":  (1152, 896),  "9:16": (768, 1344),  "16:9": (1344, 768),
    "21:9": (1536, 672),
}

# gemini-3.1-flash-image: 10 ratios (incl 21:9) × 1K/2K/4K tiers.
# The 9 ratios shared with PRO have identical output pixels to _GEMINI_OUTPUT_PX_PRO
# (2K = 1K*2, 4K = 1K*4); 21:9 is 3.1-flash specific (1584x672 @1K, differs from
# 2.5-flash's 1536x672). Measured via API probe.
_GEMINI_OUTPUT_PX_31FLASH = dict(_GEMINI_OUTPUT_PX_PRO)
_GEMINI_OUTPUT_PX_31FLASH["21:9"] = {
    "1K": (1584, 672), "2K": (3168, 1344), "4K": (6336, 2688)}


def _fit_size_vertex_ai(w, h, model=None):
    original = (w, h)
    ratio = w / h

    if model == "gemini-3-pro-image":
        candidates = _VERTEX_RATIOS_PRO
    else:
        candidates = _VERTEX_RATIOS_FLASH

    best, best_dist = None, float("inf")
    for label in candidates:
        d = abs(math.log(ratio) - math.log(_VERTEX_RATIO_MAP[label]))
        if d < best_dist:
            best_dist, best = d, label

    resized = best_dist > 0.01
    reasons = []
    warning = None
    suggest_model = None
    strategy = "pad_crop"

    if resized:
        pct = (math.exp(best_dist) - 1) * 100
        reasons.append(f"宽高比 {original[0]}:{original[1]} ≈ {ratio:.2f}, 匹配 {best}")
        if pct > 20:
            warning = f"宽高比偏差 {pct:.0f}%, 画面构图可能有明显变化"
        if model == "gemini-3-pro-image" and pct > 15:
            for label in _VERTEX_RATIOS_FLASH - _VERTEX_RATIOS_PRO:
                d = abs(math.log(ratio) - math.log(_VERTEX_RATIO_MAP[label]))
                if d < best_dist * 0.5:
                    suggest_model = f"gemini-2.5-flash-image 支持 {label}, 更接近原始比例"

    # Select imageSize tier
    if model == "gemini-2.5-flash-image":
        gem_w, gem_h = _GEMINI_OUTPUT_PX_FLASH[best]
        image_size = "1K"
    elif model == "gemini-3.1-flash-image":
        image_size = None
        gem_w, gem_h = 0, 0
        for tier in ("1K", "2K", "4K"):
            tw, th = _GEMINI_OUTPUT_PX_31FLASH[best][tier]
            if tw >= w and th >= h:
                gem_w, gem_h = tw, th
                image_size = tier
                break
        if image_size is None:
            gem_w, gem_h = _GEMINI_OUTPUT_PX_31FLASH[best]["4K"]
            image_size = "4K"
    else:
        image_size = None
        gem_w, gem_h = 0, 0
        for tier in ("1K", "2K", "4K"):
            tw, th = _GEMINI_OUTPUT_PX_PRO[best][tier]
            if tw >= w and th >= h:
                gem_w, gem_h = tw, th
                image_size = tier
                break
        if image_size is None:
            gem_w, gem_h = _GEMINI_OUTPUT_PX_PRO[best]["4K"]
            image_size = "4K"

    if gem_w < w or gem_h < h:
        strategy = "scale_down"
        scale = min(gem_w / w, gem_h / h)
        reasons.append(
            f"原图 {w}x{h} 超出Gemini {image_size}最大输出 {gem_w}x{gem_h}, "
            f"缩小到 {_round_even(w*scale)}x{_round_even(h*scale)}")
        return {
            "size": best, "original": original, "fitted": (gem_w, gem_h),
            "pad_to": None, "crop_to": None, "roi": None,
            "resized": True, "strategy": strategy,
            "reason": "; ".join(reasons), "warning": warning,
            "imageSize": image_size, "suggest_model": suggest_model,
        }

    # Minimal padding: match actual Gemini output ratio, then resize to output size
    actual_ratio = gem_w / gem_h
    if ratio > actual_ratio:
        pad_h = round(w / actual_ratio)
        pad_to = (w, max(pad_h, h))
    elif ratio < actual_ratio:
        pad_w = round(h * actual_ratio)
        pad_to = (max(pad_w, w), h)
    else:
        pad_to = (w, h)

    # ROI: where original content maps to in the Gemini output space
    scale_to_output = gem_w / pad_to[0]
    roi_w = round(w * scale_to_output)
    roi_h = round(h * scale_to_output)
    roi = (roi_w, roi_h)

    needs_padding = pad_to != (w, h)
    crop_to = original
    reasons.append(
        f"{'minimal pad ' + str(w) + 'x' + str(h) + '->' + str(pad_to[0]) + 'x' + str(pad_to[1]) + ', ' if needs_padding else ''}"
        f"resize到{gem_w}x{gem_h} ({best} {image_size}), "
        f"ROI (0,0)-({roi_w},{roi_h}), crop回{w}x{h}")

    if needs_padding and resized:
        pad_pct = (pad_to[0] * pad_to[1] - w * h) / (pad_to[0] * pad_to[1]) * 100
        if pad_pct > 50:
            warning = (warning + "; " if warning else "") + \
                f"padding面积占比 {pad_pct:.0f}%>50%"

    return {
        "size": best, "original": original, "fitted": (gem_w, gem_h),
        "pad_to": pad_to if needs_padding else None,
        "resize_to_input": (gem_w, gem_h),
        "roi": roi,
        "crop_to": crop_to,
        "resized": resized or needs_padding, "strategy": strategy,
        "reason": "; ".join(reasons) if reasons else None,
        "warning": warning,
        "imageSize": image_size, "suggest_model": suggest_model,
    }


# ---------------------------------------------------------------------------
# Request body builders — per provider
# ---------------------------------------------------------------------------

def _build_request_volcengine(prompt, model, model_config, image_ref=None):
    body = {
        "model": model,
        "prompt": prompt,
        "size": model_config.get("size", "2K"),
        "response_format": "url",
        "watermark": model_config.get("watermark", False),
    }
    if image_ref:
        body["image"] = image_ref
    return body


def _build_request_tongyi(prompt, model, model_config, image_ref=None):
    content = []
    if image_ref:
        refs = image_ref if isinstance(image_ref, list) else [image_ref]
        for img in refs:
            content.append({"image": img})
    content.append({"text": prompt})

    parameters = {"size": model_config.get("size", "1328*1328")}

    neg = model_config.get("negative_prompt", "")
    if neg:
        parameters["negative_prompt"] = neg

    if "prompt_extend" in model_config:
        parameters["prompt_extend"] = model_config["prompt_extend"]

    if model_config.get("watermark", False):
        parameters["watermark"] = True

    n = model_config.get("n", 1)
    if n and n > 1:
        parameters["n"] = n

    return {
        "model": model,
        "input": {
            "messages": [
                {"role": "user", "content": content}
            ]
        },
        "parameters": parameters,
    }


def _build_request_vertex_ai(prompt, model, model_config, image_ref=None):
    parts = []
    if image_ref:
        refs = image_ref if isinstance(image_ref, list) else [image_ref]
        for img in refs:
            parts.append({"inline_data": {"mime_type": "image/png", "data": img}})
    parts.append({"text": prompt})

    image_config = {}
    aspect_ratio = model_config.get("size", "1:1")
    if aspect_ratio:
        image_config["aspectRatio"] = aspect_ratio
    image_size = model_config.get("imageSize", "2K")
    if image_size:
        image_config["imageSize"] = image_size

    return {
        "model": model,
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": image_config,
        },
    }


# ---------------------------------------------------------------------------
# Response parsers — per provider
# ---------------------------------------------------------------------------

def _parse_response_volcengine(response):
    data = response.get("data", [])
    if data and data[0].get("url"):
        return {"url": data[0]["url"], "base64_data": None, "mime_type": None}
    raise RuntimeError(f"volcengine returned no image: {json.dumps(response)[:300]}")


def _parse_response_tongyi(response):
    data = response.get("data", [])
    if data and data[0].get("url"):
        return {"url": data[0]["url"], "base64_data": None, "mime_type": None}
    output = response.get("output", {})
    choices = output.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", [])
        for item in content:
            if isinstance(item, dict) and item.get("image"):
                return {"url": item["image"], "base64_data": None, "mime_type": None}
    results = output.get("results", [])
    if results and results[0].get("url"):
        return {"url": results[0]["url"], "base64_data": None, "mime_type": None}
    raise RuntimeError(f"tongyi returned no image: {json.dumps(response)[:300]}")


def _parse_response_vertex_ai(response):
    candidates = response.get("candidates", [])
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return {
                    "url": None,
                    "base64_data": inline["data"],
                    "mime_type": inline.get("mimeType") or inline.get("mime_type", "image/png"),
                }
    data = response.get("data", [])
    if data and data[0].get("url"):
        return {"url": data[0]["url"], "base64_data": None, "mime_type": None}
    raise RuntimeError(f"vertex_ai returned no image: {json.dumps(response)[:300]}")


# ---------------------------------------------------------------------------
# azure_openai (GPT Image 2/2.5) — size validation, fitting, request/response
# ---------------------------------------------------------------------------

_AZURE_MIN_PX = 655360
_AZURE_MAX_PX = 8294400
_AZURE_MAX_EDGE = 3840
_AZURE_MAX_RATIO = 3.0

_RATIO_TO_AZURE = {
    "1:1": "1024x1024", "16:9": "1920x1088", "9:16": "1088x1920",
    "4:3": "1376x1024", "3:4": "1024x1376", "3:2": "1536x1024",
    "2:3": "1024x1536", "21:9": "2688x896",
}


def _validate_size_azure_openai(size_str, model=None):
    m = _SIZE_WXH.match(size_str)
    if not m:
        raise ValueError(
            f"Invalid azure_openai size: {size_str}. "
            f"Use 'WxH' format (e.g., 1536x1024). Both W and H must be multiples of 16, "
            f"max edge 3840, ratio ≤ 3:1, total pixels 655,360~8,294,400.")
    w, h = int(m.group(1)), int(m.group(2))
    if w % 16 != 0 or h % 16 != 0:
        raise ValueError(f"Size {size_str}: W and H must both be multiples of 16")
    if max(w, h) > _AZURE_MAX_EDGE:
        raise ValueError(f"Size {size_str}: longest edge {max(w, h)} > {_AZURE_MAX_EDGE}")
    ratio = max(w, h) / min(w, h)
    if ratio > _AZURE_MAX_RATIO:
        raise ValueError(f"Size {size_str}: aspect ratio {ratio:.2f} > {_AZURE_MAX_RATIO}")
    total = w * h
    if total < _AZURE_MIN_PX or total > _AZURE_MAX_PX:
        raise ValueError(
            f"Size {size_str}: pixel count {total:,} out of range "
            f"[{_AZURE_MIN_PX:,}, {_AZURE_MAX_PX:,}]")
    return f"{w}x{h}"


def _fit_size_azure_openai(w, h, model=None):
    original = (w, h)
    resized = False
    reasons = []
    warning = None
    strategy = "direct"

    ratio = max(w, h) / min(w, h) if min(w, h) > 0 else 1
    if ratio > _AZURE_MAX_RATIO:
        if w > h:
            h = max(16, _floor_16(w / _AZURE_MAX_RATIO))
        else:
            w = max(16, _floor_16(h / _AZURE_MAX_RATIO))
        resized = True
        strategy = "scale_down"
        reasons.append(f"宽高比 {original[0]}:{original[1]} 超出 {_AZURE_MAX_RATIO}:1, 已调整")

    if max(w, h) > _AZURE_MAX_EDGE:
        scale = _AZURE_MAX_EDGE / max(w, h)
        w = _floor_16(w * scale)
        h = _floor_16(h * scale)
        resized = True
        strategy = "scale_down"
        reasons.append(f"最长边超出 {_AZURE_MAX_EDGE}, 等比缩小")

    px = w * h
    if px < _AZURE_MIN_PX:
        scaled = _scale_up_to_min(w, h, _AZURE_MIN_PX, _AZURE_MAX_PX,
                                   _AZURE_MAX_EDGE, _AZURE_MAX_RATIO, align=16)
        if scaled:
            w, h = scaled
            resized = True
            strategy = "scale_up"
            reasons.append(f"像素 {px:,} < {_AZURE_MIN_PX:,}, 保持宽高比放大到 {w}x{h}")
        else:
            resized = True
            strategy = "use_default"
            reasons.append(f"像素 {px:,} < {_AZURE_MIN_PX:,}, 使用模型默认输出尺寸")
            return {
                "size": None, "original": original, "fitted": None,
                "pad_to": None, "crop_to": None, "roi": None,
                "resized": resized, "strategy": strategy,
                "reason": "; ".join(reasons), "warning": None,
            }

    if px > _AZURE_MAX_PX:
        w, h = _max_size_within_area(w, h, _AZURE_MAX_PX)
        if max(w, h) > _AZURE_MAX_EDGE:
            scale = _AZURE_MAX_EDGE / max(w, h)
            w = _floor_16(w * scale)
            h = _floor_16(h * scale)
        resized = True
        strategy = "scale_down"
        reasons.append(f"像素超出 {_AZURE_MAX_PX:,}, 等比缩小到 {w}x{h}")
    else:
        nw = _round_16(w)
        nh = _round_16(h)
        if (nw, nh) != (w, h):
            w, h = nw, nh
            resized = True
            reasons.append(f"对齐到16倍数: {original[0]}x{original[1]} → {w}x{h}")

    final_ratio = max(w, h) / min(w, h) if min(w, h) > 0 else 1
    if final_ratio > 2.5:
        warning = f"宽高比 {w}:{h} ≈ {final_ratio:.1f}:1 较极端，生成质量可能受影响"

    return {
        "size": f"{w}x{h}", "original": original, "fitted": (w, h),
        "pad_to": None, "crop_to": None, "roi": None,
        "resized": resized, "strategy": strategy,
        "reason": "; ".join(reasons) if reasons else None,
        "warning": warning,
    }


def _build_request_azure_openai(prompt, model, model_config, image_ref=None):
    body = {
        "model": model,
        "prompt": prompt,
        "size": model_config.get("size", "1536x1024"),
        "quality": model_config.get("quality", "auto"),
        "n": model_config.get("n", 1),
    }
    fmt = model_config.get("output_format")
    if fmt:
        body["output_format"] = fmt
    compression = model_config.get("output_compression")
    if compression is not None and fmt == "jpeg":
        body["output_compression"] = compression
    bg = model_config.get("background")
    if bg:
        body["background"] = bg
    if image_ref:
        # Multi-image: use the plural `image_urls` array (Mify /images/edits
        # supports multi-image fusion via image_urls). Single image keeps the
        # singular `image_url` key.
        if isinstance(image_ref, list):
            body["image_urls"] = image_ref
        else:
            body["image_url"] = image_ref
        fidelity = model_config.get("input_fidelity")
        if fidelity:
            body["input_fidelity"] = fidelity
        mask = model_config.get("_mask_encoded")
        if mask:
            body["mask"] = mask
    return body


def _parse_response_azure_openai(response):
    data = response.get("data", [])
    if data:
        item = data[0]
        if item.get("b64_json"):
            fmt = response.get("output_format", "png")
            mime = "image/jpeg" if fmt == "jpeg" else "image/png"
            return {"url": None, "base64_data": item["b64_json"], "mime_type": mime}
        if item.get("url"):
            return {"url": item["url"], "base64_data": None, "mime_type": None}
    raise RuntimeError(f"azure_openai returned no image: {json.dumps(response)[:300]}")


# ---------------------------------------------------------------------------
# Provider handler registry — each provider's complete knowledge in one place
# ---------------------------------------------------------------------------

_PROVIDER_HANDLERS = {
    "volcengine_maas": {
        "build_request": _build_request_volcengine,
        "parse_response": _parse_response_volcengine,
        "validate_size": _validate_size_volcengine,
        "fit_size": _fit_size_volcengine,
        "encode_image": lambda fp: local_image_to_base64(fp),
        "accepts_url": True,
    },
    "tongyi": {
        "build_request": _build_request_tongyi,
        "parse_response": _parse_response_tongyi,
        "validate_size": _validate_size_tongyi,
        "fit_size": _fit_size_tongyi,
        "encode_image": lambda fp: local_image_to_base64(fp),
        "accepts_url": True,
        "timeout": 300,
    },
    "vertex_ai": {
        "build_request": _build_request_vertex_ai,
        "parse_response": _parse_response_vertex_ai,
        "validate_size": _validate_size_vertex_ai,
        "fit_size": _fit_size_vertex_ai,
        "encode_image": lambda fp: local_image_to_raw_base64(fp),
        "accepts_url": False,
    },
    "azure_openai": {
        "build_request": _build_request_azure_openai,
        "parse_response": _parse_response_azure_openai,
        "validate_size": _validate_size_azure_openai,
        "fit_size": _fit_size_azure_openai,
        "encode_image": lambda fp: local_image_to_base64(fp),
        "accepts_url": True,
        "img2img_endpoint": "/images/edits",
        "timeout": 600,
    },
}


def get_provider_handler(provider_id):
    handler = _PROVIDER_HANDLERS.get(provider_id)
    if not handler:
        raise ValueError(f"Unknown provider: {provider_id}")
    return handler


def build_request_body(provider_id, prompt, model, model_config, image_ref=None):
    handler = get_provider_handler(provider_id)
    return handler["build_request"](prompt, model, model_config, image_ref)


def parse_image_response(response, provider_id):
    handler = get_provider_handler(provider_id)
    return handler["parse_response"](response)


# ---------------------------------------------------------------------------
# Image dimension reading — stdlib only (struct-based header parsing)
# ---------------------------------------------------------------------------

def _parse_png_dimensions(buf):
    if len(buf) < 24:
        return None
    w, h = struct.unpack('>II', buf[16:24])
    return (w, h)


def _parse_jpeg_dimensions(buf):
    if len(buf) < 4 or buf[0:2] != b'\xff\xd8':
        return None
    pos = 2
    while pos < len(buf) - 9:
        if buf[pos] != 0xff:
            return None
        marker = buf[pos + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h = struct.unpack('>H', buf[pos + 5:pos + 7])[0]
            w = struct.unpack('>H', buf[pos + 7:pos + 9])[0]
            return (w, h)
        if marker == 0xD9:
            return None
        if marker in range(0xD0, 0xD8) or marker == 0x01:
            pos += 2
            continue
        if pos + 4 > len(buf):
            return None
        length = struct.unpack('>H', buf[pos + 2:pos + 4])[0]
        pos += 2 + length
    return None


def _parse_webp_dimensions(buf):
    if len(buf) < 16 or buf[0:4] != b'RIFF' or buf[8:12] != b'WEBP':
        return None
    chunk_id = buf[12:16]
    if chunk_id == b'VP8 ' and len(buf) >= 30:
        w = struct.unpack('<H', buf[26:28])[0] & 0x3FFF
        h = struct.unpack('<H', buf[28:30])[0] & 0x3FFF
        return (w, h)
    if chunk_id == b'VP8L' and len(buf) >= 25:
        bits = struct.unpack('<I', buf[21:25])[0]
        w = (bits & 0x3FFF) + 1
        h = ((bits >> 14) & 0x3FFF) + 1
        return (w, h)
    if chunk_id == b'VP8X' and len(buf) >= 30:
        w = (buf[24] | buf[25] << 8 | buf[26] << 16) + 1
        h = (buf[27] | buf[28] << 8 | buf[29] << 16) + 1
        return (w, h)
    return None


def _read_image_header(source, max_bytes=262144):
    """Read first bytes from a local file or URL. Returns bytes or None."""
    if source.startswith(("http://", "https://")):
        try:
            req = urllib.request.Request(
                source, headers={"Range": f"bytes=0-{max_bytes - 1}"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read(max_bytes)
        except Exception:
            return None
    path = Path(source)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            return f.read(max_bytes)
    except Exception:
        return None


def get_image_dimensions(source):
    """Read image dimensions from a local file or URL.
    Returns (width, height) or None if not determinable."""
    buf = _read_image_header(source)
    if not buf or len(buf) < 16:
        return None
    if buf[0:8] == b'\x89PNG\r\n\x1a\n':
        return _parse_png_dimensions(buf)
    if buf[0:2] == b'\xff\xd8':
        return _parse_jpeg_dimensions(buf)
    if buf[0:4] == b'RIFF' and buf[8:12] == b'WEBP':
        return _parse_webp_dimensions(buf)
    return None


# ---------------------------------------------------------------------------
# Image encoding
# ---------------------------------------------------------------------------

def local_image_to_base64(file_path):
    """Read local image, return data URI string."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {file_path}")
    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/png"
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def local_image_to_raw_base64(file_path):
    """Read local image, return raw base64 string (no data URI prefix)."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {file_path}")
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def encode_images(image_paths, provider_id):
    """Encode images using provider-appropriate format. Returns list of refs."""
    handler = get_provider_handler(provider_id)
    encode_fn = handler["encode_image"]
    accepts_url = handler.get("accepts_url", True)
    refs = []
    for path in image_paths:
        if path.startswith(("http://", "https://", "data:")):
            if not accepts_url:
                raise ValueError(f"{provider_id} requires local files, not URLs")
            refs.append(path)
        else:
            refs.append(encode_fn(path))
    return refs


# ---------------------------------------------------------------------------
# Image processing — pad / crop / resize (requires Pillow, graceful fallback)
# ---------------------------------------------------------------------------

_HAS_PILLOW = None


def _check_pillow():
    global _HAS_PILLOW
    if _HAS_PILLOW is None:
        try:
            from PIL import Image as _
            _HAS_PILLOW = True
        except ImportError:
            _HAS_PILLOW = False
    return _HAS_PILLOW


def pad_image(image_path, target_w, target_h):
    """Zero-pad image to target size (original at top-left, black fill).
    Returns path to padded image in cache dir."""
    if not _check_pillow():
        return image_path
    from PIL import Image
    img = Image.open(image_path)
    if img.size[0] >= target_w and img.size[1] >= target_h:
        return image_path
    mode = img.mode if img.mode in ("RGB", "RGBA", "L") else "RGB"
    if img.mode != mode:
        img = img.convert(mode)
    padded = Image.new(mode, (target_w, target_h), 0)
    padded.paste(img, (0, 0))
    out_path = _CACHE_DIR / f"padded_{target_w}x{target_h}_{Path(image_path).stem}.png"
    padded.save(str(out_path))
    return str(out_path)


def crop_image(image_path, crop_w, crop_h):
    """Crop image to target size from top-left. Overwrites file."""
    if not _check_pillow():
        return image_path
    from PIL import Image
    img = Image.open(image_path)
    if img.size == (crop_w, crop_h):
        return image_path
    cropped = img.crop((0, 0, crop_w, crop_h))
    cropped.save(image_path)
    return image_path


def resize_image(image_path, target_w, target_h):
    """Resize image to exact target size using Lanczos. Overwrites file."""
    if not _check_pillow():
        return image_path
    from PIL import Image
    img = Image.open(image_path)
    if img.size == (target_w, target_h):
        return image_path
    img = img.resize((target_w, target_h), Image.LANCZOS)
    img.save(image_path)
    return image_path


def _resize_image_copy(image_path, target_w, target_h):
    """Resize image to a new file in cache dir. Returns new path."""
    if not _check_pillow():
        return image_path
    from PIL import Image
    img = Image.open(image_path)
    if img.size == (target_w, target_h):
        return image_path
    img = img.resize((target_w, target_h), Image.LANCZOS)
    out_path = _CACHE_DIR / f"resized_{target_w}x{target_h}_{Path(image_path).stem}.png"
    img.save(str(out_path))
    return str(out_path)


# ---------------------------------------------------------------------------
# Image download & save
# ---------------------------------------------------------------------------

def _normalize_path(path_str):
    if sys.platform != "win32" and len(path_str) >= 2 and path_str[1] == ':':
        drive = path_str[0].lower()
        rest = path_str[2:].replace("\\", "/")
        return f"/mnt/{drive}{rest}"
    return path_str


def save_base64_image(base64_data, mime_type, output_dir, filename):
    output_path = Path(_normalize_path(output_dir))
    output_path.mkdir(parents=True, exist_ok=True)
    file_path = output_path / filename
    raw = base64.b64decode(base64_data)
    with open(file_path, "wb") as f:
        f.write(raw)
    return str(file_path.resolve())


def download_image(url, output_dir, filename):
    output_path = Path(_normalize_path(output_dir))
    output_path.mkdir(parents=True, exist_ok=True)
    file_path = output_path / filename

    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=120) as resp:
        with open(file_path, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)

    return str(file_path.resolve())


# ---------------------------------------------------------------------------
# Filename sanitization
# ---------------------------------------------------------------------------

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_SPACE = re.compile(r'[\s_]+')


def sanitize_filename(prompt, max_len=50):
    name = _UNSAFE_CHARS.sub("", prompt)
    name = _MULTI_SPACE.sub("_", name).strip("_. ")
    if len(name) > max_len:
        truncated = name[:max_len]
        last_underscore = truncated.rfind("_")
        if last_underscore > max_len // 2:
            name = truncated[:last_underscore]
        else:
            name = truncated
    return name if name else "generated_image"


def build_output_filename(prompt, output_format="png"):
    now = datetime.now()
    return f"{sanitize_filename(prompt)}_{now.strftime('%Y%m%d')}_{now.strftime('%H%M%S')}.{output_format}"


# ---------------------------------------------------------------------------
# JSON output helpers
# ---------------------------------------------------------------------------

def output_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def output_error(error_msg, suggestion=None):
    result = {"error": error_msg}
    if suggestion:
        result["suggestion"] = suggestion
    output_json(result)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Core generation function — the composable unit
# ---------------------------------------------------------------------------

def _detect_extension(image_url, base64_data, mime_type):
    if base64_data:
        return {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(mime_type, "png")
    if image_url:
        url_path = image_url.split("?")[0].lower()
        if url_path.endswith((".jpg", ".jpeg")):
            return "jpg"
        if url_path.endswith(".webp"):
            return "webp"
    return "png"


def generate_one(prompt, model=None, images=None, size=None, output_dir=None,
                  provider=None, ref_index=0, mask=None):
    """
    Core single-image generation. Callable from CLI or batch.

    Returns: {"url", "local_path", "model", "provider", "size", "mode", "auto_size"?}
    Raises: RuntimeError / ValueError / FileNotFoundError on failure.
    """
    model = model or get_default_model()
    supported = get_supported_models()
    if model not in supported:
        raise RuntimeError(f"Unsupported model: {model}. Supported: {', '.join(supported)}")

    provider_id = provider or detect_provider(model)
    if not provider_id:
        raise RuntimeError(f"Cannot detect provider for model: {model}")
    handler = get_provider_handler(provider_id)
    config = load_config()

    if not config.get("image_api_key"):
        raise RuntimeError("image_api_key not configured")

    model_config = get_model_config(model)
    settings = load_settings()
    fit_result = None

    # === Size decision ===
    img2img_follow = (settings.get("img2img_size_mode", "follow_input") == "follow_input")

    if images and size is None and img2img_follow:
        idx = min(ref_index, len(images) - 1)
        dims = get_image_dimensions(images[idx])
        if dims:
            fit_fn = handler.get("fit_size")
            if fit_fn:
                fit_result = fit_fn(dims[0], dims[1], model)
                if fit_result.get("strategy") == "use_default":
                    effective_size = model_config.get("size")
                else:
                    effective_size = fit_result["size"]
            else:
                effective_size = model_config.get("size")
        else:
            effective_size = model_config.get("size")
    else:
        effective_size = size or model_config.get("size")

    # === Normalize cross-format + validate with fit fallback ===
    if effective_size:
        effective_size = _normalize_size(effective_size, provider_id, model)
        try:
            effective_size = handler["validate_size"](effective_size, model)
        except ValueError:
            w, h = _parse_wh(effective_size)
            if w and h:
                fit_fn = handler.get("fit_size")
                if fit_fn:
                    fit_result = fit_fn(w, h, model)
                    effective_size = fit_result["size"]
                    effective_size = handler["validate_size"](effective_size, model)
                else:
                    raise
            else:
                raise
        model_config["size"] = effective_size

    # === Apply Gemini imageSize from fit_result ===
    if fit_result and provider_id == "vertex_ai":
        suggested_is = fit_result.get("imageSize")
        user_overrides = settings.get("model_configs", {}).get(model, {})
        if suggested_is and "imageSize" not in user_overrides:
            model_config["imageSize"] = suggested_is

    # === Tongyi img2img ROI warning for small output sizes ===
    _tongyi_roi_warning = None
    if images and provider_id == "tongyi" and effective_size:
        _tw, _th = _parse_wh(effective_size.replace("*", "x")) or (0, 0)
        if _tw and _th and max(_tw, _th) < _TONGYI_ROI_MIN_DIM:
            _tongyi_roi_warning = (
                f"通义模型在输出尺寸 {effective_size} (<{_TONGYI_ROI_MIN_DIM}px) "
                f"下可能出现 ROI 裁切/构图偏移，建议输出尺寸 ≥{_TONGYI_ROI_MIN_DIM}。"
            )

    # === Padding decision ===
    padding_enabled = settings.get("padding_enabled", True)
    do_padding = (
        fit_result
        and fit_result.get("strategy") == "pad_crop"
        and padding_enabled
        and _check_pillow()
    )

    if fit_result and fit_result.get("strategy") == "pad_crop" and not do_padding:
        fit_result["strategy"] = "no_pad_resize"
        fit_result["pad_to"] = None
        fit_result["roi"] = None

    # === Pad + resize input images if padding enabled ===
    actual_images = list(images) if images else None
    if do_padding and actual_images:
        pad_to = fit_result.get("pad_to")
        resize_to_input = fit_result.get("resize_to_input")
        processed = []
        for img_path in actual_images:
            if isinstance(img_path, str) and not img_path.startswith(
                    ("http://", "https://", "data:")):
                p = img_path
                if pad_to:
                    p = pad_image(p, pad_to[0], pad_to[1])
                if resize_to_input:
                    p = _resize_image_copy(p, resize_to_input[0], resize_to_input[1])
                processed.append(p)
            else:
                processed.append(img_path)
        actual_images = processed

    # === Inject ROI prompt if padding was applied ===
    effective_prompt = prompt
    if do_padding:
        roi = fit_result.get("roi") if fit_result else None
        if roi:
            roi_w, roi_h = roi
            if fit_result.get("resize_to_input"):
                canvas_w, canvas_h = fit_result["resize_to_input"]
            elif fit_result.get("pad_to"):
                canvas_w, canvas_h = fit_result["pad_to"]
            else:
                canvas_w, canvas_h = fit_result["fitted"]
            roi_prompt_tpl = load_prompts().get("padding_roi", "")
            if roi_prompt_tpl:
                roi_instruction = roi_prompt_tpl.format(
                    roi_w=roi_w, roi_h=roi_h,
                    canvas_w=canvas_w, canvas_h=canvas_h)
                effective_prompt = f"{prompt}\n\n{roi_instruction}"

    # === Encode images + validate img2img support ===
    image_ref = None
    if actual_images:
        img2img_models = get_img2img_models()
        if model not in img2img_models:
            raise RuntimeError(
                f"Model '{model}' does not support img2img. "
                f"Supported: {', '.join(img2img_models)}"
            )
        refs = encode_images(actual_images, provider_id)
        image_ref = refs if len(refs) > 1 else refs[0]

    # === Mask encoding (azure_openai inpainting) ===
    if mask and image_ref:
        if mask.startswith(("http://", "https://", "data:")):
            model_config["_mask_encoded"] = mask
        else:
            model_config["_mask_encoded"] = handler["encode_image"](mask)

    # === API call ===
    body = build_request_body(provider_id, effective_prompt, model, model_config, image_ref)
    endpoint = handler.get("img2img_endpoint") if image_ref else None
    timeout = handler.get("timeout", 180)
    response = image_request(body, config, provider_id, timeout=timeout, endpoint=endpoint)
    parsed = parse_image_response(response, provider_id)

    # === Save output ===
    out_dir = output_dir or get_output_dir()
    image_url = parsed.get("url")
    base64_data = parsed.get("base64_data")
    mime_type = parsed.get("mime_type", "image/png")

    ext = _detect_extension(image_url, base64_data, mime_type)
    filename = build_output_filename(prompt, ext)

    local_path = None
    download_error = None
    if base64_data:
        try:
            local_path = save_base64_image(base64_data, mime_type, out_dir, filename)
        except Exception as e:
            download_error = str(e)
    elif image_url:
        try:
            local_path = download_image(image_url, out_dir, filename)
        except Exception as e:
            download_error = str(e)

    # === Post-process ===
    if local_path and fit_result:
        strategy = fit_result.get("strategy")
        if strategy == "pad_crop":
            resize_to_input = fit_result.get("resize_to_input")
            if resize_to_input:
                pad_to = fit_result.get("pad_to") or fit_result.get("original")
                resize_image(local_path, pad_to[0], pad_to[1])
            crop_to = fit_result.get("crop_to")
            if crop_to:
                crop_image(local_path, crop_to[0], crop_to[1])
        elif strategy == "no_pad_resize":
            orig = fit_result.get("original")
            if orig:
                resize_image(local_path, orig[0], orig[1])

    mode = "text2img"
    if images:
        mode = "multi_image_img2img" if len(images) > 1 else "img2img"

    result = {
        "url": image_url,
        "local_path": local_path,
        "model": model,
        "provider": provider_id,
        "size": effective_size,
        "mode": mode,
    }
    if fit_result:
        result["auto_size"] = fit_result
        strategy = fit_result.get("strategy")
        if strategy == "pad_crop":
            orig = fit_result.get("original", (0, 0))
            result["size_notice"] = (
                f"输入尺寸 {orig[0]}x{orig[1]} 与模型输出要求不符，"
                f"已启用 padding 策略保持原始分辨率输出。"
                f"可通过 preflight.py --set-padding false 关闭。"
            )
        elif strategy == "no_pad_resize":
            orig = fit_result.get("original", (0, 0))
            fitted = fit_result.get("fitted", (0, 0))
            result["size_notice"] = (
                f"输入尺寸 {orig[0]}x{orig[1]} 与模型输出不符，"
                f"padding 已关闭，输出 resize 到原始尺寸 (可能有轻微比例偏差)。"
            )
        elif strategy == "scale_down":
            orig = fit_result.get("original", (0, 0))
            fitted = fit_result.get("fitted", (0, 0))
            result["size_notice"] = (
                f"输入尺寸 {orig[0]}x{orig[1]} 超出模型最大输出，"
                f"已缩小到 {fitted[0]}x{fitted[1]}。"
            )
        elif strategy == "scale_up":
            orig = fit_result.get("original", (0, 0))
            fitted = fit_result.get("fitted", (0, 0))
            result["size_notice"] = (
                f"输入尺寸 {orig[0]}x{orig[1]} 低于模型最小输出要求，"
                f"保持宽高比放大到 {fitted[0]}x{fitted[1]}。"
            )
        elif strategy == "use_default":
            orig = fit_result.get("original", (0, 0))
            result["size_notice"] = (
                f"输入尺寸 {orig[0]}x{orig[1]} 低于模型最小输出要求，"
                f"使用默认输出尺寸 {effective_size}。"
            )
    if _tongyi_roi_warning:
        result["size_notice"] = (
            result.get("size_notice", "") + " " + _tongyi_roi_warning
        ).strip()
    if download_error:
        result["download_error"] = download_error
    return result
