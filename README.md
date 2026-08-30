# 🚀 Crypto Notion Sync API

一个用于 获取加密货币价格 并自动同步到 Notion 数据库 的轻量级 API 服务。
使用 Python + Flask 构建，支持本地运行，也支持部署到 Vercel Serverless。

✨ 功能特性

🔑 基于 x-api-token 的 API 访问权限验证

🪙 调用 CoinMarketCap API 获取实时加密货币价格（5分钟缓存，防止api接口访问过度）

📝 自动写入到 Notion 数据库，每日自动计算并快照响应数据

⏰ 支持外部定时调用 `/api/cron`，自动顺序执行全部同步任务

☁️ 支持本地运行，也支持 Vercel 云端部署

📦 结构清晰，便于扩展新的加密资产和 API


## 📦 本地部署
在根目录创建 .env 文件并填写以下环境变量：

```env
# CoinMarketCap 的 API Key
CMC_API_KEY=你的CMC密钥

# Notion API Token
# https://www.notion.so/profile/integrations
NOTION_TOKEN=你的Notion Token

# Notion 数据库 ID
NOTION_DATABASE_ID=你的数据库ID

# 自定义 API 访问密钥
API_SECRET=你的访问密钥

# 外部定时器访问密钥（未设置时默认复用 API_SECRET）
CRON_SECRET=你的Cron访问密钥

# 快照源数据库ID
NOTION_HOLDINGS_DATABASE_ID

# 快照目标数据库ID
NOTION_SNAPSHOT_DATABASE_ID

# Summary 数据库ID
NOTION_SUMMARY_DATABASE_ID

# Holdings GLobal 数据库ID（账户级累计汇总，如未设置会回退到 NOTION_SUMMARY_DATABASE_ID）
NOTION_HOLDINGS_GLOBAL_DATABASE_ID

# 交易记录库（Crypto Portfolio）数据库ID，用于交易所视角聚合（如未设置会回退到 Holdings 库）
NOTION_PORTFOLIO_DATABASE_ID

# 交易所汇总库数据库ID（每行一个交易所，由 API 写入当前持仓市值/盈亏）
NOTION_EXCHANGE_DATABASE_ID

# 缓存地址
REDIS_URL=Vercel上创建redis后获取

# Supabase 历史价格存储（仅服务端，切勿暴露前端）
SUPABASE_URL=https://你的项目.supabase.co
SUPABASE_SERVICE_ROLE_KEY=你的service_role_key

# Bark 推送地址，例如 https://api.day.app/你的BarkKey
BARK_BASE_URL=你的Bark推送地址

# 可选：Bark 分组和图标
BARK_GROUP=cmc_api
BARK_ICON_URL=https://assets.coingecko.com/coins/images/1/large/bitcoin.png
```
vercel部署直接设置相应环境变量即可

普通 API 和外部定时器使用不同请求头鉴权：

- 普通 API：请求头使用 `x-api-token: 你的TOKEN`
- 外部定时入口 `/api/cron`：请求头使用 `Authorization: Bearer 你的CRON_SECRET`
- 如果未设置 `CRON_SECRET`，`/api/cron` 会复用 `API_SECRET`

## 📁 文件说明

| 文件                   | 说明                                   |
| -------------------- | ------------------------------------ |
| **api/index.py**     | 应用入口，初始化 Flask 并绑定路由（Vercel 也使用此入口）。 |
| **api/api.py**       | 废弃，旧api方法  |
| **lib/notion.py**    | 封装对 Notion API 的读写逻辑。                |
| **lib/utils.py**     | 工具函数，包括基于 `x-api-token` 的访问授权验证。     |
| **vercel.json**      | Vercel Serverless 的入口配置。             |
| **requirements.txt** | 项目依赖列表。                              |


## 🌐部署相关

本地运行时候
```shell
curl -H "x-api-token: 你的TOKEN" http://127.0.0.1:5000/api/cron-update-cache

curl -H "x-api-token: 你的TOKEN" http://127.0.0.1:5000/api/update-account-snapshot?timezone=Asia/Tokyo

curl -H "x-api-token: 你的TOKEN" http://127.0.0.1:5000/api/sync-crypto-summary

curl -H "Authorization: Bearer 你的CRON_SECRET" http://127.0.0.1:5000/api/cron
```

部署到 Vercel 后，`/api/cron` 作为统一入口，由外部定时器按需调用：

```text
GET /api/cron   (Authorization: Bearer 你的CRON_SECRET)
```

`/api/cron` 会按以下顺序执行：

1. `/api/cron-update-cache`
2. `/api/sync-crypto-summary`
3. `/api/update-account-snapshot?timezone=Asia/Tokyo`

三个任务全部成功后，会发送 Bark 通知：

- `group`: `cmc_api`
- 通知图标：Bitcoin 图标

`vercel.json` 不配置任何 Cron（不启用 Vercel 定时任务），由外部定时器负责触发，例如 GitHub Actions、VPS crontab、iOS 快捷指令等。

## 🕐 历史价格（Supabase）

`/api/cron-update-cache` 在获取行情并更新 Notion 的同时，会通过 `lib/supabase_store.py` 把每个币的完整行情快照批量 upsert 到 Supabase 的 `crypto_prices` 表：

| 字段 | 说明 |
| --- | --- |
| `symbol` | 币种符号 |
| `name` | 币种名称 |
| `price` | 最新价格（USD） |
| `change_24h` | 24小时涨跌幅 |
| `market_cap` | 市值 |
| `volume_24h` | 24小时成交量 |
| `cmc_rank` | CoinMarketCap 排名 |
| `recorded_at` | 实际入库时间 |
| `bucket_time` | 小时向下取整的时间（去重键） |
| `source` | 来源，默认 `crypto-price-api` |

- 以 `unique(symbol, bucket_time)` 去重，同一币种同一小时最多一条，配合 upsert 实现幂等写入。
- `SUPABASE_SERVICE_ROLE_KEY` 只能放服务端（Vercel 环境变量），绝不能暴露到前端。

> ⚠️ **时间约定**：`recorded_at`、`bucket_time` 一律以 **UTC（24 小时制 timestamptz）** 存储。读取/画图时请**先转换到目标时区**（如 Asia/Shanghai）再展示，切勿把 UTC 值直接当本地时间使用，否则会有 8 小时偏差。

## 👥 分币种持仓快照（Supabase）

`/api/update-account-snapshot` 在读取持仓并更新账户快照的同时，会通过 `lib/supabase_store.py` 把每个币的持仓状态批量 upsert 到 Supabase 的 `crypto_holdings_snapshot` 表：

| 字段 | 说明 |
| --- | --- |
| `symbol` | 币种符号 |
| `name` | 币种名称 |
| `quantity` | 当前持仓数量 |
| `price` | 当前单价（由 市值/数量 派生） |
| `cost` | 该币种投入成本 |
| `market_value` | 当前市值 |
| `pnl` | 盈亏（市值 − 成本） |
| `pnl_rate` | 收益率 |
| `recorded_at` | 实际入库时间 |
| `bucket_time` | 小时向下取整的时间（去重键） |
| `source` | 来源，默认 `crypto-price-api` |

- 同样以 `unique(symbol, bucket_time)` 去重 + upsert 幂等写入。
- 盈亏依赖「持仓数量 × 价格 − 成本」，随买卖变动，无法由行情事后重建，因此必须以快照形式存档，用于单币种每日盈亏/收益率/市值曲线。
- `SUPABASE_SERVICE_ROLE_KEY` 只能放服务端（Vercel 环境变量），绝不能暴露到前端。

ios上使用shortcuts
```markdown
1. 创建获取URL内容：填写url(Vercel部署后的url)，头部添加x-api-token: 你的TOKEN
2. 创建显示通知：显示URL内容
```

## 🔜TODO
