"""动作执行与历史 -> 消息转换。

对应 uiVerification.mjs：
- mi    L7060-7297  执行一个已解析的工具调用，坐标 999 归一化 -> 屏幕像素，并写入 history
- Ec    L7298-7311  ActionAgent 历史中 tool 消息的回执文本
- Ic    L7312-7367  ActionAgent 历史转换：action => assistant(tool_calls)+tool；status => user 文本
- vi    L7368-7443  action 记录 -> {name, arguments}（用于还原 tool_call / FakeAction 重放）
- Cc    L7852-7930  StatusAgent 历史中 action 的描述文本
- qc    L7931-7981  StatusAgent 历史转换：status => assistant(returnStatus)+tool；action => user 文本
- ea    L1889-1904  按键名规范化
"""
from __future__ import annotations

import json
import time

from .history import last_image_b64, last_image_item, now_ms, pending_touch_down
from .imaging import data_uri, image_size

KEY_NAMES = ["Home", "Back", "Enter", "Escape", "Tab", "Space", "Up", "Down", "Left", "Right",
             "Delete", "Backspace", "PageUp", "PageDown", "Ctrl", "Shift", "Alt"]


def normalize_keys(keys):
    """ea"""
    if not keys:
        raise ValueError("按键数组不能为空")
    out = []
    for k in keys:
        n = None
        if len(k) == 1 and "A" <= k.upper() <= "Z":
            n = k.upper()
        else:
            n = next((x for x in KEY_NAMES if x.lower() == k.lower()), None)
        if n is None:
            raise ValueError(f'未知按键: "{k}"，输入: "{"+".join(keys)}"')
        out.append(n)
    if len(out) == 1 and len(out[0]) == 1:
        raise ValueError(f'字母键 "{out[0]}" 必须配合修饰键使用（如 ["Ctrl", "{out[0]}"]），单独输入字母请使用 inputText 工具')
    return out


def action_to_call(a):
    """vi"""
    n = a["name"]
    keys = {
        "tap": ["point"], "doubleTap": ["point"], "swipe": ["startPoint", "endPoint"],
        "mouseClick": ["point", "buttonId"], "mouseDoubleClick": ["point", "buttonId"],
        "mouseScroll": ["point", "direction", "ticks"], "pressKey": ["keyName"],
        "inputText": ["point", "input", "mode"], "sleep": ["duration"], "touchDown": ["point"],
        "touchUp": [], "setFoldState": ["state"], "setRotation": ["rotation"],
    }
    if n == "startApp":
        args = {"bundleName": a["bundleName"], "freshStart": a["freshStart"]}
        if a.get("uri") is not None:
            args["uri"] = a["uri"]
        return {"name": n, "arguments": args}
    return {"name": n, "arguments": {k: a[k] for k in keys.get(n, [])}}


def execute_action(ctx, call_id, parsed, reason, history):
    """mi：执行动作并把 action 记录 push 到 history。"""
    name, args = parsed["name"], parsed["arguments"]
    ctx.logger.device_action(name)
    dev, loc = ctx.device, ctx.locator
    img = last_image_b64(history)
    if not img:
        raise RuntimeError("ActionAgent: No image found in history for point conversion")
    img_size = image_size(img)
    item = last_image_item(history)
    screen = item.get("screenSize") if item and item.get("screenSize") else list(dev.get_screen_size())

    def px(p):
        return loc.point_interp(p, img_size, screen)

    def fb(s):
        return reason or s

    rec = {"id": call_id, "type": "action", "name": name}
    if name in ("tap", "doubleTap", "touchDown"):
        c, f = args["point"]
        dev_fn = {"tap": dev.tap, "doubleTap": dev.double_tap, "touchDown": dev.touch_down}[name]
        dev_fn(*px(args["point"]))
        rec.update(point=args["point"], reason=fb(f"调用 {name}({c}, {f})"))
    elif name == "swipe":
        c, f = args["startPoint"]
        d, y = args["endPoint"]
        (x1, y1), (x2, y2) = px(args["startPoint"]), px(args["endPoint"])
        dev.swipe(x1, y1, x2, y2)
        rec.update(startPoint=args["startPoint"], endPoint=args["endPoint"],
                   reason=fb(f"调用 swipe({c}, {f}, {d}, {y})"))
    elif name in ("mouseClick", "mouseDoubleClick"):
        c, f = args["point"]
        btn = args.get("buttonId", 0)
        if btn not in (0, 1):
            msg = "Invalid mouse click buttonId" if name == "mouseClick" else "Invalid mouse buttonId"
            raise ValueError(f"{msg}: {btn}")
        (dev.mouse_click if name == "mouseClick" else dev.mouse_double_click)(*px(args["point"]), int(btn))
        rec.update(point=args["point"], buttonId=int(btn), reason=fb(f"调用 {name}({c}, {f}, {int(btn)})"))
    elif name == "mouseScroll":
        c, f = args["point"]
        d, y = args["direction"], args["ticks"]
        dev.mouse_scroll(*px(args["point"]), d, int(y))
        rec.update(point=args["point"], direction=d, ticks=int(y),
                   reason=fb(f"调用 mouseScroll({c}, {f}, {d}, {y})"))
    elif name == "pressKey":
        try:
            keys = normalize_keys(args["keyName"])
            dev.press_key(keys)
            rec.update(keyName=keys, error=None, reason=fb(f"调用 pressKey({js_json(keys)})"))
        except Exception as e:  # noqa: BLE001
            rec.update(keyName=[], error=str(e), reason=fb(f"调用 pressKey({js_json(args['keyName'])})"))
    elif name == "inputText":
        c, f = args["point"]
        d, y = args["input"], args["mode"]
        dev.input_text(*px(args["point"]), d, y)
        rec.update(point=args["point"], input=d, mode=y, reason=fb(f"调用 inputText({c}, {f}, {d}, {y})"))
    elif name == "startApp":
        c, f = args["bundleName"], args["freshStart"]
        d = args.get("uri")
        err = dev.start_app(c, f, d)
        fresh = "true" if f else "false"
        rec.update(bundleName=c, freshStart=f, error=err,
                   reason=fb(f"调用 startApp({c}, {fresh}{', ' + d if d else ''})"))
        if d is not None:
            rec["uri"] = d
    elif name == "sleep":
        time.sleep(args["duration"] / 1000)
        rec.update(duration=args["duration"], reason=reason or f"等待 {args['duration']} ms")
    elif name == "touchUp":
        down = pending_touch_down(history)
        if not down:
            raise RuntimeError("ActionAgent: No touchDown action found in history for touchUp")
        dev.touch_up(*px(down["point"]))
        rec["reason"] = reason or "调用 touchUp"
    elif name in ("setFoldState", "setRotation"):
        key = "state" if name == "setFoldState" else "rotation"
        try:
            (dev.set_fold_state if name == "setFoldState" else dev.set_rotation)(args[key])
            rec["error"] = None
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)
        rec.update({key: args[key], "reason": reason or f"调用 {name}({args[key]})"})
    rec["timestamp"] = now_ms()
    history.append(rec)


def _image_msg(item):
    return {"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_uri(b)}} for b in item["base64List"]]}


def action_receipt(a):
    """Ec"""
    n = a["name"]
    if n == "touchDown":
        return "Action executed。【提醒】调用 touchDown 操作后，设备会一直处于触摸按下状态，后续必须调用 touchUp 使用，来实现长按操作。"
    if n == "inputText":
        return "Action executed。"
    if n == "setFoldState":
        return f"Action failed: {a['error']}" if a.get("error") else f"Action executed。折叠屏状态已切换为 {a['state']}"
    if n == "setRotation":
        return f"Action failed: {a['error']}" if a.get("error") else f"Action executed。屏幕方向已切换为 {'横屏' if a['rotation'] == 'landscape' else '竖屏'}"
    return "Action executed"


def history_for_action(history):
    """Ic"""
    out = []
    for h in history:
        t = h["type"]
        if t == "status":
            out.append({"role": "user", "content": "当前状态：" + h["status"] + " 原因：" + h["reason"]})
        elif t == "image":
            out.append(_image_msg(h))
        elif t == "action":
            if h["name"] != "none":
                c = action_to_call(h)
                out.append({"role": "assistant", "content": h["reason"], "tool_calls": [
                    {"type": "function", "id": h["id"], "function": {"name": c["name"], "arguments": js_json(c["arguments"])}}]})
                out.append({"role": "tool", "content": action_receipt(h), "tool_call_id": h["id"]})
            else:
                out.append({"role": "assistant", "content": h["reason"]})
    return out


def js_json(v) -> str:
    """等价 JSON.stringify（紧凑、保留非 ASCII）。"""
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def _result(a):
    return f"失败，错误信息：{a['error']}" if a.get("error") else "成功"


def _err_suffix(a):
    return f"，失败，错误信息：{a['error']}" if a.get("error") else ""


def _rot(a):
    return "横屏" if a["rotation"] == "landscape" else "竖屏"


def _uri(a):
    return f"，URI 为{a['uri']}" if a.get("uri") else ""


def status_action_text(t):
    """Cc：StatusAgent 历史中 action 的描述（逐字对应原文案）。"""
    n, r = t["name"], t["reason"]
    p = t.get("point")
    if n == "tap":
        return f"思考：{r}；执行操作：单击，坐标为({p[0]}, {p[1]})"
    if n == "doubleTap":
        return f"思考：{r}；执行操作：双击，坐标为({p[0]}, {p[1]})"
    if n == "swipe":
        s, e = t["startPoint"], t["endPoint"]
        return f"思考：{r}；执行操作：滑动，起始坐标为({s[0]}, {s[1]}), 结束坐标为({e[0]}, {e[1]})"
    if n == "mouseClick":
        return f"思考：{r}；执行操作：鼠标单击，坐标为({p[0]}, {p[1]})，按键为{'左键' if t['buttonId'] == 0 else '右键'}"
    if n == "mouseDoubleClick":
        return f"思考：{r}；执行操作：鼠标双击，坐标为({p[0]}, {p[1]})，按键ID为{t['buttonId']}"
    if n == "mouseScroll":
        return f"思考：{r}；执行操作：鼠标{'向下' if t['direction'] == 'down' else '向上'}滚动，坐标为({p[0]}, {p[1]})，刻度数为{t['ticks']}"
    if n == "pressKey":
        return f"思考：{r}；执行操作：按键，按下{js_json(t['keyName'])}键, 执行结果：{_result(t)}"
    if n == "inputText":
        return f"思考：{r}；执行操作：输入文本，坐标为({p[0]}, {p[1]}), 输入内容为\"{t['input']}，输入模式为{t['mode']}\""
    if n == "startApp":
        return f"思考：{r}；执行操作：{'重新' if t['freshStart'] else ''}启动应用，包名为{t['bundleName']}{_uri(t)}，执行结果：{_result(t)}"
    if n == "sleep":
        return f"思考：{r}；执行操作：等待 {t['duration']} ms"
    if n == "none":
        return f"思考：{r}；不执行任何操作"
    if n == "touchDown":
        return f"思考：{r}；执行操作：按住不放，坐标为({p[0]}, {p[1]})"
    if n == "touchUp":
        return f"思考：{r}；执行操作：放开手指"
    if n == "setFoldState":
        return f"思考：{r}；执行操作：设置折叠屏状态为{t['state']}{_err_suffix(t)}"
    if n == "setRotation":
        return f"思考：{r}；执行操作：切换屏幕方向为{_rot(t)}{_err_suffix(t)}"
    return None


def history_for_status(history):
    """qc"""
    out = []
    for h in history:
        t = h["type"]
        if t == "status":
            args = {"reason": h["reason"], "status": h["status"], "progress": h["progress"], "total": h["total"]}
            out.append({"role": "assistant", "content": h["reason"], "tool_calls": [
                {"type": "function", "id": h["id"], "function": {"name": "returnStatus", "arguments": js_json(args)}}]})
            out.append({"role": "tool", "content": "received", "tool_call_id": h["id"]})
        elif t == "action":
            out.append({"role": "user", "content": status_action_text(h)})
        elif t == "image":
            out.append(_image_msg(h))
    return out


def summary_action_text(o):
    """SummaryAgent.formatHistory 中 action 的文案（逐字对应原文案）。"""
    n, r = o["name"], o["reason"]
    p = o.get("point")
    if n == "tap":
        return f"执行操作：单击，坐标为({p[0]}, {p[1]})，原因：{r}\n"
    if n == "doubleTap":
        return f"执行操作：双击，坐标为({p[0]}, {p[1]})，原因：{r}\n"
    if n == "swipe":
        s, e = o["startPoint"], o["endPoint"]
        return f"执行操作：滑动，起始坐标为({s[0]}, {s[1]}), 结束坐标为({e[0]}, {e[1]}), 原因：{r}\n"
    if n == "mouseClick":
        return f"执行操作：鼠标单击，坐标为({p[0]}, {p[1]})，按键ID为{o['buttonId']}，原因：{r}\n"
    if n == "mouseDoubleClick":
        return f"执行操作：鼠标双击，坐标为({p[0]}, {p[1]})，按键ID为{o['buttonId']}，原因：{r}\n"
    if n == "mouseScroll":
        return f"执行操作：鼠标{'向下' if o['direction'] == 'down' else '向上'}滚动，坐标为({p[0]}, {p[1]})，刻度数为{o['ticks']}，原因：{r}\n"
    if n == "pressKey":
        return f"执行操作：按键，按下{js_json(o['keyName'])}键，原因：{r}\n, 执行结果：{_result(o)}"
    if n == "inputText":
        return f"执行操作：输入文本，坐标为({p[0]}, {p[1]}), 输入内容为\"{o['input']}\"，原因：{r}，输入模式为{o['mode']}\n"
    if n == "startApp":
        return f"执行操作：{'重新' if o['freshStart'] else ''}启动应用，包名为{o['bundleName']}{_uri(o)}，执行结果：{_result(o)}，原因：{r}\n"
    if n == "sleep":
        return f"执行操作：等待 {o['duration']} ms，原因：{r}\n"
    if n == "touchDown":
        return f"执行操作：按住不放，坐标为({p[0]}, {p[1]})，原因：{r}\n"
    if n == "touchUp":
        return f"执行操作：放开手指，原因：{r}\n"
    if n == "none":
        return f"不执行任何操作，原因：{r}\n"
    if n == "setFoldState":
        return f"执行操作：设置折叠屏状态为{o['state']}{_err_suffix(o)}，原因：{r}\n"
    if n == "setRotation":
        return f"执行操作：切换屏幕方向为{_rot(o)}{_err_suffix(o)}，原因：{r}\n"
    return ""


def history_for_summary(history):
    """SummaryAgent.formatHistory：连续文本合并为一条 user 消息，每张图片单独一条。"""
    out = []

    def text(s):
        if out and isinstance(out[-1]["content"], str):
            out[-1]["content"] += s
        else:
            out.append({"role": "user", "content": s})

    for h in history:
        if h["type"] == "status":
            text(f"\n当前状态：{h['status']} 原因：{h['reason']}\n")
        elif h["type"] == "action":
            text(summary_action_text(h))
        elif h["type"] == "image":
            for b in h["base64List"]:
                out.append({"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_uri(b)}}]})
    return out