# WORKbuddy 自测报告 20261112_130414

- 状态：**failed**
- 代码版本：`616450437289`
- 开始：2026-11-12 13:04:14　结束：2026-11-12 13:20:28
- 结果：通过 74 / 失败 1 / 跳过 2
- 阶段覆盖：**完整**（5/6）

## 步骤

- [OK] 查远端 HEAD　rc=0
- [OK] git fetch　rc=0
  - From https://github.com/hufanrong/engineering-ai-assistant
 * branch            main       -> FETCH_HEAD
- [OK] 远端无新提交　rc=0
- [OK] taskkill 3216　rc=0
- [OK] 启动服务　rc=0
- [FAIL] selftest　rc=1
- [OK] 导出使用遥测　rc=0
- [FAIL] 专项回归套件　rc=1
- [OK] 判定　rc=0

## 专项回归套件（31 通过 / 2 失败 / 共 33）

| 套件 | 结果 | 用时(s) | 结论行 |
|---|---|---|---|
| test_archive_concurrency.py | OK | 0.8 | 结果：通过 13 / 失败 0 / 共 13 |
| test_atomic_io.py | OK | 7.5 | 结果：通过 22 / 失败 0 / 共 22 |
| test_atomic_write.py | OK | 1.3 | 结果：通过 29 / 失败 0 / 共 29 |
| test_delete_project_pointer.py | OK | 12.8 | 结果：通过 32 / 失败 0 |
| test_delete_sweep.py | OK | 3.2 | 结果：通过 15 / 失败 0（共 15 条） |
| test_device_identity.py | FAIL | 0.5 | 结果：通过 10 / 失败 1（共 11 条） |
| test_device_identity_242.py | FAIL | 0.5 | 结果：通过 18 / 失败 2（共 20 条） |
| test_gb_fallback.py | OK | 21.8 | 结果：193 passed, 0 failed |
| test_index_count.py | OK | 0.6 | 结果：通过 10 / 失败 0 |
| test_ledger_authority.py | OK | 1.2 | 结果：通过 15 / 失败 0 |
| test_ledger_units.py | OK | 0.5 | 结果：通过 8 / 失败 0 / 共 8 |
| test_merge_agg.py | OK | 0.1 | 通过 33 项，失败 0 项 |
| test_parsed_cache_path.py | OK | 0.5 | 结果：通过 12 / 失败 0 |
| test_phase_coverage.py | OK | 0.2 | ===== 通过 28 / 失败 0 ===== |
| test_project_audit_log.py | OK | 4.5 | 结果：通过 24 / 失败 0 |
| test_project_backup_complete.py | OK | 4.2 | 汇总：通过 19 / 失败 0 |
| test_project_scope.py | OK | 0.3 | 全部通过 |
| test_readonly_no_write.py | OK | 7.1 | 结果：17 passed, 0 failed |
| test_relations_gate.py | OK | 0.3 | ===== 通过 20 / 失败 0 ===== |
| test_relations_workshops.py | OK | 0.1 | ===== 通过 10 / 失败 0 ===== |
| test_restart_really.py | OK | 55.5 | ===== 通过 48 / 失败 0 ===== |
| test_restore_target.py | OK | 0.1 | ===== 通过 9 / 失败 0 ===== |
| test_scan_heartbeat.py | OK | 130.9 | ===== 通过 29 / 失败 0 ===== |
| test_smart_doc_persist.py | OK | 2.4 | 合计：111 PASS / 0 FAIL |
| test_source_path_fields.py | OK | 12.2 | ===== 通过 19 / 失败 0 ===== |
| test_spatial_ledger_243.py | OK | 0.1 | 通过 ALL / 失败 0 |
| test_template_concurrency.py | OK | 0.6 | 通过 9 项，失败 0 项 |
| test_upload_queue.py | OK | 0.2 | 结果：通过 15 / 失败 0 |
| test_volume_no_overwrite.py | OK | 7.4 | 合计：27 PASS / 0 FAIL |
| test_wb_loop_git.py | OK | 2.2 | ===== 通过 21 / 失败 0 ===== |
| test_workshop_approval.py | OK | 0.8 | 结果：通过 23 / 失败 0 |
| test_workshop_count_244.py | OK | 0.6 | 通过 ALL / 失败 0 |
| test_workshop_source.py | OK | 0.7 | 结果：通过 10 / 失败 0 |
