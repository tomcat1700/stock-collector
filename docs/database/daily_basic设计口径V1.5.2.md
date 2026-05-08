# daily_basic 设计口径 V1.5.2

> 状态：设计主线口径，尚未进入 current-state 事实层。  
> 用途：在 `bs / collector` 交付前，先统一 `public.daily_basic` 的表职责、键关系、字段单位和迁移边界。

## 1. 目标

新增 `public.daily_basic`，作为与 `public.kline_daily` 对齐的日度基础指标超表。

这张表用于承载 Tushare `daily_basic` 指标，不再继续往 `kline_daily` 混塞基础指标字段。

## 2. 与 `kline_daily` 的关系

- `kline_daily`
  - 继续承载日线 OHLCV 真值
- `daily_basic`
  - 承载日度基础指标

两张表按同一业务键对齐：

- `instrument_id`
- `trade_date`

原则：

- 同键对齐，不互相替代
- 行情真值和基础指标分表维护
- 业务查询按需要 join，不再把基础指标长期塞入 `kline_daily`

## 3. 表结构口径

- 表名：`public.daily_basic`
- 类型：Timescale hypertable
- 时间列：`trade_date`

建议主键 / 业务键：

- `(instrument_id, trade_date)`

## 4. 首批字段与单位

- `turnover_rate`
  - 含义：换手率
  - 单位：`%`
- `share`
  - 含义：股本 / 流通股本类股数指标，具体以接入字段定义为准
  - 单位：`万股`
- `market_cap`
  - 含义：总市值 / 流通市值类市值指标，具体以接入字段定义为准
  - 单位：`万元`

## 5. current-state 与 design 的边界

当前阶段只形成设计口径，不应写成 current-state 已完成事实。

在 `bs / collector` 交付并完成真实库核验前：

- 允许写入：
  - `docs/database/`
  - 必要的 `docs/design/`
- 不允许写入：
  - `docs/current-state/当前系统现状.md` 的已完成事实区
  - `docs/current-state/表与采集链路.md` 的现行表区

## 6. 后续需要更新的位置

实现落地后，再回写：

- `docs/current-state/当前系统现状.md`
- `docs/current-state/表与采集链路.md`
- `docs/database/migration-plan.md`
- `docs/database/ER图说明.md`

## 7. 一句话口径

`public.daily_basic` 是与 `kline_daily` 同键对齐的日度基础指标超表，承载 Tushare `daily_basic` 指标，不再把基础指标继续混塞进 `kline_daily`。
