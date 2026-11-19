#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D38 新门禁的反向验证（v0.1.250）。

门禁本身也要被验证：**故意破坏一次，门禁必须变红**；恢复后必须重新变绿，
且被改动的文件必须**逐字节还原**（sha256 比对）。

破坏点覆盖门禁的每一条：
    S1 → G2  在源码树里放回 PACKAGE_MANIFEST.json（构建产物回到树里）
    S2 → G3  放一份版本号写错的 JSON
    S3 → G4  把 FastAPI(version=CLOUD_VERSION) 改回写死字面量
    S4 → G4  把 cloud_server 文件头的版本号改成与常量不同
    S5 → G5  篡改实测包里的清单版本号

每条破坏都必须让门禁**退出码非 0**；随后还原并复跑，门禁必须**退出码 0**
且文件 sha256 与开工前完全一致。

退出码：0 = 全部反向验证成立；非 0 = 有破坏没被抓住或还原不干净。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _find_wb():
    """工作台根目录：脚本可能放在三种位置，逐一探测（谁有 app/config.py 谁算）：
        ① <workbench>/tools/            （进仓版本，tools/ 的上一级就是）
        ② <here>                          （脚本直接放在工作台根）
        ③ <here>/repo/fangong-workbench   （脚本放在 workdir 根）
    """
    cands = [os.path.dirname(HERE), HERE,
             os.path.join(HERE, "repo", "fangong-workbench"),
             os.path.join(os.path.dirname(os.path.dirname(HERE)),
                          "repo", "fangong-workbench")]
    for cand in cands:
        if os.path.isfile(os.path.join(cand, "app", "config.py")):
            return cand
    raise SystemExit("找不到工作台根目录（app/config.py）")


def _find_pkg(wb):
    """实测包：命令行 --package > 环境变量 FG_PACKAGE > workdir 下的默认名。"""
    cands = []
    if "--package" in sys.argv:
        cands.append(sys.argv[sys.argv.index("--package") + 1])
    if os.environ.get("FG_PACKAGE"):
        cands.append(os.environ["FG_PACKAGE"])
    cands.append(os.path.join(os.path.dirname(wb), "repo",
                               "繁工AI_v0.1.250_WORKbuddy实测包.zip"))
    cands.append(os.path.join(os.path.dirname(os.path.dirname(wb)),
                               "repo", "繁工AI_v0.1.250_WORKbuddy实测包.zip"))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


WB = _find_wb()
GATE = os.path.join(WB, "tools", "check_version_stamp.py")
PKG = _find_pkg(WB)


def sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def run_gate(pkg=None):
    cmd = [sys.executable, GATE]
    if pkg:
        cmd += ["--package", pkg]
    p = subprocess.run(cmd, cwd=WB, capture_output=True, text=True, timeout=180)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


class Restore:
    """记住一个文件的原始内容，恢复后必须逐字节一致。"""

    def __init__(self, path):
        self.path = path
        self.existed = os.path.isfile(path)
        self.blob = open(path, "rb").read() if self.existed else None
        self.sha = sha(path) if self.existed else None

    def restore(self):
        if self.existed:
            with open(self.path, "wb") as fh:
                fh.write(self.blob)
        elif os.path.isfile(self.path):
            os.remove(self.path)
        if self.existed:
            assert sha(self.path) == self.sha, "还原后 sha256 不一致：" + self.path


def report(tag, ok, detail):
    print(("  [PASS] " if ok else "  [FAIL] ") + tag + ("  " + detail if detail else ""))
    return ok


def main():
    ok_all = True
    print("=" * 72)
    print("D38 门禁反向验证（破坏一次，门禁必须变红）")
    print("工作台根目录：", WB)
    print("实测包：", PKG or "（未找到，G5 场景将跳过）")
    print("=" * 72)

    # 基线：未破坏时门禁必须是绿的
    rc, out = run_gate(PKG)
    ok_all &= report("基线：未破坏时门禁通过", rc == 0, "rc=%d" % rc)
    if rc != 0:
        print(out)
        return 1

    # ---- S1 → G2 ----
    stray = os.path.join(WB, "PACKAGE_MANIFEST.json")
    r = Restore(stray)
    with open(stray, "w", encoding="utf-8") as fh:
        json.dump({"version": "0.1.205", "file_count": 270}, fh)
    rc, out = run_gate()
    ok_all &= report("S1 树内放回 PACKAGE_MANIFEST.json → 门禁报红", rc != 0,
                     "rc=%d" % rc)
    ok_all &= report("S1 报红原因指到 G2", "G2" in out, "")
    r.restore()
    rc2, _ = run_gate()
    ok_all &= report("S1 还原后门禁恢复绿", rc2 == 0, "rc=%d" % rc2)

    # ---- S2 → G3 ----
    bad = os.path.join(WB, "tools", "_probe_bad_version.json")
    r = Restore(bad)
    with open(bad, "w", encoding="utf-8") as fh:
        json.dump({"version": "0.0.1-nope"}, fh)
    rc, out = run_gate()
    ok_all &= report("S2 放一份版本号写错的 JSON → 门禁报红", rc != 0, "rc=%d" % rc)
    ok_all &= report("S2 报红原因指到 G3", "G3" in out, "")
    r.restore()
    rc2, _ = run_gate()
    ok_all &= report("S2 还原后门禁恢复绿", rc2 == 0, "rc=%d" % rc2)

    # ---- S3 → G4（FastAPI 不再引用常量） ----
    cs = os.path.join(WB, "cloud_server", "app.py")
    r = Restore(cs)
    txt = open(cs, encoding="utf-8").read()
    assert "version=CLOUD_VERSION" in txt, "cloud_server/app.py 结构与预期不符"
    with open(cs, "w", encoding="utf-8") as fh:
        fh.write(txt.replace("version=CLOUD_VERSION", 'version="0.1.19"'))
    rc, out = run_gate()
    ok_all &= report("S3 FastAPI 改回写死字面量 → 门禁报红", rc != 0, "rc=%d" % rc)
    ok_all &= report("S3 报红原因指到 G4", "G4" in out, "")
    r.restore()
    rc2, _ = run_gate()
    ok_all &= report("S3 还原后门禁恢复绿", rc2 == 0, "rc=%d" % rc2)

    # ---- S4 → G4（文件头版本与常量不一致） ----
    r = Restore(cs)
    txt = open(cs, encoding="utf-8").read()
    with open(cs, "w", encoding="utf-8") as fh:
        fh.write(txt.replace("（v0.1.19）", "（v0.1.14）", 1))
    rc, out = run_gate()
    ok_all &= report("S4 文件头版本改成另一个 → 门禁报红", rc != 0, "rc=%d" % rc)
    ok_all &= report("S4 报红原因指到 G4", "G4" in out, "")
    r.restore()
    rc2, _ = run_gate()
    ok_all &= report("S4 还原后门禁恢复绿", rc2 == 0, "rc=%d" % rc2)

    # ---- S5 → G5（篡改包内清单版本） ----
    if not PKG:
        ok_all &= report("S5 篡改包内清单版本 → 门禁报红", False,
                         "未找到实测包，无法执行本场景")
    else:
        tmp = tempfile.mkdtemp(prefix="fg_rev250_")
        try:
            tampered = os.path.join(tmp, "tampered.zip")
            with zipfile.ZipFile(PKG) as src, zipfile.ZipFile(
                    tampered, "w", zipfile.ZIP_DEFLATED) as dst:
                for n in src.namelist():
                    data = src.read(n)
                    if n.endswith("PACKAGE_MANIFEST.json"):
                        man = json.loads(data.decode("utf-8"))
                        man["version"] = "0.1.205"
                        data = json.dumps(man, ensure_ascii=False,
                                          indent=2).encode("utf-8")
                    dst.writestr(n, data)
            rc, out = run_gate(tampered)
            ok_all &= report("S5 篡改包内清单版本 → 门禁报红", rc != 0, "rc=%d" % rc)
            ok_all &= report("S5 报红原因指到 G5", "G5" in out, "")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---- 收尾：全树文件不得留下任何探针 ----
    rc, _ = run_gate(PKG)
    ok_all &= report("收尾：破坏全部还原后门禁仍绿", rc == 0, "rc=%d" % rc)
    leftovers = [p for p in (stray, bad) if os.path.isfile(p)]
    ok_all &= report("收尾：没有留下任何探针文件", not leftovers, str(leftovers))

    print("=" * 72)
    print("反向验证结论：", "全部成立" if ok_all else "有破坏没被抓住")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
