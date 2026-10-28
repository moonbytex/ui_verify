"""工具定义与参数校验。

对应 uiVerification.mjs：
- class Ye         L6437-6462  Ajv 编译 JSON Schema，validate({name, arguments}) 解析并校验
- pc               L6672-6877  基础触控工具：tap/doubleTap/swipe/pressKey/inputText/startApp/sleep/touchDown/touchUp
- vc / gc / Ac     L6906-7038  折叠屏 setFoldState / 横竖屏 setRotation / 鼠标 mouseClick/mouseDoubleClick/mouseScroll
- returnStatus / get_match_result / get_input_validation_result / get_summary_result
"""
from __future__ import annotations

import json


def _fn(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


def _point(desc):
    return {"type": "array", "description": desc, "items": {"type": "number"}, "minItems": 2, "maxItems": 2}


PRESS_KEY_DESC = """在设备上按下指定的按键。
通用按键（所有设备）：Home（回到桌面）、Back（返回上一级或收起软键盘）。
注意：仅当最新截图明确显示软键盘时，才能使用 Back 收起键盘。
其他按键（仅 PC/平板，且测试计划明确说明使用键盘按键操作时才调用；未明确说明时，应优先使用其他工具。）：Enter、Escape、Tab、Space、Up/Down/Left/Right、PageUp/PageDown、Delete/Backspace、["Ctrl", "A"]、["Ctrl", "Shift", "Z"]、["Shift", "Tab"]。
注意：组合键用数组表示，修饰键在前主键在后。修饰键：Ctrl、Shift、Alt。
字母 A-Z 仅在配合修饰键时使用，单独输入字母请用 inputText。"""

SWIPE_PT = "坐标，类型为数组，包含X和Y坐标，[x, y]，需要避开屏幕边缘"

BASE_TOOLS = [
    _fn("tap", "在设备屏幕上点击指定坐标", {"point": _point("点击坐标，格式为[x, y]")}, ["point"]),
    _fn("doubleTap", "在设备屏幕上双击指定坐标", {"point": _point("点击坐标，格式为[x, y]")}, ["point"]),
    _fn("swipe", "在设备屏幕上完成一次连续滑动，用于页面滚动、拖动滑块、拖拽或移动元素",
        {"startPoint": _point("滑动起始位置的" + SWIPE_PT), "endPoint": _point("滑动结束位置的" + SWIPE_PT)},
        ["startPoint", "endPoint"]),
    _fn("pressKey", PRESS_KEY_DESC, {"keyName": {"type": "array", "items": {"type": "string"},
        "description": '按键数组。示例：["Home"]、["Back"]、["Enter"]、["Ctrl", "A"]、["Ctrl", "Shift", "Z"]、["Shift", "Tab"]。'}},
        ["keyName"]),
    _fn("inputText", "在设备屏幕的指定坐标输入文本，输入文本前会清空文本；输入完成后软键盘可能保持展开状态。", {
        "point": _point("输入文本的坐标，格式为[x, y]"),
        "input": {"type": "string", "description": "要输入的文本内容，支持直接输入多行文本。"},
        "mode": {"type": "string", "enum": ["clearAndInput", "append"],
                 "description": "输入模式，clearAndInput表示先清空文本再输入，append表示在现有文本基础上追加输入"},
    }, ["point", "input", "mode"]),
    _fn("startApp", "启动指定包名的应用，或跳转到指定 URI。测试计划要求跳转到某个 URI 时，将完整链接原样传入 uri，例如 testapp://test/orders?source=buyNow&productId=p1；普通启动时不要传 uri。", {
        "bundleName": {"type": "string", "description": "要启动的应用的包名"},
        "freshStart": {"type": "boolean", "description": "是否结束已有进程，重新启动应用。首次启动或明确验证冷启动时可设为 true；应用内通过 URI 进行后续页面跳转时通常设为 false，以保留当前进程和前序业务状态。"},
        "uri": {"type": "string", "description": "可选的 HarmonyOS DeepLink URI。提供时通过 aa start -U 隐式跳转；不提供时按包名和主 Ability 使用原有方式启动应用。"},
    }, ["bundleName", "freshStart"]),
    _fn("sleep", "固定时间等待", {"duration": {"type": "number", "description": "需要等待的时间，单位为毫秒"}}, ["duration"]),
    _fn("touchDown", "开始一次原地长按手势，在设备屏幕的指定坐标按住不放；调用后设备会一直处于触摸按下状态，若测试尚未结束，下一次有效设备操作必须调用 touchUp",
        {"point": _point("按住坐标，格式为[x, y]")}, ["point"]),
    _fn("touchUp", "结束当前原地长按手势，必须与 touchDown 配对使用；无需提供坐标，将自动使用对应 touchDown 的坐标释放手指。", {}, []),
]

FOLD_LABELS = {
    "Foldable": {"open": "完全展开", "half-open": "半折/悬停", "close": "完全闭合"},
    "WideFold": {"open": "完全展开", "half-open": "半折/悬停", "close": "完全闭合"},
    "2in1_Foldable": {"open": "横屏展开", "vertical-open": "竖屏展开", "half-open": "半折/悬停", "close": "磁吸附件"},
    "TripleFold": {
        "single": "单屏", "double": "双屏", "triple": "三屏全展开",
        "left-folded-right-half-folded": "左折叠右半折", "left-half-folded-right-expanded": "左半折右展开",
        "left-expanded-right-folded": "左展开右折叠", "left-half-folded-right-folded": "左半折右折叠",
        "left-expanded-right-half-folded": "左展开右半折", "left-half-folded-right-half-folded": "左右均半折",
    },
}


def fold_tool(fold_type, states):
    desc = "、".join(f"{s}（{FOLD_LABELS[fold_type][s]}）" for s in states)
    return _fn("setFoldState", "设置折叠屏设备的折叠状态",
               {"state": {"type": "string", "enum": states, "description": f"折叠状态，支持：{desc}"}}, ["state"])


ROT_DESC = "目标方向：landscape=横屏（向左旋转90度），portrait=竖屏（恢复竖屏）"
ROTATION_TOOL = _fn("setRotation", "切换设备的横竖屏方向：landscape=横屏（向左旋转90度），portrait=竖屏（恢复竖屏）",
                    {"rotation": {"type": "string", "enum": ["landscape", "portrait"], "description": ROT_DESC}}, ["rotation"])

_BTN = {"type": "number", "minimum": 0, "maximum": 1, "multipleOf": 1, "default": 0,
        "description": "鼠标按键：0=左键，1=右键。未明确说明时使用 0 左键。"}
MOUSE_TOOLS = [
    _fn("mouseClick", "在 2in1、2in1_Foldable、tablet 设备上执行鼠标单击。先将鼠标移动到指定坐标，再点击鼠标按键。未明确说明左键或右键时，默认使用左键。",
        {"point": _point("鼠标移动并单击的位置坐标，格式为 [x, y]，坐标基于当前截图。"), "buttonId": _BTN}, ["point", "buttonId"]),
    _fn("mouseDoubleClick", "在 2in1、2in1_Foldable、tablet 设备上执行鼠标双击。当前场景默认使用左键双击；仅当任务明确要求时才指定其他按键。",
        {"point": _point("鼠标双击的位置坐标，格式为 [x, y]，坐标基于当前截图。"), "buttonId": _BTN}, ["point", "buttonId"]),
    _fn("mouseScroll", "在 2in1、2in1_Foldable、tablet 设备上执行鼠标滚轮操作。direction=down 表示向下滚动，对应鼠标向后滚动、页面下滚或切换到下一界面；direction=up 表示向上滚动，对应鼠标向前滚动、页面上滚或切换到上一界面。", {
        "point": _point("鼠标移动并滚动的位置坐标，格式为 [x, y]，坐标基于当前截图。"),
        "direction": {"type": "string", "enum": ["up", "down"], "description": "滚动方向：down=向下滚动/页面下滚/下一界面；up=向上滚动/页面上滚/上一界面。"},
        "ticks": {"type": "number", "minimum": 1, "multipleOf": 1, "description": "滚动刻度数，必须是正整数。一个刻度会转换为底层 uinput 的 15。"},
    }, ["point", "direction", "ticks"]),
]

STATUS_TOOLS = [_fn("returnStatus", "返回当前状态、原因和进度", {
    "reason": {"type": "string", "description": "处于当前状态的原因。默认不要包含完整后续计划或详细下一步操作；当 status 为 abnormal 时，reason 中必须简要说明异常现象、是否需要先恢复页面状态，以及恢复或重试方向，并且无论执行恢复动作还是重新执行原操作，都要基于最新截图重新评估当前界面；涉及坐标时，还要重新定位并计算坐标，禁止直接复用上一次操作的坐标。不要给出多步骤计划，只给出恢复或重试方向。"},
    "status": {"type": "string", "enum": ["completed", "normal", "abnormal", "error"],
               "description": "当前状态：completed=测试已完成且符合预期；normal=最近动作符合当前步骤预期，可以继续；abnormal=最近动作异常但仍可恢复、重新定位或重试；error=明确失败、偏离计划或无法恢复。"},
    "progress": {"type": "number", "description": "当前已执行或正在判断的测试步骤序号"},
    "total": {"type": "number", "description": "总步骤数"},
}, ["reason", "status", "progress", "total"])]

MATCH_TOOLS = [_fn("get_match_result", "返回严格的完整匹配或前缀匹配结果；没有满足条件的计划时返回-1", {
    "reason": {"type": "string", "description": "说明全部步骤的比对结论；不匹配时说明首次出现分叉的步骤"},
    "index": {"type": "number", "description": "匹配项在已执行计划列表中的索引（从0开始）。只有历史计划的全部步骤都满足完整匹配或严格前缀匹配时才能返回对应索引，否则必须返回-1"},
}, ["reason", "index"])]

VALIDATION_TOOLS = [_fn("get_input_validation_result", "得出用户输入测试计划的规范性检查结果，以及该计划是否能在当前设备上执行", {
    "reason": {"type": "string", "description": "是否通过的原因；如果不通过，需要说明测试计划不规范或当前设备不支持的具体原因"},
    "isValid": {"type": "boolean", "description": "测试计划是否规范，并且是否能在当前设备上执行"},
}, ["reason", "isValid"])]

SUMMARY_TOOLS = [_fn("get_summary_result", "得出用户历史操作步骤的总结结果", {
    "successPart": {"type": "string", "description": "成功的步骤总结"},
    "failPart": {"type": "string", "description": "最终仍未完成并导致测试失败的步骤；最终状态为 completed 时必须为空字符串"},
}, ["successPart", "failPart"])]


# --------------------------------------------------------------------------- #
# 简化版 JSON Schema 校验（覆盖上述 schema 用到的关键字）
# --------------------------------------------------------------------------- #
def _check(schema, v, path, errs):
    t = schema.get("type")
    if t == "object":
        if not isinstance(v, dict):
            errs.append(f"{path or '/'} must be object")
            return
        for r in schema.get("required", []):
            if r not in v:
                errs.append(f"must have required property '{r}'")
        for k, sub in schema.get("properties", {}).items():
            if k in v:
                _check(sub, v[k], f"{path}/{k}", errs)
        return
    if t == "array":
        if not isinstance(v, list):
            errs.append(f"{path} must be array")
            return
        if "minItems" in schema and len(v) < schema["minItems"]:
            errs.append(f"{path} must NOT have fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(v) > schema["maxItems"]:
            errs.append(f"{path} must NOT have more than {schema['maxItems']} items")
        for i, it in enumerate(v):
            _check(schema.get("items", {}), it, f"{path}/{i}", errs)
        return
    if t == "number":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            errs.append(f"{path} must be number")
            return
        if "minimum" in schema and v < schema["minimum"]:
            errs.append(f"{path} must be >= {schema['minimum']}")
        if "maximum" in schema and v > schema["maximum"]:
            errs.append(f"{path} must be <= {schema['maximum']}")
        if "multipleOf" in schema and v % schema["multipleOf"] != 0:
            errs.append(f"{path} must be multiple of {schema['multipleOf']}")
    elif t == "string" and not isinstance(v, str):
        errs.append(f"{path} must be string")
    elif t == "boolean" and not isinstance(v, bool):
        errs.append(f"{path} must be boolean")
    if "enum" in schema and v not in schema["enum"]:
        errs.append(f"{path} must be equal to one of the allowed values")


class ToolValidator:
    """class Ye：validate({name, arguments(str)}) -> {name, arguments(dict)}，失败抛异常。"""

    def __init__(self, tools):
        self.schemas = {t["function"]["name"]: t["function"]["parameters"] for t in tools}

    def validate(self, fn: dict) -> dict:
        name, raw = fn["name"], fn.get("arguments") or "{}"
        if name not in self.schemas:
            raise ValueError(f"未找到名为 {name} 的工具定义")
        args = json.loads(raw) if isinstance(raw, str) else raw
        errs: list[str] = []
        _check(self.schemas[name], args, "", errs)
        if errs:
            raise ValueError("Invalid arguments: " + ", ".join(errs))
        return {"name": name, "arguments": args}
