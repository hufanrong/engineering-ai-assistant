# WORKbuddy 自测报告 20261110_085217

- 状态：**failed**
- 代码版本：`aec4082fb47a`
- 开始：2026-11-10 08:52:17　结束：2026-11-10 09:05:23
- 结果：通过 54 / 失败 13 / 跳过 2

## 步骤

- [OK] 查远端 HEAD　rc=0
- [OK] 跳过拉取　rc=0
- [FAIL] selftest　rc=1
  - Traceback (most recent call last):
  File "D:\fangong-workbench\workbench\tools\selftest.py", line 2034, in main
    {1: phase1, 2: phase2, 3: phase3, 4: phase4,
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- [FAIL] 导出使用遥测　rc=1
- [FAIL] 专项回归套件　rc=1
- [OK] 判定　rc=0

## 专项回归套件（18 通过 / 2 失败 / 共 20）

| 套件 | 结果 | 用时(s) | 结论行 |
|---|---|---|---|
| test_archive_concurrency.py | OK | 0.7 | 结果：通过 13 / 失败 0 / 共 13 |
| test_atomic_io.py | FAIL | 1.6 | FAIL: 8 线程 × 3 轮并发写索引：0 错误  错误 ["PermissionError: [WinError 5] 拒绝访问。: 'C:\\\\Use |
| test_atomic_write.py | FAIL | 0.6 | FAIL: 10 线程 × 4 轮并发写：0 错误  ["PermissionError: [WinError 5] 拒绝访问。: 'C:\\\\Users\\ |
| test_delete_project_pointer.py | OK | 0.7 | 结果：通过 32 / 失败 0 |
| test_gb_fallback.py | OK | 9.6 | 结果：193 passed, 0 failed |
| test_index_count.py | OK | 1.2 | 结果：通过 10 / 失败 0 |
| test_ledger_units.py | OK | 0.8 | 结果：通过 8 / 失败 0 / 共 8 |
| test_merge_agg.py | OK | 0.4 | 通过 33 项，失败 0 项 |
| test_parsed_cache_path.py | OK | 1.2 | 结果：通过 12 / 失败 0 |
| test_project_audit_log.py | OK | 7.7 | 结果：通过 24 / 失败 0 |
| test_project_backup_complete.py | OK | 15.5 | 汇总：通过 19 / 失败 0 |
| test_project_scope.py | OK | 0.6 | 全部通过 |
| test_readonly_no_write.py | OK | 14.2 | 结果：17 passed, 0 failed |
| test_relations_workshops.py | OK | 0.2 | ===== 通过 10 / 失败 0 ===== |
| test_smart_doc_persist.py | OK | 3.5 | 合计：111 PASS / 0 FAIL |
| test_source_path_fields.py | OK | 83.4 | ===== 通过 19 / 失败 0 ===== |
| test_template_concurrency.py | OK | 1.2 | 通过 9 项，失败 0 项 |
| test_upload_queue.py | OK | 0.5 | 结果：通过 15 / 失败 0 |
| test_volume_no_overwrite.py | OK | 11.4 | 合计：27 PASS / 0 FAIL |
| test_workshop_source.py | OK | 1.7 | 结果：通过 8 / 失败 0 |
