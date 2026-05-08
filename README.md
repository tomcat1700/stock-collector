# stock-collector

独立拆分后的 A 股数据采集项目。

## 范围

- 秒级行情采集写入 `public.realtime_quotes`
- 独立分钟聚合写入 `public.kline_minute`
- 盘后日线校准写入 `public.kline_daily`
- `daily_basic` 同步写入 `public.daily_basic`
- 东方财富板块目录 / 成分股同步
- `job_runs` / `data_quality_log` 采集审计

## 目录

```text
collector/
docs/
sql/
```

## 本地配置

请自行创建：

- `collector/config/collector.local.yaml`
- `collector/config/tushare.secrets.local.yaml`

参考样例：

- `collector/config/collector.example.yaml`
- `collector/config/tushare.secrets.example.yaml`

## 说明

- 本仓库不包含本地 secrets、runtime 状态文件和虚拟环境
- 系统服务脚本请按本机路径单独配置
