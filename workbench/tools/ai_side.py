#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""繁工AI ↔ WORKbuddy 自动循环通道 · AI 侧读取器

WORKbuddy 侧跑 workbench/tools/wb_loop.py，把每轮自测报告推到仓库
reports/<run_id>/ 下。本脚本是闭环的另一半：读远端最新报告，判定
本轮该做什么（推进 / 修代码 / 修通道）。

用法：
    python3 ai_side.py                # 看最新一轮报告摘要
    python3 ai_side.py --list         # 列出远端所有报告轮次
    python3 ai_side.py --run <run_id> # 读指定轮次的完整报告
    python3 ai_side.py --fails        # 只列最新一轮的失败项

凭据：从 ~/.aily/workspace/.gh_token 读（沙箱私有，不进公开仓库）。
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request

REPO = "hufanrong/engineering-ai-assistant"
BRANCH = "main"
API = "https://api.github.com"
TOKEN_FILE = os.path.expanduser("~/.aily/workspace/.gh_token")
REPORTS = "reports"


def token():
    try:
        return open(TOKEN_FILE, encoding="utf-8").read().strip()
    except Exception:  # noqa: BLE001
        return ""


def api(path, raw=False):
    """GET，带 token 认证（匿名额度只有 60/小时，不够用）。"""
    req = urllib.request.Request(API + path, headers={
        "Authorization": "Bearer " + token(),
        "Accept": "application/vnd.github+json",
        "User-Agent": "fangong-ai",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode("utf-8", "replace")
                return (body if raw else json.loads(body)), r.status
        except urllib.error.HTTPError as e:
            if e.code in (403, 429, 500, 502) and attempt < 2:
                import time
                time.sleep(2 + 2 * attempt)
                continue
            return {"_err": e.read().decode()[:300]}, e.code
        except Exception as e:  # noqa: BLE001
            if attempt < 2:
                import time
                time.sleep(2 + 2 * attempt)
                continue
            return {"_err": str(e)[:300]}, -1


def list_runs():
    """远端 reports/ 下所有轮次目录，新的在前。"""
    d, code = api(f"/repos/{REPO}/contents/{REPORTS}?ref={BRANCH}")
    if code != 200:
        return None, f"列目录失败 HTTP {code}: {str(d)[:200]}"
    runs = [x["name"] for x in d if x.get("type") == "dir"]
    return sorted(runs, reverse=True), ""


def read_file(relpath):
    d, code = api(f"/repos/{REPO}/contents/{relpath}?ref={BRANCH}")
    if code != 200:
        return None, f"读 {relpath} 失败 HTTP {code}"
    try:
        return base64.b64decode(d["content"]).decode("utf-8", "replace"), ""
    except Exception as e:  # noqa: BLE001
        return None, f"解码失败: {e}"


def latest_report():
    runs, err = list_runs()
    if not runs:
        return None, None, err or "远端还没有任何自测报告（WORKbuddy 尚未回传第一轮）"
    run_id = runs[0]
    txt, err2 = read_file(f"{REPORTS}/{run_id}/report.json")
    if not txt:
        return run_id, None, err2
    try:
        return run_id, json.loads(txt), ""
    except Exception as e:  # noqa: BLE001
        return run_id, None, f"report.json 解析失败: {e}"


def next_action(rep):
    """把报告翻成「我下一轮该干什么」。这是闭环的决策规则。"""
    if not rep:
        return "等 WORKbuddy 回传第一份报告；先确认通道能跑通"
    st = rep.get("status")
    sm = rep.get("summary") or {}
    if st == "passed":
        return "本轮全过，按固定顺序推进下一阶段"
    if st == "failed":
        return (f"有 {sm.get('failed', 0)} 项失败：读 console.log 定位，"
                f"改代码、推 GitHub，等 WORKbuddy 下一轮复测")
    if st == "error":
        return f"通道自身出错（非代码问题）：{rep.get('error') or '见 steps'}，先修通道"
    return "未知状态"


def print_summary(run_id, rep):
    sm = rep.get("summary") or {}
    print(f"轮次: {run_id}")
    print(f"状态: {rep.get('status')}")
    print(f"代码版本: {str(rep.get('commit_after'))[:12]}")
    print(f"时间: {rep.get('started')} → {rep.get('finished')}")
    print(f"结果: 通过 {sm.get('passed', 0)} / 失败 {sm.get('failed', 0)} / 跳过 {sm.get('skipped', 0)}")
    for ph, v in (sm.get("by_phase") or {}).items():
        print(f"  阶段 {ph}: 通过 {v.get('passed', 0)} 失败 {v.get('failed', 0)} 跳过 {v.get('skipped', 0)}")
    if rep.get("error"):
        print(f"错误: {rep['error']}")
    print(f"\n下一步: {next_action(rep)}")


def main():
    ap = argparse.ArgumentParser(description="读 WORKbuddy 回传的自测报告")
    ap.add_argument("--list", action="store_true", help="列出所有轮次")
    ap.add_argument("--run", metavar="RUN_ID", help="读指定轮次")
    ap.add_argument("--fails", action="store_true", help="只列最新一轮失败项")
    a = ap.parse_args()

    if not token():
        print(f"[错误] 找不到凭据 {TOKEN_FILE}")
        return 2

    if a.list:
        runs, err = list_runs()
        if not runs:
            print(err or "远端还没有报告")
            return 0
        print(f"远端共 {len(runs)} 轮报告（新→旧）：")
        for r in runs[:30]:
            print("  " + r)
        return 0

    run_id = a.run or None
    if run_id:
        txt, err = read_file(f"{REPORTS}/{run_id}/report.json")
        if not txt:
            print(f"[错误] {err}")
            return 1
        rep = json.loads(txt)
    else:
        run_id, rep, err = latest_report()
        if not rep:
            print(f"[提示] {err}")
            return 0

    if a.fails:
        detail, err2 = read_file(f"{REPORTS}/{run_id}/selftest_report.json")
        if not detail:
            print(f"[错误] {err2}")
            return 1
        d = json.loads(detail)
        # passed 是三态：True 通过 / False 失败 / None 跳过。只把 False 当失败，
        # 否则「环境不满足、跳过」会被算成待修问题（实测阶段④就是这样虚报 5 项）。
        bad = [x for x in d.get("results", [])
               if x.get("passed") is False and not x.get("skipped")]
        print(f"轮次 {run_id} 共 {len(bad)} 项失败：")
        for x in bad:
            print(f"  [阶段{x.get('phase')}] {x.get('step')} → {str(x.get('actual'))[:120]}")
        return 0

    print_summary(run_id, rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
