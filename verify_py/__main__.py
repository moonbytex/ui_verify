"""python -m verify_py --bundle <包名> --plan <测试计划> [--fresh] [--device 设备名]"""
from __future__ import annotations

import argparse
import json
import sys

from .runner import verify_ui


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="在已连接的鸿蒙设备上执行 UI 验证，并用浏览器查看过程")
    p.add_argument("--bundle", required=True, help="待测应用包名")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--plan", help="测试计划文本")
    src.add_argument("--plan-file", help="测试计划文件，UTF-8")
    p.add_argument("--fresh", action="store_true", help="开始前回到桌面，并允许复用已保存的步骤")
    p.add_argument("--device", default="", help="设备序列号或名称；多设备时必填")
    p.add_argument("--log-path", default=None, help="日志根目录，默认临时目录 ui-verification")
    p.add_argument("--no-browser", action="store_true", help="不打开可视化页面")
    args = p.parse_args(argv)
    if args.plan is not None:
        plan = args.plan
    else:
        with open(args.plan_file, encoding="utf-8") as f:
            plan = f.read()
    result = verify_ui(plan, args.bundle, args.fresh, args.device or None, log_path=args.log_path,
                       open_browser=not args.no_browser)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
