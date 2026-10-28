"""HarmonyDevice：对应 uiVerification.mjs 中 class Bt（L560-1261）。"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
import uuid

from .device import (
    DEVICE_TMP, FOLD_STATES, KEY_CODES, SPECIAL_CHAR_KEYS, SPECIAL_SPLIT,
    EmulatorSnapshot, SlowSnapshot, exec_command, parse_rotation,
)


class HarmonyDevice:
    def __init__(self, device_name, locator, hdc_path=None):
        self.device_name = device_name
        self.locator = locator
        self.hdc_path = hdc_path or os.environ.get("UI_VERIFY_HDC_PATH") or os.environ.get("RC_HDC_PATH")
        self.device_id = ""
        self.actual_device_name = ""
        self.device_type = ""
        self.running_id = None
        self._stop_touch = threading.Event()
        self.initial_faultlogs: list[str] = []
        self.screen_capture: SlowSnapshot | None = None
        self.emulator_direction: int | None = None

    # ---------------- hdc 基础 ----------------
    def hdc_cmd(self) -> str:
        if self.hdc_path:
            return self.hdc_path if self.hdc_path == "hdc" else f'"{self.hdc_path}"'
        home = os.environ.get("DEVECO_HOME") or os.environ.get("DEVECO_PATH")
        if home:
            return '"' + os.path.join(home, "sdk", "default", "openharmony", "toolchains", "hdc") + '"'
        return "hdc"

    def shell(self, cmd, target=None) -> str:
        t = target or self.device_id
        prefix = f"-t {t} " if t else ""
        return exec_command(f"{self.hdc_cmd()} {prefix}shell {cmd}")

    def shell_quoted(self, cmd) -> str:
        """hdcShellWithQuote：整体用双引号包裹，内部双引号替换为单引号。"""
        return self.shell('"' + cmd.replace('"', "'") + '"')

    def recv_file(self, remote, local):
        prefix = f"-t {self.device_id} " if self.device_id else ""
        return exec_command(f'{self.hdc_cmd()} {prefix}file recv {remote} "{local}"')

    # ---------------- 设备选择 ----------------
    def list_devices(self) -> list[str]:
        out = exec_command(f"{self.hdc_cmd()} list targets")
        res = []
        for line in out.splitlines():
            s = line.strip()
            if s and not s.startswith("[Empty]"):
                res.append(s.split()[0])
        return res

    def fetch_device_name(self, serial) -> str:
        v = self.shell("param get ohos.qemu.hvd.name", serial).strip()
        if v and "errNum" not in v:
            return v
        v = self.shell("param get const.product.name", serial).strip()
        if v and v != "emulator":
            return v
        model = self.shell("param get const.product.model", serial).strip()
        if model and model != "emulator":
            brand = self.shell("param get const.product.brand", serial).strip()
            if brand:
                model = re.sub(rf"^{re.escape(brand)}(\s+|[-_]+)?", "", model, flags=re.I).strip() or model
            return model
        return serial

    def update_device_id(self):
        devs = []
        for s in self.list_devices():
            try:
                devs.append((s, self.fetch_device_name(s)))
            except Exception:  # noqa: BLE001
                pass
        if not devs:
            raise RuntimeError("No active devices found. Please start an emulator or connect a physical device.")
        sel = self.device_name
        listing = "\n".join(f"  - {n} ({s})" for s, n in devs)
        if not sel and len(devs) > 1:
            raise RuntimeError("Multiple devices found. Please specify --device.\n" + listing)
        m = [(s, n) for s, n in devs if not sel or s == sel or sel.lower() in n.lower()]
        if len(m) == 1:
            self.device_id, self.actual_device_name = m[0]
            return
        raise RuntimeError(f'Device "{sel}" not found or ambiguous. Available devices:\n{listing}')

    # ---------------- 设备信息 ----------------
    def set_device_type(self):
        self.device_type = self.shell("param get const.product.devicetype").strip()

    def is_pc_or_2in1(self) -> bool:
        return self.device_type.strip().lower() == "2in1"

    def is_pc_or_tablet(self) -> bool:
        return self.device_type.strip().lower() in ("2in1", "tablet")

    def get_screen_size(self):
        out = self.shell("hidumper -s DisplayManagerService -a -a")
        i = out.find("[DISPLAY INFO]")
        if i != -1:
            out = out[i:]
        m = re.search(r"^Width:\s*(\d+)\s*[\r\n]+^Height:\s*(\d+)\s*$", out, re.M)
        if not m:
            raise RuntimeError("无法获取屏幕尺寸")
        return int(m.group(1)), int(m.group(2))

    def get_status_bar_height(self) -> int:
        if self.is_pc_or_2in1():
            return 0
        for line in self.shell("hidumper -s WindowManagerService -a '-a'").splitlines():
            if "SCBStatusBar" in line:
                m = re.search(r"\[\s*\d+\s+\d+\s+\d+\s+(\d+)\s*\]", line)
                if m:
                    return int(m.group(1))
        raise RuntimeError("无法获取状态栏高度")

    def get_system_rotation(self):
        try:
            return parse_rotation(self.shell("hidumper -s DisplayManagerService -a -a"))
        except Exception:  # noqa: BLE001
            return None

    def get_screenshot_rotation(self) -> int:
        return ((self.get_system_rotation() or 0) - (self.emulator_direction or 0) + 4) % 4

    def get_emulator_name(self):
        try:
            v = self.shell("param get ohos.qemu.hvd.name")
            return None if "errNum" in v else v.strip()
        except Exception:  # noqa: BLE001
            return None

    def is_emulator(self) -> bool:
        return self.get_emulator_name() is not None

    def emulator_path(self):
        home = os.environ.get("DEVECO_HOME") or os.environ.get("DEVECO_PATH")
        return os.path.join(home, "tools", "emulator", "Emulator") if home else None

    def emulator_major_version(self) -> int:
        p = self.emulator_path()
        if not p:
            return 0
        try:
            out = exec_command(f'"{p}" -version', True)
            m = re.search(r"HarmonyOS Emulator\s*:\s*(\d+)", out, re.I)
            return int(m.group(1)) if m else 0
        except Exception:  # noqa: BLE001
            return 0

    def get_foldable_info(self):
        name, p = self.get_emulator_name(), self.emulator_path()
        if not name or not p:
            return None
        try:
            arr = json.loads(exec_command(f'"{p}" -list -details', True))
        except Exception:  # noqa: BLE001
            return None
        for d in arr if isinstance(arr, list) else []:
            if isinstance(d, dict) and d.get("name") == name and isinstance(d.get("deviceType"), str):
                for k in FOLD_STATES:
                    if k.lower() == d["deviceType"].lower():
                        return {"type": k, "supportedStates": FOLD_STATES[k], "emulatorName": name}
        return None

    # ---------------- 截图 ----------------
    def single_screenshot(self, resize=True) -> dict:
        """singleScreenshot：snapshot_display（按定位器尺寸缩放）-> base64 -w 0 读回。"""
        w, h = self.get_screen_size()
        size = self.locator.get_suitable_image_size((w, h))
        remote = f"{DEVICE_TMP}/_tmp_{uuid.uuid4()}.jpeg"
        for attempt in range(1, 6):
            if size and resize:
                out = self.shell(f"snapshot_display -w {size[0]} -h {size[1]} -f {remote}")
            else:
                out = self.shell(f"snapshot_display -f {remote}")
            if "success" in out:
                break
            if attempt >= 5:
                raise RuntimeError("暂时无法截图，请稍后再试")
            time.sleep(attempt * 0.1)
        b64 = re.sub(r"\s+", "", self.shell(f"base64 -w 0 {remote}"))
        self.shell(f"rm -f {remote}")
        return {"base64": b64, "screenSize": [w, h], "timestamp": int(time.time() * 1000), "diff": 0}

    def screenshot(self) -> list[dict]:
        return self.screen_capture.screenshot()

    def wait_until_change(self, ms):
        self.screen_capture.wait_until_change(ms)

    # ---------------- 输入 ----------------
    def tap(self, x, y):
        self.shell(f"uitest uiInput click {x} {y}")

    def double_tap(self, x, y):
        self.shell(f"uitest uiInput doubleClick {x} {y}")

    def swipe(self, x1, y1, x2, y2, speed=1500):
        self.shell(f"uitest uiInput swipe {x1} {y1} {x2} {y2} {speed}")

    def mouse_click(self, x, y, btn=0):
        self.shell(f"uinput --mouse --move {x} {y} --click {btn}")

    def mouse_double_click(self, x, y, btn=0):
        self.shell(f"uinput --mouse --double_click {x} {y} {btn} 1 1")

    def mouse_scroll(self, x, y, direction, ticks):
        v = (1 if direction == "down" else -1) * ticks * 15
        self.shell(f"uinput --mouse --move {x} {y} --scroll {v}")

    def touch_down(self, x, y):
        self.shell(f"uinput -T -d {x} {y}")

    def touch_up(self, x, y):
        self.shell(f"uinput -T -u {x} {y}")

    def press_key(self, keys):
        if not (len(keys) == 1 and keys[0] in ("Home", "Back")) and not self.is_pc_or_tablet():
            raise RuntimeError(f"当前设备不支持按键 {'+'.join(keys)}，仅 PC/平板可用")
        if keys == ["Home"] and self.is_pc_or_2in1():
            self.shell("uitest uiInput keyEvent 2076 2020")
            return
        self.shell("uitest uiInput keyEvent " + " ".join(str(KEY_CODES[k]) for k in keys))

    def _line_commands(self, line):
        cmds = []
        for seg in SPECIAL_SPLIT.split(line):
            if not seg:
                continue
            if len(seg) == 1 and seg in SPECIAL_CHAR_KEYS:
                cmds.append(f"uitest uiInput keyEvent {SPECIAL_CHAR_KEYS[seg]}")
            else:
                cmds.append(f"uitest uiInput text '{seg}'")
        return cmds

    def input_text(self, x, y, text, mode):
        """先点击输入框；clearAndInput=Ctrl+A + Delete；append=End(2082)；换行=Enter(2054)。"""
        self.tap(x, y)
        if mode == "clearAndInput":
            cmds = ["uitest uiInput keyEvent 2072 2017", "uitest uiInput keyEvent 2071"]
        else:
            cmds = ["uitest uiInput keyEvent 2082"]
        for i, line in enumerate(text.split("\n")):
            if i > 0:
                cmds.append("uitest uiInput keyEvent 2054")
            cmds.extend(self._line_commands(line))
        self.shell_quoted(" && ".join(cmds))

    # ---------------- 应用 ----------------
    def get_main_ability_name(self, bundle):
        """getMainAbilityName：bm dump，launcher ability 优先，其次按 mainAbility/mainModule 打分。"""
        try:
            out = self.shell(f"bm dump -n {bundle}")
            info = json.loads(out[out.index("{"): out.rindex("}") + 1])
        except Exception:  # noqa: BLE001
            return "", f"{bundle} is not installed"
        cands = []
        main_entry = info.get("mainEntry") or ""
        for mod in info.get("hapModuleInfos") or []:
            main_ability = mod.get("mainAbility") or ""
            for ab in mod.get("abilityInfos") or []:
                skills = ab.get("skills") or []
                launcher = bool(skills) and "action.system.home" in (skills[0].get("actions") or [])
                score = int(ab.get("name") == main_ability) + int(ab.get("moduleName") == main_entry)
                cands.append((not launcher, -score, ab.get("name") or ""))
        if not cands:
            return "", f"No main ability found in {bundle}"
        cands.sort(key=lambda c: (c[0], c[1]))
        return cands[0][2], None

    def start_app(self, bundle, fresh, uri=None):
        if uri:
            if fresh:
                self.shell(f"aa force-stop {bundle}")
                time.sleep(0.5)
            out = self.shell_quoted(f"aa start -U '{uri}'")
            if re.search("successfully", out, re.I):
                return None
            return f"DeepLink 跳转失败，URI：{uri}"
        ability, err = self.get_main_ability_name(bundle)
        if err:
            return err
        if fresh:
            self.shell(f"aa force-stop {bundle}")
            time.sleep(0.5)
        self.shell(f"aa start -a {ability} -b {bundle}")
        return None

    def get_pids(self, bundle):
        out = self.shell_quoted(f"ps -eo PID,ARGS=CMD | grep {bundle}")
        pids = []
        for line in out.splitlines():
            if " grep " in line:
                continue
            m = re.match(r"^\s*(\d+)\s+", line)
            if m:
                pids.append(int(m.group(1)))
        return pids

    def get_log(self, bundle, level="info") -> str:
        """getLog：按应用 pid 拉 hilog，然后 hilog -r 清空缓冲区。"""
        try:
            pids = self.get_pids(bundle)[:5]
            if not pids:
                return ""
            out = self.shell(f"hilog -P {','.join(map(str, pids))} -x -L {level.upper()}")
            self.shell("hilog -r")
            return out
        except Exception as e:  # noqa: BLE001
            print("getLog failed:", e)
            return ""

    # ---------------- faultlog ----------------
    def get_faultlogs(self):
        try:
            out = self.shell('hidumper -s 1201 -a "-p Faultlogger %s -LogSuffixWithMs"')
        except Exception:  # noqa: BLE001
            return []
        pat = re.compile(r"^(appfreeze|cppcrash|jscrash|serviceblock|sysfreeze|syswarning)-")
        return [l.strip() for l in out.splitlines() if pat.match(l.strip())]

    def check_error(self, save_dir) -> str:
        new = [f for f in self.get_faultlogs() if f not in self.initial_faultlogs]
        if not new:
            return ""
        os.makedirs(save_dir, exist_ok=True)
        saved = []
        for f in new:
            local = os.path.join(save_dir, f"faultlog-{re.sub(r'[^a-zA-Z0-9_-]', '_', f)}-{int(time.time()*1000)}.log")
            try:
                self.recv_file(f"/data/log/faultlog/faultlogger/{f}", local)
                saved.append(local)
            except Exception as e:  # noqa: BLE001
                print(f"下载faultlog失败 {f}: {e}")
        return f"新增的faultlog已下载到：{'; '.join(saved)}" if saved else ""

    # ---------------- 横竖屏 / 折叠屏 ----------------
    def _emu_exec(self, args):
        name, p = self.get_emulator_name(), self.emulator_path()
        if not name:
            raise RuntimeError("当前设备不是模拟器")
        if not p:
            raise RuntimeError("未配置 DEVECO_PATH 或 DEVECO_HOME 环境变量")
        v = self.emulator_major_version()
        if v < 26:
            raise RuntimeError(f"Emulator 命令要求主版本 >= 26，当前主版本 = {v}")
        exec_command(f'"{p}" -instance "{name}" {args}', True)

    def set_rotation(self, rotation):
        target = 3 if rotation == "landscape" else 0
        cur = self.emulator_direction or 0
        diff = (target - cur + 4) % 4
        if diff == 0:
            return
        direction, times = ("right", diff) if diff <= 2 else ("left", 4 - diff)
        for _ in range(times):
            self._emu_exec(f"-rotation {direction}")
        self.emulator_direction = target

    def set_fold_state(self, state):
        info = self.get_foldable_info()
        if not info:
            raise RuntimeError("当前设备不是折叠屏设备或不支持折叠屏操作")
        if state not in info["supportedStates"]:
            raise RuntimeError(
                f"设备类型 {info['type']} 不支持状态 \"{state}\"，支持的状态：{', '.join(info['supportedStates'])}"
            )
        self._emu_exec(f'-foldedState "{state}"')

    # ---------------- 任务生命周期 ----------------
    def _check_existing_running(self):
        """checkExistingRunning：设备上存在 15 秒内刷新过的锁文件则拒绝并发任务。"""
        try:
            out = self.shell(f"ls -1 {DEVICE_TMP}/ui-verification-*")
        except Exception:  # noqa: BLE001
            return
        if "No such file" in out:
            return
        for f in [l.strip() for l in out.splitlines() if l.strip()]:
            mtime = int(self.shell(f"stat -c %Y {f}").strip() or 0)
            now = int(self.shell("date +%s").strip() or 0)
            if now - mtime < 15:
                raise RuntimeError(f"检测到正在运行的验证任务（ID: {f[len(DEVICE_TMP) + 1:]})，请稍后再试")
            self.shell(f"rm {f}")

    def _create_running_id(self):
        self.running_id = f"ui-verification-{int(time.time()*1000)}-{secrets.token_hex(4)}"
        path = f"{DEVICE_TMP}/{self.running_id}"
        self.shell(f"touch {path}")
        self._stop_touch.clear()

        def keepalive():
            while not self._stop_touch.wait(10):
                try:
                    self.shell(f"touch {path}")
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=keepalive, daemon=True).start()

    def before_task(self):
        """beforeTask：选设备 -> 设备类型 -> 任务锁 -> 选截图方式 -> 记录已有 faultlog。"""
        self.update_device_id()
        self.set_device_type()
        self._check_existing_running()
        self._create_running_id()
        emu_name = self.get_emulator_name()
        sbh = self.get_status_bar_height()
        emu_path = self.emulator_path()
        ver = self.emulator_major_version() if emu_name and emu_path else 0
        if emu_name and emu_path and ver >= 26:
            cap = EmulatorSnapshot(emu_name, emu_path, self, sbh)
            cap.cache_emulator_direction()
            self.screen_capture = cap
        else:
            if emu_name and emu_path:
                print(f"模拟器截图要求 Emulator 主版本 >= 26，当前主版本 = {ver}，fallback 到 SlowSnapshot")
            self.screen_capture = SlowSnapshot(self, sbh)
        self.initial_faultlogs = self.get_faultlogs()

    def after_task(self):
        if self.screen_capture:
            self.screen_capture.stop()
        self._stop_touch.set()
        if self.running_id:
            try:
                self.shell(f"rm {DEVICE_TMP}/{self.running_id}")
            except Exception:  # noqa: BLE001
                pass
            self.running_id = None
