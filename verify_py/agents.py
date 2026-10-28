"""多智能体编排。

对应 uiVerification.mjs：
- class We  L7445-7512  ActionAgent
- class qr  L7515-7569  FakeActionAgent（重放步骤记忆）
- class br  L7607-7639  InputMatcherAgent
- class Ur  L7691-7784  InputValidationAgent
- class Kr  L7998-8057  StatusAgent（+ bc 重复状态检测 L7982, Uc abnormal 重试计数 L8059）
- class Mr  L8124-8262  SummaryAgent
- class Fr  L8266-8396  ManagerAgent.verifyUI
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Event

from . import prompts
from .actions import (
    action_to_call, execute_action, history_for_action, history_for_status, history_for_summary, js_json,
)
from .config import MAX_ABNORMAL_RETRIES, MAX_EXECUTION_ROUNDS, MAX_REPEATED_STATUS
from .history import (
    StepMemory, first_action_name, get_stable_images, has_abnormal, last_image_b64, now_ms,
    pending_touch_down, until_last_normal,
)
from .imaging import compare_images, image_size
from .llm import call_with_tools
from .logger import History
from .tools import (
    BASE_TOOLS, MATCH_TOOLS, MOUSE_TOOLS, ROTATION_TOOL, STATUS_TOOLS, SUMMARY_TOOLS, VALIDATION_TOOLS,
    ToolValidator, fold_tool,
)

INVALID_PREFIX = "[计划校验失败]"  # Mc


class Aborted(RuntimeError):
    pass


@dataclass
class Context:
    device: object
    locator: object
    chat: object
    logger: object
    log_root: str
    session_id: str | None = None
    signal: Event = field(default_factory=Event)  # set() 即中止
    deadline: float = field(default_factory=lambda: time.time() + 1000)  # AbortSignal.timeout(1e6)
    send_progress: object = None
    send_tracing: object = None

    def throw_if_aborted(self):
        if self.signal.is_set() or time.time() > self.deadline:
            raise Aborted("The operation was aborted")


def trace(ctx, msg, event):
    print(msg)
    if ctx.send_tracing:
        ctx.send_tracing(event)


# --------------------------------------------------------------------------- #
class ActionAgent:
    """We"""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self._tv = None

    def tools_and_validator(self):
        if self._tv is None:
            dev = self.ctx.device
            fold, emu = dev.get_foldable_info(), dev.is_emulator()
            tools = list(BASE_TOOLS)
            if fold:
                tools.append(fold_tool(fold["type"], fold["supportedStates"]))
            if dev.is_pc_or_tablet():
                tools.extend(MOUSE_TOOLS)
            if emu and not dev.is_pc_or_2in1():
                tools.append(ROTATION_TOOL)
            self._tv = (tools, ToolValidator(tools))
        return self._tv

    def get_next_action(self, plan, history):
        dev = self.ctx.device
        msgs = [
            {"role": "system", "content": prompts.action_system_prompt(dev.device_type, dev.emulator_direction)
             + self.ctx.locator.get_prompt()},
            {"role": "user", "content": f"{plan}"},
            *history_for_action(history),
        ]
        down = pending_touch_down(history) is not None
        tools, validator = self.tools_and_validator()

        def check(p):
            if p is None:
                return None
            if down and p["name"] != "touchUp":
                print(f"[ActionAgent] touchDown 后检测到非 touchUp 操作：{p['name']}")
                return "touchDown 操作后必须调用 touchUp 操作"
            if not down and p["name"] == "touchUp":
                return "touchUp 操作前必须先调用 touchDown 操作"
            return None

        result, tc, parsed = call_with_tools(self.ctx, "ActionAgent", tools, validator, msgs, check_function=check)
        return {"toolCall": tc, "parsedToolCall": parsed, "result": result}

    def release_pending_touch(self, history) -> bool:
        down = pending_touch_down(history)
        if not down:
            return False
        img = last_image_b64(history)
        if not img:
            raise RuntimeError("ActionAgent: No image found in history for terminal touchUp")
        w, h = self.ctx.device.get_screen_size()
        x, y = self.ctx.locator.point_interp(down["point"], image_size(img), [w, h])
        self.ctx.device.touch_up(x, y)
        print(f"[ActionAgent] 长按释放成功：touchUp({x}, {y})")
        return True

    def execute_action(self, nxt, bundle, history):
        tc, parsed, result = nxt["toolCall"], nxt["parsedToolCall"], nxt["result"]
        if parsed is None:
            history.append({"id": "", "type": "action", "name": "none",
                            "reason": result.get("content") or "没有可执行的操作", "timestamp": now_ms()})
            return
        self.ctx.throw_if_aborted()
        print("ActionAgent获取截图")
        self.ctx.device.screenshot()  # 清空缓存，使之后的截图都在动作之后
        execute_action(self.ctx, tc["id"], parsed, result.get("content"), history)
        if parsed["name"] != "sleep":
            if parsed["name"] in ("touchDown", "inputText"):
                time.sleep(0.8)
            else:
                self.ctx.device.wait_until_change(4000)

    def action(self, plan, bundle, history):
        with ThreadPoolExecutor(1) as ex:
            log_f = ex.submit(self.ctx.device.get_log, bundle)
            nxt = self.get_next_action(plan, history)
            log = log_f.result()
        history.append({"type": "log", "content": log, "timestamp": now_ms()})
        self.execute_action(nxt, bundle, history)


# --------------------------------------------------------------------------- #
class FakeActionAgent:
    """qr：重放已保存的步骤；截图像素比对 diff > 0.01 即停止，返回已复用进度。"""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    def action(self, saved, bundle, history):
        progress = 0
        for i in range(1, len(saved)):
            self.ctx.throw_if_aborted()
            s = saved[i]
            if s["type"] == "action":
                if s["name"] == "none":
                    continue
                print(f"FakeAction Agent: {s['name']}, reason: {s['reason']}")
                self.ctx.logger.fake_action(s["name"], s["reason"])
                history.append({"type": "log", "content": self.ctx.device.get_log(bundle), "timestamp": now_ms()})
                execute_action(self.ctx, s["id"], action_to_call(s), s["reason"], history)
                nxt = saved[i + 1] if i + 1 < len(saved) else None
                wait = nxt["timestamp"] - s["timestamp"] if nxt and nxt["type"] == "image" else 1500
                if s["name"] != "sleep":
                    print(f"FakeActionAgent: 等待{wait}ms")
                    time.sleep(max(wait, 0) / 1000)
                print("FakeActionAgent获取截图")
                y = self.ctx.device.screenshot()[-1]
                history.append({"type": "image", "base64List": [y["base64"]], "screenSize": y["screenSize"],
                                "timestamp": now_ms()})
            elif s["type"] == "image":
                cur = last_image_b64(history)
                if not cur:
                    print("No image available for comparison.")
                    return progress
                try:
                    sbh = self.ctx.device.get_status_bar_height()
                except Exception:  # noqa: BLE001
                    sbh = 0
                ref = s["base64List"][-1] if s["base64List"] else None
                if not ref:
                    print("No image in matched history item for comparison.")
                    return progress
                d = compare_images(ref, cur, {"x": 0, "y": sbh})
                self.ctx.logger.fake_match(d, d <= 0.01)
                if d > 0.01:
                    print(f"FakeActionAgent: 截图匹配失败，diff={d}")
                    return progress
            elif s["type"] == "status":
                history.append(s)
                progress = s["progress"]
        return progress


# --------------------------------------------------------------------------- #
class InputMatcherAgent:
    """br"""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.validator = ToolValidator(MATCH_TOOLS)

    def memory(self, bundle):
        return StepMemory(self.ctx.log_root, self.ctx.session_id, self.ctx.device.actual_device_name, bundle)

    def match(self, plan, bundle):
        mem = self.memory(bundle)
        plans = mem.plans()
        if not plans:
            return {"type": "InputMatcher", "matchedHistory": None}
        msgs = [
            {"role": "system", "content": prompts.MATCHER},
            {"role": "user", "content": f"用户计划：{plan}"},
            {"role": "user", "content": f"已执行的计划列表：{js_json(plans)}"},
        ]
        _, _, parsed = call_with_tools(self.ctx, "InputMatcherAgent", MATCH_TOOLS, self.validator, msgs,
                                       message_when_no_tool_call="未正确调用工具进行匹配，请重试")
        if parsed is None or parsed["arguments"]["index"] == -1:
            return {"type": "InputMatcher", "matchedHistory": None}
        idx = int(parsed["arguments"]["index"])
        if not 0 <= idx < len(plans):
            return {"type": "InputMatcher", "matchedHistory": None}
        key = plans[idx]
        hist = mem.get(key)
        mem.delete(key)
        return {"type": "InputMatcher", "matchedHistory": hist}


FAULTLOG_DIR = os.path.join(tempfile.gettempdir(), "ui-verification", "faultlogs")
_RUNS: dict[str, list] = {}
_RUN_ORDER: list[str] = []


def remember_run(run_id, history):
    """ir：内存里保留最近 50 次 history，供按 id 回看。"""
    if run_id not in _RUNS:
        _RUN_ORDER.append(run_id)
    _RUNS[run_id] = list(history)
    while len(_RUN_ORDER) > 50:
        _RUNS.pop(_RUN_ORDER.pop(0), None)


def repeated_status(history, limit=MAX_REPEATED_STATUS):
    """bc：最近 limit 次 status 完全相同且都是 normal 时返回该状态。"""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        return None
    items = [h for h in history if h["type"] == "status"][-limit:]
    if len(items) < limit:
        return None
    n = items[0]
    same = all(i["status"] == n["status"] and i["reason"] == n["reason"] and i["progress"] == n["progress"]
               and i["total"] == n["total"] for i in items)
    if n["status"] != "normal" or not same:
        return None
    return {"count": limit, "status": n["status"], "reason": n["reason"], "progress": n["progress"], "total": n["total"]}


def abnormal_account(history, status, progress, total, limit):
    """Uc。返回 (abnormalRetryCount, isRetryLimitReached)。"""
    prev_count, prev_status, prev_progress = 0, None, None
    for h in reversed(history):
        if h["type"] == "status":
            prev_count, prev_status, prev_progress = h["abnormalRetryCount"], h["status"], h["progress"]
            break
    if status == "completed":
        count, reached, tag = 0, False, "completed"
    else:
        advanced = prev_progress is not None and prev_progress < progress
        base = 0 if advanced else prev_count
        if status == "abnormal":
            count = min(base + 1, limit)
            reached = count >= limit
            tag = "retry_limit_reached" if reached else ("abnormal_detected" if base == 0 else "retry_failed")
        elif status == "error":
            count, reached, tag = base, False, "unrecoverable_error"
        else:
            count, reached = base, False
            tag = ("retry_succeeded" if advanced else "recovering") if prev_count > 0 else "normal_execution"
    shown = "error" if reached else status
    prev_p = "none" if prev_progress is None else prev_progress
    prev_s = "null" if prev_status is None else prev_status
    print(f"[StatusAgent][{tag}]\nprevious status = {prev_s}\ncurrent status = {shown}\n"
          f"previous progress = {prev_p}\ncurrent progress = {progress}\ntotal = {total}\n"
          f"previous abnormalCount = {prev_count}\ncurrent abnormalCount = {count}\n"
          f"maximalAbnormalRetries = {limit}")
    return count, reached


FOLD_OP_DESC = {
    "Foldable": "展开、闭合、半展开、悬停等折叠屏状态相关操作。",
    "WideFold": "展开、闭合、半展开、悬停等折叠屏状态相关操作。",
    "TripleFold": "单屏、双屏、三屏、左半折右展开、左展开右半折、左半折右半折、左折叠右半折、左半折右折叠、左展开右折叠等三折屏状态相关操作。",
    "2in1_Foldable": "横屏展开、竖屏展开、半折、悬停、磁吸等 2in1 折叠屏状态相关操作。",
}


# --------------------------------------------------------------------------- #
class InputValidationAgent:
    """Ur"""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.validator = ToolValidator(VALIDATION_TOOLS)

    def validate(self, plan):
        profile = self.device_profile()
        msgs = [
            {"role": "system", "content": prompts.VALIDATION},
            {"role": "user", "content": f"当前设备信息：\n{json.dumps(profile, ensure_ascii=False, indent=2)}\n\n用户测试计划：\n{plan}"},
        ]
        _, _, parsed = call_with_tools(
            self.ctx, "InputValidationAgent", VALIDATION_TOOLS, self.validator, msgs,
            message_when_no_tool_call="未正确调用工具进行输入校验，请重试",
        )
        if parsed is None:
            return {"type": "InputValidation", "status": "inValid", "reason": "未正确调用工具进行输入校验，请重试"}
        return {"type": "InputValidation", "status": "valid" if parsed["arguments"]["isValid"] else "inValid",
                "reason": parsed["arguments"]["reason"]}

    def device_profile(self):
        dev = self.ctx.device
        kind = dev.device_type
        emu, fold = dev.is_emulator(), dev.get_foldable_info()
        fold_val = None if not fold else {"type": fold["type"], "supportedStates": fold["supportedStates"]}
        return [
            {"name": "deviceType", "definition": "当前设备类型。可能值包括 phone、tablet、2in1。 ", "value": kind},
            {"name": "isEmulator", "definition": "当前设备是否为模拟器。可能值为 true 或 false。", "value": emu},
            {"name": "foldableInfo",
             "definition": "当前设备是否为可识别的折叠屏模拟器及其支持状态。可能值为 null，或包含 type 与 supportedStates 的对象；type 可能为 Foldable、WideFold、TripleFold、2in1_Foldable。",
             "value": fold_val},
            {"name": "supportedOperations",
             "definition": "当前设备根据 deviceType、isEmulator、foldableInfo 得到操作能力集合；用于判断测试计划中的操作是否能在当前设备上执行。",
             "value": self.supported_operations(kind, emu, fold_val)},
        ]

    def supported_operations(self, kind, emu, fold):
        name = kind.strip().lower()
        ops = [{"type": "基础触控操作", "description": "点击、双击、滑动、长按、输入、返回、Home 等所有设备通用操作。"}]
        if self.ctx.device.is_pc_or_tablet():
            ops.append({"type": "鼠标操作", "description": "鼠标点击、鼠标双击、鼠标滚轮、左键、右键等明确依赖鼠标的操作。"})
            ops.append({"type": "键盘按键操作", "description": "键盘按键、组合键、方向键、Enter、Tab、删除等明确依赖键盘的操作。"})
        if emu and fold is not None:
            ops.append({"type": "折叠状态切换", "description": FOLD_OP_DESC.get(fold["type"], "")})
        if emu and (name != "2in1" or (fold or {}).get("type") == "2in1_Foldable"):
            ops.append({"type": "横竖屏切换",
                        "description": "横屏、竖屏、切换至横屏、设置为竖屏等以目标屏幕方向作为描述的操作；不允许使用“左旋”或“右旋”描述横竖屏切换。"})
        return ops


# --------------------------------------------------------------------------- #
class StatusAgent:
    """Kr"""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.validator = ToolValidator(STATUS_TOOLS)

    def analyze(self, plan, history):
        msgs = [
            {"role": "system", "content": prompts.STATUS + prompts.status_direction_hint(self.ctx.device.emulator_direction)},
            {"role": "user", "content": f"用户计划：{plan}"},
            *history_for_status(history),
        ]
        dup = repeated_status(history)
        if dup is not None:
            print(f"[重复 Status 检测] 最近 {dup['count']} 次 Status 判断完全相同：status={dup['status']}，"
                  f"progress/total={dup['progress']}/{dup['total']}，reason=「{dup['reason']}」；已向 StatusAgent 注入重复状态检测提醒。")
            msgs.append({"role": "user", "content":
                f"【系统重复状态检测提醒】最近 {dup['count']} 次 Status 判断完全相同：status={dup['status']}，"
                f"progress/total={dup['progress']}/{dup['total']}，reason=「{dup['reason']}」；请停止沿用之前的状态判断，"
                "重新基于原始测试计划和最新截图判断：如果计划目标已经满足，返回 completed；如果当前操作没有效果且任务尚未完成，"
                "返回 abnormal。不要虚构或机械推进 progress/total。"})
        result, tc, parsed = call_with_tools(
            self.ctx, "StatusAgent", STATUS_TOOLS, self.validator, msgs,
            message_when_no_tool_call="未使用工具返回结果，请重试",
        )
        if parsed is None:
            return {"type": "status", "status": "error", "reason": "内部错误：未使用工具返回结果，请重试",
                    "progress": -1, "total": -1, "abnormalRetryCount": 0,
                    "maximalAbnormalRetries": MAX_ABNORMAL_RETRIES, "id": (tc or {}).get("id", ""), "timestamp": now_ms()}
        d = parsed["arguments"]
        count, reached = abnormal_account(history, d["status"], d["progress"], d["total"], MAX_ABNORMAL_RETRIES)
        final_status = "error" if reached else d["status"]
        reason = (f"abnormal 重试已达上限（{count}/{MAX_ABNORMAL_RETRIES}），步骤 {d['progress']} 反复失败未能推进：{d['reason']}"
                  if reached else d["reason"])
        if self.ctx.send_progress:
            self.ctx.send_progress(d["progress"], d["total"], reason)
        return {"type": "status", "status": final_status, "reason": reason, "progress": d["progress"],
                "total": d["total"], "abnormalRetryCount": count, "maximalAbnormalRetries": MAX_ABNORMAL_RETRIES,
                "id": tc["id"], "timestamp": now_ms()}


# --------------------------------------------------------------------------- #
class SummaryAgent:
    """Mr"""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.validator = ToolValidator(SUMMARY_TOOLS)

    def summary_steps(self, history):
        msgs = [{"role": "system", "content": prompts.SUMMARY}, *history_for_summary(history)]
        _, _, parsed = call_with_tools(
            self.ctx, "SummaryAgent", SUMMARY_TOOLS, self.validator, msgs,
            message_when_no_tool_call="未使用工具返回结果，请重试",
        )
        if parsed is None:
            return {"successPart": "", "failPart": ""}
        return {"successPart": parsed["arguments"]["successPart"], "failPart": parsed["arguments"]["failPart"]}


# --------------------------------------------------------------------------- #
class ManagerAgent:
    """Fr.verifyUI"""

    def __init__(self, ctx: Context):
        self.id = str(uuid.uuid4())
        self.ctx = ctx
        self.action = ActionAgent(ctx)
        self.fake = FakeActionAgent(ctx)
        self.status = StatusAgent(ctx)
        self.summary = SummaryAgent(ctx)
        self.validation = InputValidationAgent(ctx)
        self.matcher = InputMatcherAgent(ctx)

    def verify_ui(self, test_plan, bundle, fresh):
        ctx = self.ctx
        with ThreadPoolExecutor(max_workers=3) as pool:
            val_f = pool.submit(self.validation.validate, test_plan)
            match_f = pool.submit(self.matcher.match, test_plan, bundle) if fresh else None

            def press_home():
                if not fresh:
                    return
                ctx.throw_if_aborted()
                ctx.logger.device_action("pressKey")
                ctx.device.press_key(["Home"])
                time.sleep(1.5)

            home_f = pool.submit(press_home)
            verdict = val_f.result()
            matched = match_f.result() if match_f else {"type": "InputMatcher", "matchedHistory": None}
            home_f.result()
        if verdict["status"] == "inValid":
            return {"success": False, "successPart": "", "failPart": "",
                    "reason": f"{INVALID_PREFIX}{verdict['reason']}", "id": ""}
        ctx.throw_if_aborted()
        saved = matched["matchedHistory"]
        shot = ctx.device.screenshot()[-1]
        history = History(ctx.logger)
        history.append({"type": "image", "base64List": [shot["base64"]], "screenSize": shot["screenSize"],
                        "timestamp": now_ms()})
        plan = (f"待测试应用bundleName：{bundle}\n测试开始时是否重新启动应用：{'true' if fresh else 'false'}\n"
                f"测试计划：\n{test_plan}")
        reused = None
        if saved is None:
            self.action.action(plan, bundle, history)
        else:
            reused = self.fake.action(saved, bundle, history)
        image_cache, reuse_traced, rounds = [], False, 0
        pool = ThreadPoolExecutor(max_workers=3)
        try:
            while True:
                ctx.throw_if_aborted()
                if not history or history[-1]["type"] != "image":
                    image_cache, stable = get_stable_images(ctx.device, image_cache)
                    if stable:
                        trace(ctx, f"[screenshot-tracing] emit event=UI_VERIFICATION_SCREENSHOT_COUNT screenshot_count={len(stable)}",
                              {"event": "UI_VERIFICATION_SCREENSHOT_COUNT", "screenshot_count": len(stable)})
                        history.append({"type": "image", "base64List": [f["base64"] for f in stable],
                                        "screenSize": stable[-1]["screenSize"], "timestamp": now_ms()})
                log_f = pool.submit(ctx.device.get_log, bundle)
                log_f.add_done_callback(lambda f: f.exception())
                status_f = pool.submit(self.status.analyze, plan, list(history))
                action_f = pool.submit(self.action.get_next_action, plan, list(history))
                m = status_f.result()
                rounds += 1
                if rounds >= MAX_EXECUTION_ROUNDS and m["status"] not in ("completed", "error"):
                    m = {**m, "status": "error",
                         "reason": (f"总执行轮数达到上限（{rounds}/{MAX_EXECUTION_ROUNDS}），当前进度为 {m['progress']}/{m['total']}，"
                                    f"为避免无限循环已终止执行。最后一次状态：{m['reason']}")}
                print(f"[Manager] executionRound={rounds}/{MAX_EXECUTION_ROUNDS} status={m['status']} progress={m['progress']}/{m['total']}")
                nxt = action_f.result()
                if reused is not None and not reuse_traced:
                    trace(ctx, f"[history-tracing] emit event=UI_VERIFICATION_HISTORY_REUSED current_total_steps={m['total']} reused_steps={reused}",
                          {"event": "UI_VERIFICATION_HISTORY_REUSED", "current_total_steps": m["total"], "reused_steps": reused})
                    reuse_traced = True
                image_cache = []
                if m["status"] == "completed":
                    history.append(m)
                    history.append({"type": "log", "content": log_f.result(), "timestamp": now_ms()})
                    summed = self.summary.summary_steps(history)
                    fault = ctx.device.check_error(FAULTLOG_DIR)
                    self.action.release_pending_touch(history)
                    remember_run(self.id, history)
                    return {"success": True, "successPart": summed["successPart"], "failPart": summed["failPart"],
                            "reason": f"{m['reason']}。{fault}" if fault else m["reason"], "id": self.id}
                if m["status"] == "error":
                    history.append(m)
                    history.append({"type": "log", "content": log_f.result(), "timestamp": now_ms()})
                    summed = self.summary.summary_steps(history)
                    remember_run(self.id, history)
                    if has_abnormal(history):
                        print("[Manager] 出现abnormal status，跳过保存stepMemory.")
                    elif fresh and first_action_name(history) == "startApp":
                        prefix = until_last_normal(history)
                        last = prefix[-1] if prefix else None
                        saved_steps = last["progress"] if last and last["type"] == "status" and last["status"] == "normal" else 0
                        self.matcher.memory(bundle).save(summed["successPart"], prefix)
                        trace(ctx, f"[history-tracing] emit event=UI_VERIFICATION_HISTORY_SAVED total_steps={m['total']} saved_steps={saved_steps}",
                              {"event": "UI_VERIFICATION_HISTORY_SAVED", "total_steps": m["total"], "saved_steps": saved_steps})
                    fault = ctx.device.check_error(FAULTLOG_DIR)
                    self.action.release_pending_touch(history)
                    return {"success": False, "successPart": summed["successPart"], "failPart": summed["failPart"],
                            "reason": f"{m['reason']}。{fault}" if fault else m["reason"], "id": self.id}
                if m["status"] == "normal":
                    history.append(m)
                    history.append({"type": "log", "content": log_f.result(), "timestamp": now_ms()})
                    self.action.execute_action(nxt, bundle, history)
                    continue
                if m["status"] == "abnormal":
                    history.append(m)
                    self.action.action(plan, bundle, history)
                    continue
                remember_run(self.id, history)
                return {"success": False, "successPart": "", "failPart": "", "reason": "Unknown status", "id": self.id}
        finally:
            pool.shutdown(wait=True)

