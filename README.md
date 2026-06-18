# 🚀 Crypto Notion Sync API

一个用于 获取加密货币价格 并自动同步到 Notion 数据库 的轻量级 API 服务。
使用 Python + Flask 构建，支持本地运行，也支持部署到 Vercel Serverless。

✨ 功能特性

🔑 基于 x-api-token 的 API 访问权限验证

🪙 调用 CoinMarketCap API 获取实时加密货币价格（5分钟缓存，防止api接口访问过度）

📝 自动写入到 Notion 数据库，每日自动计算并快照响应数据

⏰ 支持 Vercel Cron 统一触发 `/api/cron`，自动顺序执行全部同步任务

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

# Vercel Cron 访问密钥（未设置时默认复用 API_SECRET）
CRON_SECRET=你的Cron访问密钥

# 快照源数据库ID
NOTION_HOLDINGS_DATABASE_ID

# 快照目标数据库ID
NOTION_SNAPSHOT_DATABASE_ID

# Summary 数据库ID
NOTION_SUMMARY_DATABASE_ID

# 缓存地址
REDIS_URL=Vercel上创建redis后获取

# Bark 推送地址，例如 https://api.day.app/你的BarkKey
BARK_BASE_URL=你的Bark推送地址

# 可选：Bark 分组和图标
BARK_GROUP=cmc_api
BARK_ICON_URL=https://assets.coingecko.com/coins/images/1/large/bitcoin.png
```
vercel部署直接设置相应环境变量即可

普通 API 和 Vercel Cron 使用不同请求头鉴权：

- 普通 API：请求头使用 `x-api-token: 你的TOKEN`
- Vercel Cron 入口 `/api/cron`：请求头使用 `Authorization: Bearer 你的CRON_SECRET`
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

Vercel 部署后会读取 `vercel.json` 中的 Cron 配置，定时调用统一入口：

```text
/api/cron
```

当前定时任务按 `Asia/Tokyo` 时间每天执行 4 次：

1. 00:00
2. 05:00
3. 12:00
4. 17:00

Vercel Cron 使用 UTC 时间，所以 `vercel.json` 中配置为 `0 3,8,15,20 * * *`。

`/api/cron` 会按以下顺序执行：

1. `/api/cron-update-cache`
2. `/api/sync-crypto-summary`
3. `/api/update-account-snapshot?timezone=Asia/Tokyo`

三个任务全部成功后，会发送 Bark 通知：

- `group`: `cmc_api`
- 通知图标：Bitcoin 图标

原来的三个 API 仍然可以被外部调用，调用方式不变；如果旧的外部定时器继续运行，会和 Vercel Cron 重复执行，建议部署验证后关闭旧定时器。

ios上使用shortcuts
```markdown
1. 创建获取URL内容：填写url(Vercel部署后的url)，头部添加x-api-token: 你的TOKEN
2. 创建显示通知：显示URL内容
```

## 🔜TODO
