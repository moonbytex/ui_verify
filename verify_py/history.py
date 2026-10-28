"""执行历史 / 稳定截图 / 步骤记忆。

history 是一个 list[dict]，每项 type ∈ {image, status, action, log}，与原实现结构一致：
  image : {base64List, screenSize, timestamp}
  status: {id, status, reason, progress, total, abnormalRetryCount, maximalAbnormalRetries, timestamp}
  action: {id, name, reason, timestamp, ...参数(point/startPoint/endPoint/keyName/...)}
  log   : {content, timestamp}

对应 uiVerification.mjs：
- Dr / zs / Xs / Ns / Ds   L1704-1741  历史查询
- Js/Ws/ks/Gs/Zs/Ys        L1794-1855  从截图缓存中挑选"稳定"的关键帧（最多 6 张）
- stepMemory (Jt/ni/bs/Us/Ks/Ms)  L1588-1673  成功前缀步骤的持久化与复用（version 1.0.2）
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

DIFF_EPS = 1e-3  # oi


def now_ms() -> int:
    return int(time.time() * 1000)


def last_image_b64(history):
    """Dr"""
    for h in reversed(history):
        if h["type"] == "image" and h["base64List"]:
            return h["base64List"][-1]
    return None


def last_image_item(history):
    """zs"""
    for h in reversed(history):
        if h["type"] == "image":
            return h
    return None


def until_last_normal(history):
    """Xs：截到最后一个 normal status（含）"""
    for i in range(len(history) - 1, -1, -1):
        h = history[i]
        if h["type"] == "status" and h["status"] == "normal":
            return history[: i + 1]
    return []


def has_abnormal(history):
    """Ns"""
    return any(h["type"] == "status" and h["status"] == "abnormal" for h in history)


def first_action_name(history):
    """Ds"""
    for h in history:
        if h["type"] == "action":
            return h["name"]
    return None


def pending_touch_down(history):
    """Cr：最近一个有效 action 是 touchDown 则返回它。"""
    for h in reversed(history):
        if h["type"] == "action":
            if h["name"] == "none":
                continue
            return h if h["name"] == "touchDown" else None
    return None


# --------------------------- 稳定截图挑选 --------------------------- #
def _drop_leading_static(frames, eps=DIFF_EPS):
    """Js：丢掉开头没有变化的帧（全部无变化则只留最后一张）。"""
    if not frames:
        return []
    for i, f in enumerate(frames):
        if f["diff"] >= eps:
            return frames[i:]
    return [frames[-1]]


def _sample_by_interval(frames, interval=500):
    """Ws：至少间隔 500ms 采样一帧，并保证包含最后一帧。"""
    if not frames:
        return []
    fs = sorted(frames, key=lambda f: f["timestamp"])
    out, last = [fs[0]], fs[0]["timestamp"]
    for f in fs[1:]:
        if f["timestamp"] >= last + interval:
            out.append(f)
            last = f["timestamp"]
    if out[-1] is not fs[-1]:
        out.append(fs[-1])
    return out


def _keep_changed(frames, eps=DIFF_EPS):
    """ks：保留最后一帧，以及"下一帧相对它有变化"的帧。"""
    if not frames:
        return []
    out = [frames[-1]]
    for i in range(len(frames) - 2, -1, -1):
        if frames[i + 1]["diff"] >= eps:
            out.append(frames[i])
    return list(reversed(out))


def _cap(frames, limit=6):
    """Gs：超过 6 张时保留前 3 张 + 中间 diff 最大的 2 张 + 最后 1 张。"""
    if len(frames) <= limit:
        return frames
    head, tail = frames[:3], frames[-1:]
    mid = sorted(frames[3:-1], key=lambda f: -f["diff"])[:2]
    return sorted(head + mid + tail, key=lambda f: f["timestamp"])


def _is_stable(frames, window=800):
    """Ys：最后一帧无变化，且之前连续无变化帧覆盖 >= 800ms。"""
    if len(frames) < 2:
        return False
    r = len(frames) - 1
    if frames[r]["diff"] > 0.01:
        return False
    n = r - 1
    while n > 0 and frames[n]["diff"] < 0.01:
        n -= 1
        if frames[r]["timestamp"] - frames[n]["timestamp"] >= window:
            return True
    return False


_debug_seq = 0


def _dump_stable_debug(frames, keyframes):
    """Hs/Qs：UI_VERIFY_DEBUG=1 时把本轮缓存帧落到 getStableImages-debug。"""
    global _debug_seq
    if os.environ.get("UI_VERIFY_DEBUG") not in ("1", "true") or not frames:
        return
    import base64
    from datetime import datetime, timezone

    from .imaging import image_ext

    _debug_seq += 1
    root = os.environ.get("UI_VERIFY_LOG_PATH") or os.environ.get("LOG_PATH") or os.path.join(".", "logs")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3] + "Z"
    folder = Path(root) / "getStableImages-debug" / f"{stamp}-call-{_debug_seq:04d}"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        keys = {f["timestamp"] for f in keyframes}
        manifest = []
        for i, f in enumerate(frames):
            ext = image_ext(f["base64"])
            name = f"{i:03d}_diff-{f['diff']:.4f}_{'key' if f['timestamp'] in keys else 'frame'}_{f['timestamp']}.{ext}"
            (folder / name).write_bytes(base64.b64decode(f["base64"]))
            manifest.append({"index": i, "filename": name, "timestamp": f["timestamp"], "diff": f["diff"],
                             "isKeyframe": f["timestamp"] in keys, "screenSize": f.get("screenSize")})
        doc = {"callIndex": _debug_seq, "rawCacheSize": len(frames), "keyframeCount": len(keyframes),
               "keyframeTimestamps": [f["timestamp"] for f in keyframes], "frames": manifest}
        (folder / "manifest.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), "utf-8")
        print(f"[getStableImages debug] dumped {len(frames)} frames ({len(keyframes)} keyframes) to {folder}")
    except Exception as e:  # noqa: BLE001
        print("[getStableImages debug] failed to dump frames:", e)


def get_stable_images(device, cache):
    """Zs：最多 3 秒内持续取截图直到画面稳定，然后挑选关键帧。"""
    frames = list(cache)
    deadline = time.time() + 3
    while time.time() < deadline:
        print("getStableImages获取截图")
        frames.extend(device.screenshot())
        if _is_stable(frames):
            break
    stable = _cap(_keep_changed(_sample_by_interval(_drop_leading_static(frames))))
    _dump_stable_debug(frames, stable)
    return frames, stable


# --------------------------- 步骤记忆 --------------------------- #
MEMORY_VERSION = "1.0.2"
MAX_MEMORY_FILES = 20  # Ps
MAX_PLANS_PER_FILE = 10  # Ss


class StepMemory:
    def __init__(self, log_root: Path, session_id: str | None, device_name: str, bundle: str):
        self.dir = Path(log_root) / "stepMemory"
        key = f"{session_id or 'default'}_{re.sub(r'[^a-zA-Z0-9]', '_', device_name)}_{bundle}"
        self.path = self.dir / f"{key}.json"

    def _read(self):
        try:
            if not self.path.exists():
                return None
            d = json.loads(self.path.read_text("utf-8"))
            if d.get("version") != MEMORY_VERSION:
                self.path.unlink()
                return None
            return d
        except Exception:  # noqa: BLE001
            self.path.unlink(missing_ok=True)
            return None

    def _write(self, data):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"version": MEMORY_VERSION, "data": data}, ensure_ascii=False), "utf-8")
        files = sorted(self.dir.iterdir(), key=lambda p: -p.stat().st_mtime)
        for p in files[MAX_MEMORY_FILES:]:
            p.unlink(missing_ok=True)

    def plans(self) -> list[str]:
        """Us"""
        d = self._read()
        return list(d["data"].keys()) if d else []

    def get(self, plan):
        """Ks"""
        d = self._read()
        return d["data"].get(plan) if d else None

    def delete(self, plan):
        """Ms：被匹配复用后从记忆中删除（复用后若再次失败会重新写入）。"""
        d = self._read()
        if d:
            d["data"].pop(plan, None)
            self._write(d["data"])

    def save(self, summary: str, history):
        """bs：以 successPart 为 key 保存（action 的 reason 置空）。"""
        d = self._read()
        data = d["data"] if d else {}
        data[summary] = [{**h, "reason": ""} if h["type"] == "action" else h for h in history]
        while len(data) > MAX_PLANS_PER_FILE:
            data.pop(next(iter(data)))
        self._write(data)
        print(f"Set the following steps as a reusable script: {summary}")
