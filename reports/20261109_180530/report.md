# WORKbuddy 自测报告 20261109_180530

- 状态：**failed**
- 代码版本：`aa0801bd15c5`
- 开始：2026-11-09 18:05:30　结束：2026-11-09 18:06:11
- 结果：通过 57 / 失败 2 / 跳过 2

## 步骤

- [OK] 查远端 HEAD　rc=0
- [OK] git fetch　rc=0
  - From https://github.com/hufanrong/engineering-ai-assistant
 * branch            main       -> FETCH_HEAD
- [OK] 远端无新提交　rc=0
- [OK] taskkill 25864　rc=0
- [OK] 启动服务　rc=0
- [FAIL] selftest　rc=1
  - Traceback (most recent call last):
  File "D:\fangong-workbench\workbench\tools\selftest.py", line 1752, in main
    {1: phase1, 2: phase2, 3: phase3, 4: phase4,
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- [OK] 导出使用遥测　rc=0
- [OK] 判定　rc=0
- [OK] git add reports　rc=0
- [OK] git commit　rc=0
- [OK] git push　rc=0
  - To https://github.com/hufanrong/engineering-ai-assistant
   0465792..aa0801b  HEAD -> main
