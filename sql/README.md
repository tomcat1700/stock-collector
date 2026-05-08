# sql

用于存放数据库 migration、初始化脚本、兼容视图脚本和最小验证 SQL。

## 目录约定

- `migrations/`: 版本化迁移脚本

## 开发提示

- 涉及数据库结构变化时，优先采用增量变更、兼容视图或新表迁移
- `kline_daily` 为历史真值层，禁止破坏性修改
- 变更应同步更新 `docs/database/migration-plan.md`
