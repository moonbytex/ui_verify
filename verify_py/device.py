"""HarmonyOS 设备操作。

对应 uiVerification.mjs：
- class Bt   L560-1261  HDC 设备封装（点击/滑动/按键/输入/启动应用/日志/faultlog/任务锁/模拟器信息）
- class es   L475-530   SlowSnapshot：后台循环 hdc snapshot_display 截图并缓存，计算相邻帧差异
- class $i   L338-474   EmulatorSnapshot：DevEco Emulator >= 26 时用 `Emulator -screenshot` 截图
- rs / ns    L536-558   解析模拟器 deviceType / 屏幕 Rotation
"""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from PIL import Image

from .imaging import compare_images

DEVICE_TMP = "/data/local/tmp"  # Ke

# jr：折叠屏类型 -> 支持的状态
FOLD_STATES = {
    "Foldable": ["open", "half-open", "close"],
    "WideFold": ["open", "half-open", "close"],
    "2in1_Foldable": ["open", "vertical-open", "half-open", "close"],
    "TripleFold": [
        "single", "double", "triple",
        "left-folded-right-half-folded", "left-half-folded-right-expanded",
        "left-expanded-right-folded", "left-half-folded-right-folded",
        "left-expanded-right-half-folded", "left-half-folded-right-half-folded",
    ],
}

KEY_CODES = {
    "Home": 1, "Back": 2, "Enter": 2054, "Escape": 2070, "Tab": 2049, "Space": 2050,
    "Up": 2012, "Down": 2013, "Left": 2014, "Right": 2015, "Delete": 2071,
    "Backspace": 2055, "PageUp": 2068, "PageDown": 2069,
    **{chr(ord("A") + i): 2017 + i for i in range(26)},
    "Ctrl": 2072, "Shift": 2047, "Alt": 2045,
}

# buildSpecialCharCommand：特殊字符 -> keyEvent
SPECIAL_CHAR_KEYS = {
    "\\": "2061", " ": "2050", "'": "2063", '"': "2047 2063", "<": "2047 2043",
    ">": "2047 2044", "&": "2047 2007", "|": "2047 2061", "^": "2047 2006",
    "`": "2056", "~": "2047 2056", ";": "2062", "(": "2047 2009", ")": "2047 2000",
    "$": "2047 2004", "#": "2047 2003",
}
SPECIAL_SPLIT = re.compile(r"([\\'\" <>&|^`~;()$#])")
PNG_TAIL = bytes([0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130])  # ki：IEND 块


class CommandError(RuntimeError):
    pass


def exec_command(cmd: str, ignore_stderr: bool = False) -> str:
    """execCommand：stderr 非空且不含 WARNING 时视为失败（除非 ignore_stderr）。"""
    p = subprocess.run(cmd, shell=True, capture_output=True)
    out = p.stdout.decode("utf-8", errors="replace")
    err = p.stderr.decode("utf-8", errors="replace")
    if p.returncode != 0:
        raise CommandError(f"Command failed: {cmd}\n{err or out}")
    if "[Fail]ExecuteCommand need connect-key" in out:
        raise CommandError(out)
    if err and not ignore_stderr and "WARNING" not in err:
        raise CommandError(err)
    return out


def parse_rotation(dump: str) -> int | None:
    """ns()"""
    m0 = re.search(r"\[SCREEN[ _]INFO\]", dump)
    if not m0:
        return None
    m = re.search(r"Rotation:\s*(\d+)", dump[m0.start():])
    if not m:
        return None
    v = int(m.group(1))
    return v if v in (0, 1, 2, 3) else None


def encode_jpeg(raw: bytes, size, quality: int, turns_cw: int = 0, crop: dict | None = None) -> bytes:
    """对应 WASM resizeAndEncodeJPEG：裁剪 -> 顺时针旋转 -> 缩放 -> JPEG。"""
    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        if crop:
            im = im.crop((crop["x"], crop["y"], crop["x"] + crop["width"], crop["y"] + crop["height"]))
        if turns_cw % 4:
            im = im.rotate(-90 * (turns_cw % 4), expand=True)
        if size:
            im = im.resize(tuple(size), Image.BILINEAR)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
        return buf.getvalue()


class SlowSnapshot:
    """class es：后台线程不断 singleScreenshot()，缓存帧并记录与上一帧的 diff。"""

    TIMEOUT = 5.0  # _i
    POLL = 0.1  # on
    CHANGE_THRESHOLD = 1e-3

    def __init__(self, device: "HarmonyDevice", status_bar_height: int):
        self.device = device
        self.status_bar_height = status_bar_height
        self.running = False
        self.cache: list[dict] = []
        self.last_before_consumed: dict | None = None
        self.lock = threading.Lock()

    def start(self):
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _grab(self) -> dict:
        return self.device.single_screenshot()

    def _loop(self):
        while self.running:
            try:
                self._add(self._grab())
            except Exception as e:  # noqa: BLE001
                print("获取截图失败:", e)
                time.sleep(0.5)

    def stop(self):
        self.running = False

    def _reference(self) -> dict | None:
        with self.lock:
            if not self.cache and self.last_before_consumed:
                ref, self.last_before_consumed = self.last_before_consumed, None
                return ref
            return self.cache[-1] if self.cache else None

    def _add(self, img: dict):
        ref = self._reference()
        region = {"x": 0, "y": self.status_bar_height}
        img["diff"] = compare_images(ref["base64"], img["base64"], region) if ref else 1.0
        with self.lock:
            self.cache.append(img)

    def wait_until_change(self, timeout_ms: int):
        start = time.time() * 1000
        while time.time() * 1000 < start + timeout_ms:
            with self.lock:
                if any(i["timestamp"] > start and i["diff"] > self.CHANGE_THRESHOLD for i in self.cache):
                    return
            time.sleep(self.POLL)

    def screenshot(self) -> list[dict]:
        """取走并清空缓存中的全部帧；缓存为空则轮询等待。"""
        if not self.running:
            self.start()
        t0 = time.time()
        while True:
            with self.lock:
                if self.cache:
                    out, self.cache = self.cache, []
                    self.last_before_consumed = out[-1]
                    return out
            if time.time() - t0 >= self.TIMEOUT:
                raise RuntimeError("截图超时，设备可能忙")
            time.sleep(self.POLL)


class EmulatorSnapshot(SlowSnapshot):
    """class $i：`Emulator -instance <name> -screenshot` 抓原始 PNG，再按需旋转/压缩。"""

    POLL = 0.05  # rn
    CHANGE_THRESHOLD = 0.01

    def __init__(self, emulator_name, emulator_path, device, status_bar_height):
        super().__init__(device, status_bar_height)
        self.emulator_name = emulator_name
        self.emulator_path = emulator_path
        self.last_img: dict | None = None

    def _reference(self):
        return self.last_img

    def _add(self, img):
        super()._add(img)
        self.last_img = img

    def stop(self):
        self.running = False
        self.cache, self.last_img = [], None

    def capture_raw_png(self) -> bytes:
        d = Path(tempfile.gettempdir()) / f"emu-screenshot-{uuid.uuid4()}"
        d.mkdir(parents=True, exist_ok=True)
        try:
            exec_command(f'"{self.emulator_path}" -instance "{self.emulator_name}" -screenshot -screenshotPath "{d}"', True)
            t0 = time.time()
            while time.time() - t0 < 5:
                for f in d.glob("*.png"):
                    data = f.read_bytes()
                    if len(data) >= 12 and data[-12:] == PNG_TAIL:
                        return data
                time.sleep(0.05)
            raise RuntimeError("模拟器截图超时")
        finally:
            for f in d.glob("*"):
                f.unlink(missing_ok=True)
            d.rmdir()

    def cache_emulator_direction(self):
        """cacheEmulatorDirection：emu 方向 = 系统方向 + 截图旋转差。这里简化为以系统方向为准。"""
        if self.device.is_pc_or_2in1():
            return
        r = self.device.get_system_rotation()
        if r is None:
            raise RuntimeError("读取系统方向失败")
        self.device.emulator_direction = r

    def _grab(self) -> dict:
        w, h = self.device.get_screen_size()
        size = self.device.locator.get_suitable_image_size((w, h))
        turns = self.device.get_screenshot_rotation()
        raw = self.capture_raw_png()
        if self.device.is_pc_or_2in1():
            data = encode_jpeg(raw, size or (w, h), 80)
        elif turns == 0 and not size:
            data = raw
        else:
            data = encode_jpeg(raw, size or (w, h), 80, turns)
        import base64

        return {"base64": base64.b64encode(data).decode(), "screenSize": [w, h],
                "timestamp": int(time.time() * 1000), "diff": 0}


# ---- HarmonyDevice 定义见下方 ----
