"""运行日志与本地可视化。

对应 uiVerification.mjs：
- class _o  L1343-1493  sequence-log-<时间>/history.md + log.md + imgN.jpeg，最多保留 50 个目录
- vs        L1507-1519  history.push 时同步写日志
- gs / As   L1520-1536  记录 LLM 调用和设备调用

额外生成 index.html + events.json/events.js，用浏览器打开即可实时查看每一步。
"""
from __future__ import annotations

import base64
import json
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from .imaging import image_ext

MAX_LOG_FOLDERS = 50
PREFIX = "sequence-log-"
VIEWER = Path(__file__).with_name("viewer.html")


class RunLogger:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.start = time.time()
        self.dir = self.root / (PREFIX + datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3])
        self.dir.mkdir(parents=True)
        self._cleanup()
        self.img_count = 0
        self.events: list[dict] = []
        self.lock = threading.Lock()
        shutil.copyfile(VIEWER, self.dir / "index.html")
        self._flush()

    def _cleanup(self):
        dirs = sorted(p for p in self.root.iterdir() if p.is_dir() and p.name.startswith(PREFIX))
        for p in dirs[: max(0, len(dirs) - MAX_LOG_FOLDERS)]:
            shutil.rmtree(p, ignore_errors=True)

    def t(self) -> str:
        return f"+{time.time() - self.start:.2f}s"

    def _md(self, text, name="history.md"):
        with self.lock:
            with open(self.dir / name, "a", encoding="utf-8") as f:
                f.write(text)

    def _event(self, kind, **data):
        with self.lock:
            self.events.append({"kind": kind, "time": self.t(), **data})
            self._flush()

    def _flush(self):
        js = json.dumps(self.events, ensure_ascii=False)
        (self.dir / "events.json").write_text('{"events":' + js + "}", "utf-8")
        # file:// 打开时 fetch 可能被禁止，额外写一份 JS 版本供 <script> 加载
        (self.dir / "events.js").write_text("window.__EVENTS__=" + js, "utf-8")

    # ------------------------- 调用点 -------------------------
    def call(self, name, args):
        # 与 addCall 一致：只落 string / number / boolean，布尔值写成 true/false
        lines = []
        for a in args:
            if isinstance(a, bool):
                lines.append("true" if a else "false")
            elif isinstance(a, (str, int, float)):
                lines.append(str(a))
        self._md(f"## {name} {self.t()} Call\n" + "".join(f"{a}\n" for a in lines))
        self._event("call", name=name, args=lines)

    def device_call(self, name, args):
        self._md(f"`{self.t()} Device {name}({', '.join(json.dumps(a, ensure_ascii=False, separators=(',', ':')) for a in args)})`\n")

    def device_action(self, name):
        self._md(f"**Interface Operation: `{name}`**\n")

    def llm_start(self, agent):
        self._md(f"\n## {agent} LLM Start {self.t()}\n")

    def llm_end(self, agent, msg):
        self._md(f"## {agent} LLM End {self.t()} Chat Message\n\n")
        content = msg.get("content") if isinstance(msg.get("content"), str) else ""
        if content.strip():
            self._md(f"### Content\n{content}\n")
        tool = None
        if msg.get("tool_calls"):
            f = msg["tool_calls"][0]["function"]
            tool = {"name": f["name"], "arguments": f.get("arguments")}
            self._md(f"### Tool Call\n{f['name']}\n{f.get('arguments')}\n")
        self._event("llm", agent=agent, content=content, tool=tool)

    def fake_action(self, name, reason):
        self._md(f"\n### FakeAction\n**Action:** {name}\n**Reason:** {reason}\n\n")
        self._event("fake_action", name=name, reason=reason)

    def fake_match(self, diff, ok):
        self._md(f"**Image Pixel Contrast:** {'pass' if ok else 'fail'} (diff={diff:.4f})\n\n")

    def info(self, text):
        print(text)
        self._event("info", text=text)

    def result(self, result: dict):
        (self.dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
        self._event("result", result=result)

    # ------------------------- history 同步 -------------------------
    def add_history(self, item):
        typ = item["type"]
        if typ == "image":
            files = []
            for b64 in item["base64List"]:
                self.img_count += 1
                fn = f"img{self.img_count}.{image_ext(b64)}"
                (self.dir / fn).write_bytes(base64.b64decode(b64))
                self._md(f"![{fn}]({fn})\n\n")
                files.append(fn)
            self._event("image", files=files)
        elif typ == "log":
            if item["content"]:
                self._md(item["content"], "log.md")
        elif typ == "status":
            keys = ("status", "reason", "progress", "total", "abnormalRetryCount")
            self._event("status", **{k: item.get(k) for k in keys})
        elif typ == "action":
            data = {k: v for k, v in item.items() if k not in ("type", "id", "timestamp")}
            self._event("action", **data)


class History(list):
    """vs()：append 时同步写日志。"""

    def __init__(self, logger: RunLogger):
        super().__init__()
        self.logger = logger

    def append(self, item):
        self.logger.add_history(item)
        super().append(item)
