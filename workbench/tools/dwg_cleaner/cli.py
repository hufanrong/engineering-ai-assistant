# -*- coding: utf-8 -*-
"""命令行入口：批量处理 DWG，输出汇总 JSON。"""

import argparse
import json

from dwg_cleaner import core, rules


def main():
    p = argparse.ArgumentParser(description="DWG 竣工图清稿工具（命令行版）")
    p.add_argument("--input", required=True, help="DWG 文件路径或文件夹路径")
    p.add_argument("--output", required=True, help="输出文件夹")
    p.add_argument("--config", default=None, help="规则配置文件路径（默认使用包内 config.json）")
    p.add_argument("--no-recursive", action="store_true", help="不递归子目录")
    p.add_argument("--style", choices=["mono", "color"], default="mono", help="打印样式：mono=黑白（默认），color=彩色")
    args = p.parse_args()

    cfg = rules.load_config(args.config)
    if args.style == "color":
        cfg["plot"]["style_sheet"] = ""

    report = core.process_folder(
        args.input, args.output, cfg,
        recursive=not args.no_recursive,
        on_progress=lambda m: print(m) if m else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
