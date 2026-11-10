# WORKbuddy 自测报告 20261110_093714

- 状态：**failed**
- 代码版本：`e653a5815c7f`
- 开始：2026-11-10 09:37:14　结束：2026-11-10 09:52:10
- 结果：通过 50 / 失败 0 / 跳过 0

## 步骤

- [OK] 查远端 HEAD　rc=0
- [OK] 跳过拉取　rc=0
- [OK] 启动服务　rc=0
- [OK] selftest　rc=0
- [OK] 导出使用遥测　rc=0
- [FAIL] 专项回归套件　rc=1
- [OK] 判定　rc=0
- [OK] git add reports　rc=0
  - warning: in the working copy of 'reports/20261110_092937/INVALID.md', LF will be replaced by CRLF the next time Git touches it
- [OK] git commit　rc=0
- [OK] git push　rc=0
  - To https://github.com/hufanrong/engineering-ai-assistant
   c723339..e653a58  HEAD -> main

## 专项回归套件（18 通过 / 2 失败 / 共 20）

| 套件 | 结果 | 用时(s) | 结论行 |
|---|---|---|---|
| test_archive_concurrency.py | OK | 0.5 | 结果：通过 13 / 失败 0 / 共 13 |
| test_atomic_io.py | FAIL | 1.5 | FAIL: 8 线程 × 3 轮并发写索引：0 错误  错误 ["PermissionError: [WinError 5] 拒绝访问。: 'C:\\\\Use |
| test_atomic_write.py | FAIL | 0.5 | FAIL: 10 线程 × 4 轮并发写：0 错误  ["PermissionError: [WinError 5] 拒绝访问。: 'C:\\\\Users\\ |
| test_delete_project_pointer.py | OK | 0.6 | 结果：通过 32 / 失败 0 |
| test_gb_fallback.py | OK | 9.4 | 结果：193 passed, 0 failed |
| test_index_count.py | OK | 1.4 | 结果：通过 10 / 失败 0 |
| test_ledger_units.py | OK | 0.8 | 结果：通过 8 / 失败 0 / 共 8 |
| test_merge_agg.py | OK | 0.3 | 通过 33 项，失败 0 项 |
| test_parsed_cache_path.py | OK | 1.2 | 结果：通过 12 / 失败 0 |
| test_project_audit_log.py | OK | 4.4 | 结果：通过 24 / 失败 0 |
| test_project_backup_complete.py | OK | 1.2 | 汇总：通过 19 / 失败 0 |
| test_project_scope.py | OK | 0.4 | 全部通过 |
| test_readonly_no_write.py | OK | 6.1 | 结果：17 passed, 0 failed |
| test_relations_workshops.py | OK | 0.1 | ===== 通过 10 / 失败 0 ===== |
| test_smart_doc_persist.py | OK | 2.7 | 合计：111 PASS / 0 FAIL |
| test_source_path_fields.py | OK | 75.4 | ===== 通过 19 / 失败 0 ===== |
| test_template_concurrency.py | OK | 1.0 | 通过 9 项，失败 0 项 |
| test_upload_queue.py | OK | 0.5 | 结果：通过 15 / 失败 0 |
| test_volume_no_overwrite.py | OK | 7.8 | 合计：27 PASS / 0 FAIL |
| test_workshop_source.py | OK | 1.4 | 结果：通过 8 / 失败 0 |
