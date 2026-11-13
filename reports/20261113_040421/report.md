# WORKbuddy 自测报告 20261113_040421

- 状态：**failed**
- 代码版本：`c4226ea184a6`
- 开始：2026-11-13 04:04:21　结束：2026-11-13 04:32:55
- 结果：通过 57 / 失败 12 / 跳过 3
- 阶段覆盖：**完整**（5/6）

## 步骤

- [OK] 查远端 HEAD　rc=0
- [OK] git fetch　rc=0
  - From https://github.com/hufanrong/engineering-ai-assistant
 * branch            main       -> FETCH_HEAD
- [OK] 远端无新提交　rc=0
- [OK] taskkill 17036　rc=0
- [OK] 启动服务　rc=0
- [FAIL] 服务健康检查　rc=1
- [OK] 补启动服务　rc=0
- [FAIL] selftest　rc=1
- [OK] 导出使用遥测　rc=0
- [FAIL] 专项回归套件　rc=1
- [OK] 判定　rc=0

## 专项回归套件（30 通过 / 4 失败 / 共 34）

| 套件 | 结果 | 用时(s) | 结论行 |
|---|---|---|---|
| test_archive_concurrency.py | OK | 2.4 | 结果：通过 13 / 失败 0 / 共 13 |
| test_atomic_io.py | FAIL | 2.4 | FAIL: 队列包 20 个一个不少  实得 1 个 |
| test_atomic_write.py | OK | 1.1 | 结果：通过 29 / 失败 0 / 共 29 |
| test_delete_project_pointer.py | OK | 6.5 | 结果：通过 32 / 失败 0 |
| test_delete_sweep.py | OK | 7.6 | 结果：通过 15 / 失败 0（共 15 条） |
| test_device_identity.py | OK | 0.7 | 结果：通过 14 / 失败 0（共 14 条） |
| test_device_identity_242.py | OK | 0.5 | 结果：通过 21 / 失败 0（共 21 条） |
| test_gb_fallback.py | OK | 10.1 | 结果：193 passed, 0 failed |
| test_index_count.py | OK | 0.6 | 结果：通过 10 / 失败 0 |
| test_ledger_authority.py | OK | 1.9 | 结果：通过 15 / 失败 0 |
| test_ledger_units.py | OK | 1.5 | 结果：通过 8 / 失败 0 / 共 8 |
| test_merge_agg.py | OK | 0.2 | 通过 33 项，失败 0 项 |
| test_multi_project_245.py | FAIL | 1.7 | 失败 3 条  ['M9b 当前项目的索引/归属/队列/版本台账一个字节都没变', 'M9c 当前项目的上传队列没有多出包', 'M9d 隔离目录里确实落了解析 |
| test_parsed_cache_path.py | OK | 1.0 | 结果：通过 12 / 失败 0 |
| test_phase_coverage.py | OK | 3.0 | ===== 通过 28 / 失败 0 ===== |
| test_project_audit_log.py | OK | 10.1 | 结果：通过 24 / 失败 0 |
| test_project_backup_complete.py | OK | 2.8 | 汇总：通过 19 / 失败 0 |
| test_project_scope.py | OK | 0.4 | 全部通过 |
| test_readonly_no_write.py | OK | 12.7 | 结果：17 passed, 0 failed |
| test_relations_gate.py | OK | 0.4 | ===== 通过 22 / 失败 0 ===== |
| test_relations_workshops.py | OK | 0.1 | ===== 通过 10 / 失败 0 ===== |
| test_restart_really.py | OK | 56.0 | ===== 通过 48 / 失败 0 ===== |
| test_restore_target.py | OK | 0.2 | ===== 通过 9 / 失败 0 ===== |
| test_scan_heartbeat.py | OK | 496.7 | ===== 通过 29 / 失败 0 ===== |
| test_smart_doc_persist.py | OK | 6.1 | 合计：111 PASS / 0 FAIL |
| test_source_path_fields.py | FAIL | 346.0 | [C5] 临时目录里重解析不得写进真实项目队列 |
| test_spatial_ledger_243.py | OK | 2.9 | 通过 ALL / 失败 0 |
| test_template_concurrency.py | OK | 7.4 | 通过 9 项，失败 0 项 |
| test_upload_queue.py | FAIL | 6.5 |  |
| test_volume_no_overwrite.py | OK | 31.0 | 合计：27 PASS / 0 FAIL |
| test_wb_loop_git.py | OK | 3.1 | ===== 通过 21 / 失败 0 ===== |
| test_workshop_approval.py | OK | 11.3 | 结果：通过 23 / 失败 0 |
| test_workshop_count_244.py | OK | 0.6 | 通过 ALL / 失败 0 |
| test_workshop_source.py | OK | 1.4 | 结果：通过 10 / 失败 0 |
