# ER 图说明 V1.5.2

## 1. 核心实体

- 行情事实层：`realtime_quotes`、`kline_minute`、`kline_daily`
- 日线衍生层：`daily_adj_factor`、`daily_indicator`
- 日度基础指标层：`daily_basic`
- 采集清单：`collector_watchlist`
- 板块：`standard_sectors`、`standard_sector_stocks`
- 审计与质量：`job_runs`、`data_quality_log`
- 当前三张行情事实表均已完成 Timescale hypertable 迁移；`daily_basic` 也已落为 hypertable；历史影子回退表已清理，不是当前业务实体。

## 2. 关系说明

- `collector_watchlist` 是单一采集清单；不再按池分类，通过 `instrument_type` 区分股票和指数
- `realtime_quotes` 作为盘中快照输入，支撑分钟聚合与前端展示
- `kline_minute` 作为统一分钟事实层，`period` 区分不同周期
- `kline_daily` 作为盘后日线真值层
- `daily_adj_factor` 保存股票复权因子，支撑系统自行计算前复权价格
- `daily_indicator` 保存系统 MA 结果，股票口径为前复权 `qfq_close`，指数口径为原始 `close`
- `standard_sectors` 与 `standard_sector_stocks` 构成当前板块目录与成分关系
- `job_runs` 与 `data_quality_log` 负责作业与数据质量审计

## 2.1 已删除的旧板块表

以下旧表已删除，不再属于当前 ER 口径：

- `pools`
- `sector_mapping`
- `sector_operation_log`
- `sector_quotes_daily`
- `sector_sync_log`
- `sectors`

## 3. 版本说明

- V1.5.2 以后，ER 图的真值边界以 current-state 和 migration-plan 为准
- `public.daily_basic` 已落地为日度基础指标层
- 早期草图仅保留历史对照，不作为当前结构依据
