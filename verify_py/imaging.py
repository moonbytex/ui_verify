"""图片工具。

对应 uiVerification.mjs：
- Or / ji / Fi / Ho / Jo / De / zr      L67-89    识别 png/jpeg、读取宽高、生成 data URI
- Oi / Wo                               L129-203  pixelmatch 像素差异（YIQ 色差，threshold=0.1）
- Zo / Vr / Hi / Rr                     L272-320  解码 -> 裁剪区域(去掉状态栏) -> 差异像素比例
原实现用内嵌 WASM 解码图片，这里用 Pillow + numpy 实现同样语义。
"""
from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image


def is_png(b64: str) -> bool:
    return b64.startswith("iVBORw")


def is_jpeg(b64: str) -> bool:
    return b64.startswith("/9j/")


def image_ext(b64: str) -> str:
    """De()"""
    if is_png(b64):
        return "png"
    if is_jpeg(b64):
        return "jpeg"
    raise ValueError("Unknown image syntax")


def data_uri(b64: str) -> str:
    """zr()"""
    return f"data:image/{image_ext(b64)};base64,{b64}"


def image_size(b64: str) -> tuple[int, int]:
    """Or()：返回 [width, height]"""
    image_ext(b64)
    with Image.open(io.BytesIO(base64.b64decode(b64))) as im:
        return im.size


def _decode_region(b64: str, region: dict | None) -> np.ndarray | None:
    """Vr() + Hi()：解码并裁剪区域 {x, y, width?, height?}，非法区域则返回整图。"""
    try:
        with Image.open(io.BytesIO(base64.b64decode(b64))) as im:
            arr = np.asarray(im.convert("RGBA"), dtype=np.float32)
    except Exception as e:  # noqa: BLE001
        print("Failed to decode image region: ", e)
        return None
    if region:
        h, w = arr.shape[:2]
        x, y = int(region.get("x", 0)), int(region.get("y", 0))
        rw = region.get("width") or (w - x)
        rh = region.get("height") or (h - y)
        if x < 0 or y < 0 or rw <= 0 or rh <= 0 or x + rw > w or y + rh > h:
            print(f"Invalid extractImageRegion parameters: x={x}, y={y}, width={rw}, height={rh}, image size: {w}x{h}")
        else:
            arr = arr[y : y + rh, x : x + rw]
    return arr


# pixelmatch: maxDelta = 35215 * threshold^2, threshold = 0.1
_MAX_DELTA = 35215 * 0.1 * 0.1


def _pixel_diff_ratio(a: np.ndarray, b: np.ndarray) -> float:
    """Zo()：尺寸不同返回 1；否则 差异像素数 / 总像素数。

    Wo() 的 YIQ 色差公式（alpha 混合到白底）。原实现还会排除抗锯齿像素(en/_e)，
    这里省略抗锯齿检测，对截图差异判断影响很小。
    """
    if a.shape != b.shape:
        print(f"Image size mismatch: region1 {a.shape[1]}x{a.shape[0]}, region2 {b.shape[1]}x{b.shape[0]}")
        return 1.0

    def blend(x: np.ndarray) -> np.ndarray:
        alpha = x[..., 3:4] / 255.0
        return 255 + (x[..., :3] - 255) * alpha

    ca, cb = blend(a), blend(b)
    d = ca - cb
    dr, dg, db = d[..., 0], d[..., 1], d[..., 2]
    y = dr * 0.29889531 + dg * 0.58662247 + db * 0.11448223
    i = dr * 0.59597799 - dg * 0.2741761 - db * 0.32180189
    q = dr * 0.21147017 - dg * 0.52261711 + db * 0.31114694
    delta = 0.5053 * y * y + 0.299 * i * i + 0.1957 * q * q
    diff = int(np.count_nonzero(delta > _MAX_DELTA))
    return diff / (a.shape[0] * a.shape[1])


def compare_images(b64_a: str, b64_b: str, region: dict | None = None) -> float:
    """Rr()：失败时返回 1（视为完全不同）。"""
    try:
        a = _decode_region(b64_a, region)
        b = _decode_region(b64_b, region)
        if a is None or b is None:
            return 1.0
        return _pixel_diff_ratio(a, b)
    except Exception as e:  # noqa: BLE001
        print("Failed to compare images: ", e)
        return 1.0
