# collector

负责外部行情采集、主备切换、实时聚合、盘后校准、板块同步，以及作业与数据质量日志落库。

## 核心事实链路（当前已确认）

- `public.realtime_quotes`：秒级快照层（写入口）
- `public.kline_minute`：统一分钟层，`period` 维度区分 `1/5/15/30/60`
- `public.kline_daily`：盘后日线真值层（历史必须保留）

禁止回归到的过渡对象：

- `public.bar_3s`
- `public.bar_1m`
- `public.bar_30m`
- `public.kline_second`
- `public.v_bar_5m` / `public.v_bar_15m` / `public.v_bar_60m`

## 目标链路（V1.5.2 当前口径）

1. 采集任务将快照写入 `realtime_quotes`。
2. 通过独立聚合进程从 `realtime_quotes` 按 1/5/15/30/60 形成分钟/多周期事实表。
3. 日终按盘后策略重建/校准 `kline_daily`。
4. `backend` 和 `frontend` 只读 `public` 事实层，不直接请求第三方源。
5. 运行态状态通过 `collector/runtime/source_failover_state.json` 统一记录。

## 任务划分

- 现货行情采集 Worker：拉取快照到 `realtime_quotes`
- 周期聚合：维护 `public.kline_minute.period`
- 日线盘后校准：修复当日缺失、覆盖异常、补齐字段一致性
- 日度基础指标同步：维护 `public.daily_basic`
- 板块同步任务：维护板块元数据与股票映射
- 日志：`job_runs` 记录任务生命周期与计数；`data_quality_log` 记录采集/聚合质量问题

## 当前脚本

- `collect_realtime.py`：拉取采集清单实时行情并写入 `public.realtime_quotes`
- `run_realtime_loop.py`：按固定间隔循环执行实时采集
  - 当前主源为 `sina`，主配置 cadence 为 `2s`
  - 正常连续采集窗口：工作日 `09:29:56-11:30:03`、`12:59:58-15:00:03`
  - `sina` 写入必须携带 source-side `日期+时间`
  - 当前依赖 `(instrument_id, quote_time)` 主键和 source-side timestamp CHECK 约束去重，重复快照走 `ON CONFLICT DO NOTHING`
  - 非交易时段不写 heartbeat；交易时段 heartbeat 按 `2s` 节流
  - `empty_payload` / `stale_snapshot` 会被视为软失败，仅触发退避，不累计主备切换计数
  - 兼容旧启动脚本：`collector/.venv/bin/python` 会转发到当前可用解释器，供历史 `stock-collector-launch.sh` 直接调用
- `reconcile_daily.py`：按交易日从 Tushare 拉取日 K 并回写 `public.kline_daily`
- `sync_index_daily_history.py`：按指数从 Tushare `index_daily` 回填指数历史日 K
- `sync_daily_basic.py`：按 `trade_date` 或日期区间从 Tushare 拉取并写入 `public.daily_basic`
- `sync_daily_adj_factor.py`：按交易日从 Tushare 拉取股票复权因子并写入 `public.daily_adj_factor`
- `calculate_daily_indicator.py`：基于本地 `kline_daily` 和 `daily_adj_factor` 计算全量 MA 指标并写入 `public.daily_indicator`
- `cleanup_realtime_quotes.py`：按 `realtime_quotes.trade_date` 保留最近 10 个实际采集交易日的秒级快照
- `cleanup_kline_minute.py`：按 `kline_minute.trade_date` 保留最近 45 个实际采集交易日的分钟线
- `source_probe.py`：检测 AkShare 实时与日线源是否可用
- `sync_eastmoney_sectors.py`：同步东方财富板块目录
- `sync_eastmoney_sector_stocks.py`：同步东方财富板块成分股到 `public.standard_sector_stocks`
- `run_minute_aggregation_loop.py`：独立按频率从 `realtime_quotes` 聚合 `1/5/15/30/60` 分钟线
- `runtime_control.py`：collector 运行态与 failover state 读写助手

- 当前盘后任务顺序：
  - `16:30`：`reconcile_daily(当日) -> sync_daily_basic(当日) -> sync_daily_adj_factor(当日) -> calculate_daily_indicator(当日)`
  - `20:00`：`sync_eastmoney_sectors -> sync_eastmoney_sector_stocks`
  - `21:30`：`cleanup_realtime_quotes -> cleanup_kline_minute -> cleanup_data_quality_log`

## 当前已落地脚本

- `sync_eastmoney_sectors.py`
  - 从东方财富 `sidemenu_new.json` 同步行业板块和概念板块字典
  - 当前写入：
    - `public.standard_sectors`
  - 失败与异常写入：
    - `public.data_quality_log`
  - 任务生命周期写入：
    - `public.job_runs`

- `sync_eastmoney_sector_stocks.py`
  - 以 `public.standard_sectors` 中的 `source='eastmoney'` 板块为目标，逐板同步成分股
  - 只有通过完整性校验的板块才会替换 `public.standard_sector_stocks` 中的旧成员，避免上游返回不完整时误删真值
  - 写入：
    - `public.standard_sector_stocks`
  - 失败板块写入：
    - `public.data_quality_log`
  - 任务生命周期写入：
    - `public.job_runs`

## 约束

- 不在 collector 中写业务评分、策略决策或交易执行逻辑。
- 不引入外部端口级决策流程；仅做数据抓取、聚合、校验与审计。
- 不直接重建 `kline_daily` 历史；任何修复应避免破坏全量历史。
- 不把源切换状态散落在多个脚本里；统一走 `runtime_control.py` 和 runtime state 文件。
- 源切换只由真实采集故障触发；空采集清单、空 payload、陈旧快照不应被当成 failover 信号。
- 在改采集链路前，先补齐并同步 `docs/current-state/`。

## 当前链路核对要求（本版本固定）

- `realtime_quotes` 为唯一秒级写入入口。
- `kline_minute.period = 1/5/15/30/60` 为唯一周期口径。
- 盘后职责边界为 `reconcile_daily`（日线）、`sync_daily_basic`（日度基础指标）、`sync_daily_adj_factor`（复权因子）、`calculate_daily_indicator`（系统 MA）与板块同步。
- `job_runs` / `data_quality_log` 是 collector 数据链路可观测性唯一入口。
