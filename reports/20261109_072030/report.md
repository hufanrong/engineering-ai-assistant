# WORKbuddy 自测报告 20261109_072030

- 状态：**failed**
- 代码版本：`6f0b93637cf5`
- 开始：2026-11-09 07:20:30　结束：2026-11-09 07:24:10
- 结果：通过 67 / 失败 1 / 跳过 2

## 步骤

- [OK] 查远端 HEAD　rc=0
- [OK] 跳过拉取　rc=0
- [OK] 启动服务　rc=0
- [FAIL] selftest　rc=1
  - [safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED] {"count":51,"threshold":50,"scope":"turn","targets":["D:\\fangong-workbench\\workbench\\tools\\_samples"],"targetCount":1}

- [OK] 导出使用遥测　rc=0
- [OK] 判定　rc=0
- [OK] git add reports　rc=0
- [OK] git commit　rc=0
- [FAIL] git push　rc=128
