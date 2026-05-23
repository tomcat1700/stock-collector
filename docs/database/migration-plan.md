# migration plan V1.5.2

## 1. 当前基线

> 说明：本文件记录的是已经完成的 Timescale 迁移事实、当前可用回退路径和后续数据库演进原则，不再是“草案未执行”。

当前数据库真实 schema 为 `public`。

2026-04-07 晚间已完成 Timescale hypertable 迁移，当前三张主事实表均已转为 hypertable：

- `public.realtime_quotes`
  - chunk interval：`1 day`
- `public.kline_minute`
  - chunk interval：`30 days`
- `public.kline_daily`
  - chunk interval：`365 days`
  - 行数：`7,239,482`
- `public.daily_basic`
  - chunk interval：`365 days`
  - 当前已完成 Timescale hypertable 初始化

Timescale 版本：

- `timescaledb`：`2.26.1`

## 2. 已完成的迁移事实

### 2.1 主事实层

- `realtime_quotes`
  - 已转为 Timescale hypertable
  - 仍承担秒级盘中事实层
- `kline_minute`
  - 已转为 Timescale hypertable
  - 统一承载 `1/5/15/30/60` 分钟周期
- `kline_daily`
  - 已转为 Timescale hypertable
  - 仍承担盘后日线真值层
- `daily_basic`
  - 已转为 Timescale hypertable
  - 承担日度基础指标层

### 2.2 `kline_daily` 影子表迁移与后续清理

- `kline_daily` 采用影子表迁移完成切换。
- 迁移完成后曾短期保留影子回退表 `public.kline_daily_pre_timescale_20260407`。
- 由于后续日线回补已使该影子表与当前 `kline_daily` 发生偏离，影子回退表已于 `2026-04-08` 删除。
- 当前不再依赖库内影子切回做 `kline_daily` 回滚。

### 2.3 过渡对象状态

已替换 / 已清理对象保持以下口径：

- `kline_second`
- `bar_3s`
- `bar_1m`
- `bar_30m`
- `v_bar_5m`
- `v_bar_15m`
- `v_bar_60m`

### 2.4 盘中历史窗口清理

- `realtime_quotes` 与 `kline_minute` 已于 `2026-04-08` 清理 `2026-04-07` 以前的历史盘中数据。
- 本次清理不影响 `kline_daily`。
- 当前 `realtime_quotes` 保留口径：由 `cleanup_realtime_quotes.py` 保留最近 `10` 个实际采集交易日。
- 当前 `kline_minute` 保留口径：由 `cleanup_kline_minute.py` 保留最近 `45` 个实际采集交易日。

### 2.5 日线历史窗口清理

- `kline_daily` 曾于 `2026-04-08` 清理 `2026-04-07` 以前的历史日线数据。
- 随后已于 `2026-04-08` 从远端库 `192.168.10.50:7007/stock` 回灌恢复历史，当前历史范围恢复到 `2010-01-28` 起。
- 后续新的日线保留窗口已收敛为 `>= 2020-01-01`。
- 这条窗口调整尚待 `bs` 执行完成并核验；在完成前，不应回写成 current-state 已完成事实。

## 3. 迁移与回滚原则

- 已完成迁移事实优先于历史草案。
- `kline_daily` 历史真值层禁止破坏性修改。
- 若未来继续演进 Timescale 参数，应在 current-state 先写清当前事实，再补 migration 说明。
- 如需回滚 `kline_daily`，应依赖数据库备份/恢复，而不是影子切回。
- 对 `realtime_quotes` 和 `kline_minute` 不建议做反向普通表恢复；如需极端回退，应依赖备份恢复或重建。

## 4. 验证方式

执行以下验证：

- 检查 `realtime_quotes`、`kline_minute`、`kline_daily` 仍可正常查询
- 检查三张主事实表均为 hypertable
- 检查 `timescaledb` 版本为 `2.26.1`
- 检查 `kline_daily_pre_timescale_20260407` 已不存在
- 随机抽样同一标的同一时间段，核对查询结果与迁移前口径一致

## 5. 后续数据库演进原则

- 任何新增事实表都应先判断是否能复用 `realtime_quotes`、`kline_minute`、`kline_daily` 的既有边界。
- `kline_daily` 后续保留窗口按 `>= 2020-01-01` 收敛。
- `realtime_quotes` 与 `kline_minute` 分别由独立维护任务按交易日滚动清理；`kline_daily` 不跟随盘中事实层清理。
- `public.daily_basic` 已新增，并与 `kline_daily` 按 `(instrument_id, trade_date)` 同键对齐，不再继续混塞进 `kline_daily`。
- `public.daily_basic` 当前为 Timescale hypertable，时间列为 `trade_date`。
- `public.daily_basic` 首批指标以 Tushare `daily_basic` 为准，字段单位统一写清：
  - `turnover_rate`：`%`
  - `share`：`万股`
  - `market_cap`：`万元`
- `public.aggregate_15min_kline` / `aggregate_30min_kline` / `aggregate_60min_kline` 已于 `017_fix_session_bucket_alignment_for_multi_period_kline.sql` 修正为交易时段对齐分桶：
  - 上午起点 `09:30`
  - 下午起点 `13:00`
  - 不再生成 `09:15 / 09:00 / 08:30` 这类非业务时间桶
- 未来若引入 continuous aggregate、压缩或保留策略，应先明确 current-state 中的已验证事实，再写 design。
- 历史日线真值层仍然禁止破坏性修改。
- 迁移前准备类材料可保留为历史参考，但不能再放进主判断链路。

## 6. 旧版说明

- 旧的 Timescale“准备清单”可以保留为历史记录，但当前完成事实以本文件和 current-state 为准。
- 旧版数据库设计说明已下沉到 `docs/design/old/`。
- 历史 DDL 草案仅作对照，不替代当前迁移结果。
