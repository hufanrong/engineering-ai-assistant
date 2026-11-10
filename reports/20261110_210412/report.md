# WORKbuddy 自测报告 20261110_210412

- 状态：**failed**
- 代码版本：`d3cb449f1e4f`
- 开始：2026-11-10 21:04:12　结束：2026-11-10 21:18:05
- 结果：通过 50 / 失败 2 / 跳过 0

## 步骤

- [OK] 查远端 HEAD　rc=0
- [OK] git fetch　rc=0
  - From https://github.com/hufanrong/engineering-ai-assistant
 * branch            main       -> FETCH_HEAD
   71bf835..d3cb449  main       -> origin/main
- [OK] git fetch　rc=0
  - From https://github.com/hufanrong/engineering-ai-assistant
 * branch            main       -> FETCH_HEAD
- [OK] 快进到 origin/main　rc=0
- [OK] 拉取后 HEAD　rc=0
- [OK] taskkill 23000　rc=0
- [OK] 启动服务　rc=0
- [FAIL] selftest　rc=1
- [OK] 导出使用遥测　rc=0
- [OK] 专项回归套件　rc=0
- [OK] 判定　rc=0

## 专项回归套件（24 通过 / 0 失败 / 共 24）

| 套件 | 结果 | 用时(s) | 结论行 |
|---|---|---|---|
| test_archive_concurrency.py | OK | 0.7 | 结果：通过 13 / 失败 0 / 共 13 |
| test_atomic_io.py | OK | 3.5 | 结果：通过 22 / 失败 0 / 共 22 |
| test_atomic_write.py | OK | 1.1 | 结果：通过 29 / 失败 0 / 共 29 |
| test_delete_project_pointer.py | OK | 0.3 | 结果：通过 32 / 失败 0 |
| test_gb_fallback.py | OK | 28.1 | 结果：193 passed, 0 failed |
| test_index_count.py | OK | 0.7 | 结果：通过 10 / 失败 0 |
| test_ledger_units.py | OK | 0.6 | 结果：通过 8 / 失败 0 / 共 8 |
| test_merge_agg.py | OK | 0.2 | 通过 33 项，失败 0 项 |
| test_parsed_cache_path.py | OK | 0.6 | 结果：通过 12 / 失败 0 |
| test_phase_coverage.py | OK | 0.4 | ===== 通过 25 / 失败 0 ===== |
| test_project_audit_log.py | OK | 8.8 | 结果：通过 24 / 失败 0 |
| test_project_backup_complete.py | OK | 6.5 | 汇总：通过 19 / 失败 0 |
| test_project_scope.py | OK | 0.3 | 全部通过 |
| test_readonly_no_write.py | OK | 6.4 | 结果：17 passed, 0 failed |
| test_relations_workshops.py | OK | 0.1 | ===== 通过 10 / 失败 0 ===== |
| test_restart_really.py | OK | 35.5 | ===== 通过 17 / 失败 0 ===== |
| test_restore_target.py | OK | 0.1 | ===== 通过 9 / 失败 0 ===== |
| test_smart_doc_persist.py | OK | 2.4 | 合计：111 PASS / 0 FAIL |
| test_source_path_fields.py | OK | 113.3 | ===== 通过 19 / 失败 0 ===== |
| test_template_concurrency.py | OK | 0.9 | 通过 9 项，失败 0 项 |
| test_upload_queue.py | OK | 1.2 | 结果：通过 15 / 失败 0 |
| test_volume_no_overwrite.py | OK | 9.1 | 合计：27 PASS / 0 FAIL |
| test_wb_loop_git.py | OK | 2.1 | ===== 通过 21 / 失败 0 ===== |
| test_workshop_source.py | OK | 1.8 | 结果：通过 8 / 失败 0 |
