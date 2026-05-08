# migrations

本目录用于存放数据库迁移脚本。

建议命名方式：

```text
001_init_public_baseline.sql
002_add_bar_3s_and_bar_1m.sql
003_add_compatibility_views.sql
```

每个 migration 建议同时说明：

- 变更目标
- 影响范围
- 回滚或兼容方案
- 最小验证方式
