# WORKbuddy 自测报告 20261110_071929

- 状态：**failed**
- 代码版本：`091a615f1bbc`
- 开始：2026-11-10 07:19:29　结束：2026-11-10 07:24:39
- 结果：通过 74 / 失败 0 / 跳过 2

## 步骤

- [OK] 查远端 HEAD　rc=0
- [OK] git fetch　rc=0
  - From https://github.com/hufanrong/engineering-ai-assistant
 * branch            main       -> FETCH_HEAD
- [OK] 远端无新提交　rc=0
- [OK] taskkill 11368　rc=0
- [OK] 启动服务　rc=0
- [FAIL] selftest　rc=1
  - D:\fangong-workbench\workbench\venv\Lib\site-packages\fitz\__init__.py:17: FutureWarning: The `fitz` API is deprecated and will be removed in future. Use `import pymupdf` instead.
  warnings.warn(
[sa
- [OK] 导出使用遥测　rc=0
- [OK] 判定　rc=0
- [OK] git add reports　rc=0
- [OK] git commit　rc=0
- [OK] git push　rc=0
  - To https://github.com/hufanrong/engineering-ai-assistant
   21e2ab5..091a615  HEAD -> main
