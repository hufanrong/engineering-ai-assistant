# WORKbuddy 自测报告 20261112_230413

- 状态：**failed**
- 代码版本：`b897433170d7`
- 开始：2026-11-12 23:04:13　结束：2026-11-12 23:19:44
- 结果：通过 74 / 失败 1 / 跳过 2
- 阶段覆盖：**完整**（5/6）

## 步骤

- [OK] 查远端 HEAD　rc=0
- [OK] git fetch　rc=0
  - From https://github.com/hufanrong/engineering-ai-assistant
 * branch            main       -> FETCH_HEAD
- [OK] 远端无新提交　rc=0
- [OK] taskkill 13704　rc=0
- [OK] 启动服务　rc=0
- [FAIL] selftest　rc=1
- [OK] 导出使用遥测　rc=0
- [FAIL] 专项回归套件　rc=1
- [OK] 判定　rc=0

## 专项回归套件（30 通过 / 4 失败 / 共 34）

| 套件 | 结果 | 用时(s) | 结论行 |
|---|---|---|---|
| test_archive_concurrency.py | OK | 0.8 | 结果：通过 13 / 失败 0 / 共 13 |
| test_atomic_io.py | FAIL | 3.2 | FAIL: 队列包 20 个一个不少  实得 1 个 |
| test_atomic_write.py | OK | 1.3 | 结果：通过 29 / 失败 0 / 共 29 |
| test_delete_project_pointer.py | OK | 10.2 | 结果：通过 32 / 失败 0 |
| test_delete_sweep.py | OK | 3.5 | 结果：通过 15 / 失败 0（共 15 条） |
| test_device_identity.py | OK | 0.5 | 结果：通过 14 / 失败 0（共 14 条） |
| test_device_identity_242.py | OK | 0.5 | 结果：通过 21 / 失败 0（共 21 条） |
| test_gb_fallback.py | OK | 11.4 | 结果：193 passed, 0 failed |
| test_index_count.py | OK | 0.6 | 结果：通过 10 / 失败 0 |
| test_ledger_authority.py | OK | 1.2 | 结果：通过 15 / 失败 0 |
| test_ledger_units.py | OK | 0.5 | 结果：通过 8 / 失败 0 / 共 8 |
| test_merge_agg.py | OK | 0.1 | 通过 33 项，失败 0 项 |
| test_multi_project_245.py | FAIL | 0.9 | 失败 3 条  ['M9b 当前项目的索引/归属/队列/版本台账一个字节都没变', 'M9c 当前项目的上传队列没有多出包', 'M9d 隔离目录里确实落了解析 |
| test_parsed_cache_path.py | OK | 0.6 | 结果：通过 12 / 失败 0 |
| test_phase_coverage.py | OK | 0.3 | ===== 通过 28 / 失败 0 ===== |
| test_project_audit_log.py | OK | 4.5 | 结果：通过 24 / 失败 0 |
| test_project_backup_complete.py | OK | 3.7 | 汇总：通过 19 / 失败 0 |
| test_project_scope.py | OK | 0.3 | 全部通过 |
| test_readonly_no_write.py | OK | 7.2 | 结果：17 passed, 0 failed |
| test_relations_gate.py | OK | 0.4 | ===== 通过 22 / 失败 0 ===== |
| test_relations_workshops.py | OK | 0.1 | ===== 通过 10 / 失败 0 ===== |
| test_restart_really.py | OK | 55.6 | ===== 通过 48 / 失败 0 ===== |
| test_restore_target.py | OK | 0.3 | ===== 通过 9 / 失败 0 ===== |
| test_scan_heartbeat.py | OK | 118.4 | ===== 通过 29 / 失败 0 ===== |
| test_smart_doc_persist.py | OK | 2.3 | 合计：111 PASS / 0 FAIL |
| test_source_path_fields.py | FAIL | 8.8 | [C5] 临时目录里重解析不得写进真实项目队列 |
| test_spatial_ledger_243.py | OK | 0.1 | 通过 ALL / 失败 0 |
| test_template_concurrency.py | OK | 0.6 | 通过 9 项，失败 0 项 |
| test_upload_queue.py | FAIL | 0.2 |  |
| test_volume_no_overwrite.py | OK | 7.5 | 合计：27 PASS / 0 FAIL |
| test_wb_loop_git.py | OK | 2.3 | ===== 通过 21 / 失败 0 ===== |
| test_workshop_approval.py | OK | 0.8 | 结果：通过 23 / 失败 0 |
| test_workshop_count_244.py | OK | 0.7 | 通过 ALL / 失败 0 |
| test_workshop_source.py | OK | 0.8 | 结果：通过 10 / 失败 0 |
