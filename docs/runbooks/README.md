# runbooks

运行手册目录。

这个目录放的是可直接执行的操作说明。

## 作用

- 记录本地启动、采集运行、校准、同步和故障排查步骤
- 为执行层和联调层提供可复现的操作手册

## 当前真值

- [本地启动.md](/Users/wt/work/stockx/docs/runbooks/本地启动.md)
- [每日业务流程.md](/Users/wt/work/stockx/docs/runbooks/每日业务流程.md)
- [数据采集运行.md](/Users/wt/work/stockx/docs/runbooks/数据采集运行.md)
- [盘后日线校准.md](/Users/wt/work/stockx/docs/runbooks/盘后日线校准.md)
- [板块同步运行.md](/Users/wt/work/stockx/docs/runbooks/板块同步运行.md)
- [故障排查.md](/Users/wt/work/stockx/docs/runbooks/故障排查.md)

## 当前盘后任务口径

- `16:30`：`reconcile_daily(当日) -> sync_daily_basic(当日)`
- `20:00`：`sync_eastmoney_sectors -> sync_eastmoney_sector_stocks`

## 补充资料

- 当前没有单独的补充说明文档；如后续补详细操作示例，可继续放这里

## 历史/不可作为当前依据

- 过时启动参数、旧采集脚本说明应进入 `docs/archive/`
- 运行口径变化时，旧步骤不能直接当当前步骤

## 推荐阅读顺序

1. 先看 [本地启动.md](/Users/wt/work/stockx/docs/runbooks/本地启动.md)
2. 再看对应模块的运行手册
3. 最后看 [故障排查.md](/Users/wt/work/stockx/docs/runbooks/故障排查.md)

## 使用建议

- 先看本地启动，再看模块运行，再看故障排查
- 任何能落地执行的步骤都应写在这里
