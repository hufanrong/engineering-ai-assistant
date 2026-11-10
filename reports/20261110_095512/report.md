# WORKbuddy 自测报告 20261110_095512

- 状态：**passed**
- 代码版本：`825015906b5c`
- 开始：2026-11-10 09:55:12　结束：2026-11-10 10:04:04
- 结果：通过 50 / 失败 0 / 跳过 0

## 步骤

- [OK] 查远端 HEAD　rc=0
- [OK] 跳过拉取　rc=0
- [OK] 启动服务　rc=0
- [OK] selftest　rc=0
- [OK] 导出使用遥测　rc=0
- [OK] 专项回归套件　rc=0
- [OK] 判定　rc=0
- [OK] git add reports　rc=0
- [OK] git commit　rc=0
- [OK] git push　rc=0
  - To https://github.com/hufanrong/engineering-ai-assistant
   45b862b..8250159  HEAD -> main

## 专项回归套件（20 通过 / 0 失败 / 共 20）

| 套件 | 结果 | 用时(s) | 结论行 |
|---|---|---|---|
| test_archive_concurrency.py | OK | 0.5 | 结果：通过 13 / 失败 0 / 共 13 |
| test_atomic_io.py | OK | 2.2 | 结果：通过 22 / 失败 0 / 共 22 |
| test_atomic_write.py | OK | 1.9 | 结果：通过 29 / 失败 0 / 共 29 |
| test_delete_project_pointer.py | OK | 0.5 | 结果：通过 32 / 失败 0 |
| test_gb_fallback.py | OK | 9.1 | 结果：193 passed, 0 failed |
| test_index_count.py | OK | 1.0 | 结果：通过 10 / 失败 0 |
| test_ledger_units.py | OK | 0.7 | 结果：通过 8 / 失败 0 / 共 8 |
| test_merge_agg.py | OK | 0.3 | 通过 33 项，失败 0 项 |
| test_parsed_cache_path.py | OK | 1.1 | 结果：通过 12 / 失败 0 |
| test_project_audit_log.py | OK | 5.0 | 结果：通过 24 / 失败 0 |
| test_project_backup_complete.py | OK | 1.0 | 汇总：通过 19 / 失败 0 |
| test_project_scope.py | OK | 0.6 | 全部通过 |
| test_readonly_no_write.py | OK | 4.5 | 结果：17 passed, 0 failed |
| test_relations_workshops.py | OK | 0.1 | ===== 通过 10 / 失败 0 ===== |
| test_smart_doc_persist.py | OK | 2.8 | 合计：111 PASS / 0 FAIL |
| test_source_path_fields.py | OK | 67.8 | ===== 通过 19 / 失败 0 ===== |
| test_template_concurrency.py | OK | 1.1 | 通过 9 项，失败 0 项 |
| test_upload_queue.py | OK | 0.5 | 结果：通过 15 / 失败 0 |
| test_volume_no_overwrite.py | OK | 7.8 | 合计：27 PASS / 0 FAIL |
| test_workshop_source.py | OK | 1.3 | 结果：通过 8 / 失败 0 |
