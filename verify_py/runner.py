"""本地入口，对应 uiVerification.mjs 的 Fc（L8398-8421）与启动时的模型/定位器选择（L9454-9464）。

不启动 MCP。在已连接的鸿蒙设备上执行 verifyUI，并把过程写到 sequence-log 目录，用浏览器打开 index.html 即可看每一步。
"""
from __future__ import annotations

import os
import re
import tempfile
import time
from threading import Event

from .agents import Context, ManagerAgent
from .config import load_model_config
from .harmony import HarmonyDevice
from .llm import DefaultChat, OpenAIClient, QwenChat
from .locator import NormalizedLocator, Qwen25Locator
from .logger import RunLogger

_JS_NAME = {
    "tap": "tap", "double_tap": "doubleTap", "swipe": "swipe", "mouse_click": "mouseClick",
    "mouse_double_click": "mouseDoubleClick", "mouse_scroll": "mouseScroll", "touch_down": "touchDown",
    "touch_up": "touchUp", "press_key": "pressKey", "input_text": "inputText", "start_app": "startApp",
    "get_log": "getLog", "screenshot": "screenshot", "get_screen_size": "getScreenSize",
    "wait_until_change": "waitUntilChange", "get_status_bar_height": "getStatusBarHeight",
    "check_error": "checkError", "set_rotation": "setRotation", "set_fold_state": "setFoldState",
    "get_foldable_info": "getFoldableInfo", "is_emulator": "isEmulator", "is_pc_or_tablet": "isPCOrTablet",
    "is_pc_or_2in1": "isPCOr2in1Device", "before_task": "beforeTask", "after_task": "afterTask",
    "single_screenshot": "singleScreenshot",
}


class LoggingDevice:
    """As()：外部调用设备方法时写入 history.md。对象内部的 self.xxx 不会再记一次。"""

    def __init__(self, device, logger):
        object.__setattr__(self, "_device", device)
        object.__setattr__(self, "_logger", logger)

    def __getattr__(self, name):
        attr = getattr(self._device, name)
        if not callable(attr):
            return attr

        def wrapped(*args, **kwargs):
            self._logger.device_call(_JS_NAME.get(name, name), list(args))
            return attr(*args, **kwargs)

        return wrapped


def log_root(path: str | None = None) -> str:
    """iu()：LOG_PATH 或参数，默认系统临时目录下的 ui-verification。"""
    root = path or os.environ.get("LOG_PATH") or os.path.join(tempfile.gettempdir(), "ui-verification")
    root = os.path.abspath(root)
    os.makedirs(root, exist_ok=True)
    if not os.path.isdir(root):
        raise RuntimeError(f"Log path {root} is not a directory")
    os.environ["UI_VERIFY_LOG_PATH"] = root
    return root


def build_chat_and_locator(cfg):
    """模型名匹配 /qwen2\\.5/i 时用 QwenChat + Qwen25Locator，否则 DefaultChat + 999 归一化。"""
    client = OpenAIClient(cfg)
    if re.search(r"qwen2\.5", cfg.model_name, re.I):
        return QwenChat(client, cfg.model_name), Qwen25Locator()
    return DefaultChat(client, cfg.model_name), NormalizedLocator()


def verify_ui(test_plan: str, bundle: str, fresh_start: bool, device_name: str | None = None, *,
              log_path: str | None = None, session_id: str | None = None, timeout: float = 1000,
              send_progress=None, send_tracing=None, signal: Event | None = None,
              open_browser: bool = False) -> dict:
    """Fc。timeout 单位秒，默认 1000，对应 AbortSignal.timeout(1e6)。"""
    cfg = load_model_config()
    chat, locator = build_chat_and_locator(cfg)
    root = log_root(log_path)
    logger = RunLogger(root)
    device = LoggingDevice(HarmonyDevice(device_name or "", locator), logger)
    ctx = Context(
        device=device, locator=locator, chat=chat, logger=logger, log_root=root,
        session_id=session_id or os.environ.get("UI_VERIFY_SESSION_ID"),
        signal=signal or Event(), deadline=time.time() + timeout,
        send_progress=send_progress, send_tracing=send_tracing,
    )
    viewer = logger.dir / "index.html"
    print(f"可视化页面: {viewer}")
    if open_browser:
        import webbrowser
        webbrowser.open(viewer.as_uri())
    print("Starting verification with plan:\n", test_plan, "\nfor bundle:", bundle)
    manager = ManagerAgent(ctx)
    try:
        device.before_task()
        if send_tracing:
            name = device.actual_device_name

            def wrapped(event, _send=send_tracing, _name=name):
                _send({**event, "deviceName": _name})

            ctx.send_tracing = wrapped
        logger.call("verifyUI", [test_plan, bundle, True if fresh_start else False])
        result = manager.verify_ui(test_plan, bundle, fresh_start)
        logger.result(result)
        return result
    finally:
        try:
            device.after_task()
        except Exception as e:  # noqa: BLE001
            print("afterTask failed:", e)
        print(f"可视化页面: {logger.dir / 'index.html'}")
