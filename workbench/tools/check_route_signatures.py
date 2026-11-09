"""AST 扫描：所有 FastAPI 路由函数的参数必须带类型标注。

背景（v0.1.219 实测）：`async def import_project(request)` 少写 `: Request`，
FastAPI 就把 request 当成**必填 query 参数**，任何真实调用都在进函数体之前被拒：
    POST /api/projects/import -> 422 {"detail":[{"type":"missing","loc":["query","request"]}]}
也就是说这个接口自写下起从未成功执行过一次，而 /openapi.json 里它照样列着 ——
「接口存在」不等于「接口能用」。

本脚本只读，不改任何东西。

用法：
    python tools/check_route_signatures.py
退出码：0 = 所有路由函数参数都带标注；1 = 有缺标注，或压根没扫到路由（后者是脚本自身
        解析错目录的假通过，必须报红 —— 「扫到 0 个」不等于「没有问题」）。
"""
import ast
import os
import sys

# 本脚本在 tools/ 下，app/ 在上一级（项目根）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(PROJECT_ROOT, "app")
METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "api_route"}


def scan_file(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return None, f"语法错误：{e}"

    bad = []
    total = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_route = False
        for deco in node.decorator_list:
            d = deco
            if isinstance(d, ast.Call):
                d = d.func
            if isinstance(d, ast.Attribute) and d.attr in METHODS:
                is_route = True
                break
        if not is_route:
            continue
        total += 1
        a = node.args
        params = list(getattr(a, "posonlyargs", [])) + list(a.args) + list(a.kwonlyargs)
        for p in params:
            if p.arg in ("self", "cls"):
                continue
            if p.annotation is None:
                bad.append((node.name, p.arg, node.lineno))
    return (total, bad), None


def main():
    if not os.path.isdir(APP_DIR):
        print(f"[FAIL] app 目录不存在：{APP_DIR}")
        return 1
    files = []
    for root, _dirs, names in os.walk(APP_DIR):
        for n in names:
            if n.endswith(".py"):
                files.append(os.path.join(root, n))
    grand_total = 0
    grand_bad = []
    err_files = []
    for f in sorted(files):
        res, err = scan_file(f)
        if err:
            print(f"[ERR ] {os.path.relpath(f, PROJECT_ROOT)}: {err}")
            err_files.append(f)
            continue
        total, bad = res
        if total == 0:
            continue
        rel = os.path.relpath(f, PROJECT_ROOT)
        grand_total += total
        if bad:
            for fn, p, ln in bad:
                print(f"[FAIL] {rel}:{ln} {fn}({p}) 缺少类型标注 -> "
                      f"FastAPI 会当成必填 query 参数，该接口恒 422")
                grand_bad.append((rel, ln, fn, p))
        else:
            print(f"[ OK ] {rel}: {total} 个路由函数，参数全带标注")

    print(f"\n扫描 {len(files)} 个 py 文件，识别路由函数 {grand_total} 个，"
          f"缺标注参数 {len(grand_bad)} 个，解析失败 {len(err_files)} 个")

    # 防假通过：路由数为 0 说明目录/装饰器识别错了，不能当成「没有问题」
    if grand_total == 0:
        print("[FAIL] 一个路由函数都没识别到 —— 检查 APP_DIR 与装饰器识别逻辑，"
              "不能据此判定通过")
        return 1
    if grand_bad:
        return 1
    if err_files:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
