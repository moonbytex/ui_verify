"""坐标定位器。对应 uiVerification.mjs L1262-1296。

- NormalizedLocator (ss)：默认。提示模型"屏幕宽高为999x999"，截图缩放到 2/3，坐标按 999 归一化换算。
- Qwen25Locator     (is)：模型名匹配 /qwen2\\.5/i 时使用，截图尺寸对齐 28 的倍数，坐标按截图像素换算。
"""
from __future__ import annotations

import math


class NormalizedLocator:
    def get_prompt(self) -> str:
        return "屏幕宽高为999x999，坐标原点在左上角"

    def get_suitable_image_size(self, screen: tuple[int, int]) -> tuple[int, int] | None:
        return (math.floor(screen[0] * 2 / 3), math.floor(screen[1] * 2 / 3))

    def point_interp(self, point, image_size, screen_size) -> tuple[int, int]:
        w, h = screen_size
        x = min(w, max(1, round(point[0] * w / 999)))
        y = min(h, max(1, round(point[1] * h / 999)))
        return x, y


PE, MIN_SIDE, MAX_SIDE = 28, 480, 1424


class Qwen25Locator:
    def get_prompt(self) -> str:
        return ""

    def get_suitable_image_size(self, screen):
        r, n = screen
        i = round(r / PE) * PE
        o = round(n / PE) * PE
        if i > MAX_SIDE or o > MAX_SIDE:
            s = max(i, o) / MAX_SIDE
            i = math.floor(i / s / PE) * PE
            o = math.floor(o / s / PE) * PE
        if i < MIN_SIDE or o < MIN_SIDE:
            s = MIN_SIDE / min(i, o)
            i = math.ceil(i * s / PE) * PE
            o = math.ceil(o * s / PE) * PE
        return (i, o)

    def point_interp(self, point, image_size, screen_size):
        x = min(screen_size[0], max(1, round(point[0] * screen_size[0] / image_size[0])))
        y = min(screen_size[1], max(1, round(point[1] * screen_size[1] / image_size[1])))
        return x, y
