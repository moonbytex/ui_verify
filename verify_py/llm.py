"""LLM 调用层。

对应 uiVerification.mjs：
- class Zc + Yc   L9118-9189  OpenAI 兼容 /chat/completions，重试：5xx/429/408 指数退避，406 排队等待
- gi              L9190-9204  限制历史图片：最多保留 3 轮/12 张，其余替换为"已省略历史截图"
- $c              L9205-9217  默认 chat：限制图片 + tools（baseURL 含 devecostudio 时 tool_choice=required）
- ou 及辅助函数   L9218-9446  Qwen2.5-VL 模式：工具定义写进 system prompt，从文本中解析 JSON 工具调用
- $e              L6558-6620  工具调用循环：最多 3 次；无 tool_calls 时从 content 中提取；校验失败回填 tool 错误重试
- fc/So/dc/lc/Po/uc/Vo L6463-6557 从模型文本中提取 JSON 工具调用（含修复未转义引号/反斜杠）
"""
from __future__ import annotations

import json
import re
import time
import uuid

import requests

from .config import ModelConfig


class OpenAIClient:
    def __init__(self, cfg: ModelConfig, retries=3, timeout=120):
        self.cfg, self.retries, self.timeout = cfg, retries, timeout

    def create(self, body: dict, session_id: str | None = None) -> dict:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.cfg.api_key}",
                   "Chat-Id": uuid.uuid4().hex}
        if session_id:
            headers["Session-Id"] = session_id
        url = self.cfg.base_url + "/chat/completions"
        attempt = queued = 0
        resp_json, status = None, 0
        while True:
            attempt += 1
            try:
                r = requests.post(url, headers=headers, json={**body, "stream": False}, timeout=self.timeout)
                status = r.status_code
                try:
                    resp_json = r.json()
                except ValueError:
                    resp_json = {"error": {"message": r.text}}
            except requests.Timeout:
                status, resp_json = 408, {"error": {"message": f"Request timed out after {self.timeout}s"}}
            if status >= 500 or status in (429, 408):
                if attempt < self.retries:
                    delay = min(0.5 * 2 ** attempt, 10)
                    print(f"Request failed with status {status}, retrying in {delay}s ({attempt}/{self.retries})")
                    time.sleep(delay)
                    continue
                break
            if status == 406:
                attempt -= 1
                queued += 1
                time.sleep(min(2 * queued, 10))
                continue
            break
        return resp_json


def limit_images(messages, max_rounds=3, max_images=12):
    """gi()"""
    idx, total = [], 0
    for i, m in enumerate(messages):
        c = m.get("content")
        if isinstance(c, list) and any(p.get("type") == "image_url" for p in c):
            idx.append(i)
            total += sum(1 for p in c if p.get("type") == "image_url")
    if not idx or (total <= max_images and len(idx) <= max_rounds):
        return messages
    keep = max_rounds - 1 if total > max_images else max_rounds
    drop = set(idx[: max(0, len(idx) - keep)])
    out = []
    for i, m in enumerate(messages):
        if i in drop:
            m = {**m, "content": [{"type": "text", "text": "已省略历史截图"} if p.get("type") == "image_url" else p
                                  for p in m["content"]]}
        out.append(m)
    print(f"[limitImages] {total}张/{len(idx)}条 → {keep}轮")
    return out


def _message_of(resp: dict) -> dict:
    try:
        msg = resp["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        msg = None
    if not msg:
        raise RuntimeError("No message in response, cause: " + json.dumps(resp, ensure_ascii=False)[:2000])
    u = resp.get("usage") or {}
    print(f"Prompt tokens: {u.get('prompt_tokens')}, Completion tokens: {u.get('completion_tokens')}, Total tokens: {u.get('total_tokens')}")
    return msg


class DefaultChat:
    """$c"""

    def __init__(self, client: OpenAIClient, model: str):
        self.client, self.model = client, model

    def __call__(self, messages, tools, tool_choice=None, session_id=None):
        body = {"model": self.model, "messages": limit_images(messages)}
        if tools:
            body["tools"] = tools
            if "devecostudio" in self.client.cfg.base_url:
                tool_choice = "required"
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        t0 = time.time()
        resp = self.client.create(body, session_id)
        print(f"API调用耗时: {time.time() - t0:.2f} 秒")
        return _message_of(resp)


# --------------------------------------------------------------------------- #
# 从文本中提取工具调用（fc / So / dc / lc）
# --------------------------------------------------------------------------- #
def last_json_object(text: str):
    """dc / Ai：从尾部向前找最后一个配平的 {...}，返回 (json, start, end)。"""
    depth, end = 0, -1
    for i in range(len(text) - 1, -1, -1):
        ch = text[i]
        if ch == "}":
            if depth == 0:
                end = i
            depth += 1
        elif ch == "{":
            depth -= 1
            if depth == 0 and end != -1:
                return text[i: end + 1], i, end + 1
    return None


def _fix_backslashes(s):
    """Po：把非法转义 \\x 变成 \\\\x"""
    return re.sub(r'\\\\|\\([^"\\/bfnrtu])', lambda m: m.group(0) if m.group(1) is None else "\\\\" + m.group(1), s)


def _fix_unescaped_quotes(s):
    """uc：字符串内部、后面不是 , } ] : 的双引号视为未转义引号。"""
    out, in_str, i = [], False, 0
    while i < len(s):
        ch = s[i]
        if not in_str:
            out.append(ch)
            in_str = ch == '"'
            i += 1
        elif ch == "\\":
            out.append(s[i: i + 2])
            i += 2
        elif ch == '"':
            j = i + 1
            while j < len(s) and s[j] in " \t\n\r":
                j += 1
            nxt = s[j] if j < len(s) else None
            if nxt in (None, ",", "}", "]", ":"):
                out.append('"')
                in_str = False
            else:
                out.append('\\"')
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def safe_json_parse(s):
    """lc"""
    for cand in (s, _fix_backslashes(s), _fix_backslashes(_fix_unescaped_quotes(s))):
        try:
            return json.loads(cand)
        except ValueError:
            continue
    return None


def _to_tool_call(obj):
    """Vo"""
    args = obj.get("arguments")
    return {"type": "function", "id": obj.get("id") or f"call_fallback_{int(time.time()*1000)}",
            "function": {"name": obj["name"], "arguments": args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False)}}


def _parse_as_tool_call(text, names):
    """So"""
    found = last_json_object(text)
    if not found:
        return None
    obj = safe_json_parse(found[0])
    if not isinstance(obj, dict):
        return None
    tcs = obj.get("tool_calls")
    if isinstance(tcs, list) and tcs and isinstance(tcs[0], dict) and tcs[0].get("name") in names:
        return _to_tool_call(tcs[0])
    if obj.get("name") in names:
        return _to_tool_call(obj)
    return None


def extract_tool_call_from_content(content, names):
    """fc：优先 <tool_call>...</tool_call>，否则整段内容。"""
    if not content or not isinstance(content, str):
        return None
    m = re.search(r"<tool_call>\s*([\s\S]*?)\s*</tool_call>", content)
    if m:
        tc = _parse_as_tool_call(m.group(1), names)
        if tc:
            return tc
    return _parse_as_tool_call(content, names)


# --------------------------------------------------------------------------- #
# Qwen2.5-VL 模式（ou）：不使用原生 tools，工具描述写入 system prompt
# --------------------------------------------------------------------------- #
REPEAT_LIMIT = 5  # Nt


def _tools_prompt(tools, tool_choice):
    """tu"""
    names, blocks = [], []
    for t in tools:
        f = t["function"]
        names.append(f["name"])
        blocks.append(f"### {f['name']}\n描述: {f['description']}\n参数schema:\n"
                      + json.dumps(f.get("parameters") or {"type": "object"}, ensure_ascii=False, indent=2))
    must = tool_choice in ("required", "auto", None)
    lines = [
        "# 工具调用规则（必须严格遵守）", "",
        f"你只能调用以下工具: [{', '.join(names)}]",
        "严禁调用未在上述列表中的工具（如 terminate、finish、end、done 等均为非法工具名）。", "",
        "当测试计划要求「启动应用」「打开应用」时，必须调用 startApp 并传入给定的包名，禁止使用 tap、swipe 在桌面上查找并点击应用图标。" if "startApp" in names else "",
        "",
        "你必须调用一个工具。禁止输出不包含工具调用的纯文本回复。" if must else "",
        "", "## 输出格式",
        "你的回复必须包含且仅包含一个 JSON 对象（可以在 JSON 前写思考内容），格式如下:",
        '{"tool_calls":[{"id":"call_<唯一数字>","name":"<工具名>","arguments":{<参数>}}]}',
        "", "## 示例", "假设需要点击坐标(500,300)，正确的回复:", "需要点击目标位置",
        '{"tool_calls":[{"id":"call_1","name":"tap","arguments":{"point":[500,300]}}]}',
        "", "## 可用工具", *blocks,
    ]
    return "\n".join(l for l in lines if l)


def _flatten_tool_messages(messages):
    """eu：assistant.tool_calls -> 文本 JSON；tool -> user '[工具执行结果] ...'"""
    out = []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            tc = m["tool_calls"][0]
            try:
                args = json.loads(tc["function"]["arguments"])
            except (ValueError, TypeError):
                args = {}
            js = json.dumps({"tool_calls": [{"id": tc["id"], "name": tc["function"]["name"], "arguments": args}]}, ensure_ascii=False)
            c = m.get("content") if isinstance(m.get("content"), str) else ""
            out.append({"role": "assistant", "content": f"{c}\n\n{js}" if c else js})
        elif m["role"] == "tool":
            out.append({"role": "user", "content": f"[工具执行结果] {m.get('content', '')}"})
        else:
            out.append(m)
    return out


def _parse_text_tool_calls(text, names):
    """yi"""
    if not text or not isinstance(text, str):
        return None
    t = text.strip()
    found = last_json_object(t)
    if not found:
        return None
    try:
        obj = json.loads(found[0])
    except ValueError:
        return None
    tcs = obj.get("tool_calls") if isinstance(obj, dict) else None
    if not isinstance(tcs, list) or not tcs:
        return None
    valid = [c for c in tcs if isinstance(c, dict) and c.get("name") in names]
    if not valid:
        return {"ok": False, "invalid": [c.get("name", "") for c in tcs if isinstance(c, dict) and c.get("name")]}
    calls = []
    for i, c in enumerate(valid):
        cid = c.get("id") if isinstance(c.get("id"), str) and c["id"].startswith("call_") else f"call_{int(time.time()*1000)}_{i}"
        a = c.get("arguments")
        calls.append({"type": "function", "id": cid, "function": {"name": c["name"], "arguments": a if isinstance(a, str) else json.dumps(a or {}, ensure_ascii=False)}})
    rest = "\n".join(p for p in (t[: found[1]].strip(), t[found[2]:].strip()) if p).strip() or None
    return {"ok": True, "tool_calls": calls, "content": rest}


def _repeat_hint(messages):
    """nu：最近 5 次 assistant 调用了完全相同的操作时注入提醒。"""
    sigs = []
    for m in [m for m in messages if m["role"] == "assistant"][-REPEAT_LIMIT:]:
        f = last_json_object(m["content"]) if isinstance(m.get("content"), str) else None
        try:
            tc = json.loads(f[0])["tool_calls"][0] if f else None
            sigs.append(f"{tc['name']}:{json.dumps(tc.get('arguments') or {})}" if tc and tc.get("name") else None)
        except (ValueError, KeyError, IndexError, TypeError):
            sigs.append(None)
    if len(sigs) == REPEAT_LIMIT and sigs[0] is not None and all(s == sigs[0] for s in sigs):
        return messages + [{"role": "user", "content": f"[系统提示] 相同操作已连续执行{REPEAT_LIMIT}次，界面可能未发生变化，请重新分析当前界面状态，判断测试是否失败或尝试其他操作。"}]
    return messages


class QwenChat(DefaultChat):
    """ou"""

    def _once(self, body, session_id):
        for attempt in range(4):
            t0 = time.time()
            resp = self.client.create(body, session_id)
            print(f"API调用耗时: {time.time() - t0:.2f} 秒")
            try:
                msg = resp["choices"][0]["message"]
                if msg:
                    if msg.get("tool_calls") == []:
                        msg.pop("tool_calls")
                    return msg
            except (KeyError, IndexError, TypeError):
                pass
            if attempt == 3:
                raise RuntimeError("No message in response after retries")
            time.sleep((attempt + 1) * 2)

    def _retry_with(self, body, names, session_id):
        msg = self.client.create(body, session_id)["choices"][0]["message"]
        p = _parse_text_tool_calls(msg.get("content"), names) if msg and msg.get("content") else None
        if p and p["ok"]:
            return {"role": "assistant", "content": p["content"], "tool_calls": p["tool_calls"]}
        return msg

    def __call__(self, messages, tools, tool_choice=None, session_id=None):
        names = {t["function"]["name"] for t in tools}
        body = {"model": self.model, "messages": messages}
        if tools:
            tp = _tools_prompt(tools, tool_choice)
            flat = _flatten_tool_messages(messages)
            if flat and flat[0]["role"] == "system":
                sys = flat[0]["content"] if isinstance(flat[0]["content"], str) else ""
                body["messages"] = [{"role": "system", "content": f"{sys}\n\n{tp}" if sys else tp}, *flat[1:]]
            else:
                body["messages"] = [{"role": "system", "content": tp}, *flat]
            body["messages"] = _repeat_hint(body["messages"])
        body["messages"] = limit_images(body["messages"])
        msg = self._once(body, session_id)
        if tools and msg.get("content"):
            p = _parse_text_tool_calls(msg["content"], names)
            if p and p["ok"]:
                first_swipe = p["tool_calls"][0]["function"]["name"] == "swipe"
                if first_swipe and not any(m["role"] == "assistant" for m in body["messages"]):
                    body["messages"] = body["messages"] + [
                        {"role": "assistant", "content": msg["content"]},
                        {"role": "user", "content": "[提示] 你正在使用 swipe 操作。如果你的目的是启动应用，请调用 startApp 工具，禁止使用 swipe 在桌面查找并点击应用图标。"}]
                    r = self._retry_with(body, names, session_id)
                    if r:
                        return r
                return {"role": "assistant", "content": p["content"], "tool_calls": p["tool_calls"]}
            if p and not p["ok"]:
                body["messages"] = body["messages"] + [
                    {"role": "assistant", "content": msg["content"]},
                    {"role": "user", "content": f"[工具调用错误] 你调用了不存在的工具: [{', '.join(p['invalid'])}]。可用工具为: [{', '.join(names)}]，请重新调用正确的工具。"}]
                r = self._retry_with(body, names, session_id)
                if r:
                    return r
        return msg


# --------------------------------------------------------------------------- #
# $e：带校验的工具调用循环
# --------------------------------------------------------------------------- #
def call_with_tools(ctx, agent_name, tools, validator, messages, retry=3,
                    message_when_no_tool_call=None, check_function=None):
    """返回 (result_message, tool_call | None, parsed | None)。

    - 每轮调用 ctx.chat；无原生 tool_calls 时尝试从 content 提取 JSON 工具调用
    - 仍无工具调用：若未设置 message_when_no_tool_call 直接返回（ActionAgent 视为"无操作"），
      否则追加 assistant + user 提醒后重试
    - 参数校验 / check_function 失败：追加 assistant(tool_calls) + tool(错误信息) 后重试
    """
    msgs = list(messages)
    names = {t["function"]["name"] for t in tools}
    result = {"role": "assistant", "content": ""}
    for count in range(1, retry + 1):
        ctx.logger.llm_start(agent_name)
        result = ctx.chat(msgs, tools, None, ctx.session_id)
        ctx.logger.llm_end(agent_name, result)
        tcs = result.get("tool_calls") or []
        if not tcs:
            tc = extract_tool_call_from_content(result.get("content"), names)
            if tc is None:
                if message_when_no_tool_call is None:
                    return result, None, None
                print(f"[{agent_name}] no tool call in result (count {count})")
                msgs += [{"role": "assistant", "content": result.get("content")},
                         {"role": "user", "content": message_when_no_tool_call}]
                continue
        else:
            tc = tcs[0]
        if tc.get("type", "function") != "function":
            raise RuntimeError("Tool call is not a function")
        try:
            parsed = validator.validate(tc["function"])
            if check_function:
                err = check_function(parsed)
                if err:
                    raise ValueError(err)
        except Exception as e:  # noqa: BLE001
            print(f"[{agent_name}] error in validate: {e}")
            msgs += [{"role": "assistant", "content": result.get("content"),
                      "tool_calls": [{"type": "function", "id": tc["id"], "function": tc["function"]}]},
                     {"role": "tool", "content": f"Error: {e}", "tool_call_id": tc["id"]}]
            continue
        return result, tc, parsed
    return result, None, None
