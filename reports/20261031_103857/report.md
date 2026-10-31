# WORKbuddy 自测报告 20261031_103857

- 状态：**error**
- 代码版本：`6af63a36768b`
- 开始：2026-10-31 10:38:57　结束：2026-10-31 10:41:11

## 步骤

- [OK] 查远端 HEAD　rc=0
- [OK] 跳过拉取　rc=0
- [FAIL] 启动服务　rc=1
- [OK] 服务不可用，转进程内模式　rc=0
- [OK] 进程内自测　rc=0
- [FAIL] selftest　rc=2
  - 缺少 python-multipart（进程内模式需要；pip install python-multipart）
- [OK] 判定　rc=0
