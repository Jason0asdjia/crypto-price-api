# 🚀 Crypto Notion Sync API

一个用于 获取加密货币价格 并自动同步到 Notion 数据库 的轻量级 API 服务。
使用 Python + Flask 构建，支持本地运行，也支持部署到 Vercel Serverless。

✨ 功能特性

🔑 基于 x-api-token 的 API 访问权限验证

🪙 调用 CoinMarketCap API 获取实时加密货币价格

📝 自动写入到 Notion 数据库

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

```
vercel部署直接设置相应环境变量即可

## 📁 文件说明

| 文件                   | 说明                                   |
| -------------------- | ------------------------------------ |
| **api/index.py**     | 应用入口，初始化 Flask 并绑定路由（Vercel 也使用此入口）。 |
| **api/api.py**       | 废弃，旧api方法  |
| **lib/notion.py**    | 封装对 Notion API 的读写逻辑。                |
| **lib/utils.py**     | 工具函数，包括基于 `x-api-token` 的访问授权验证。     |
| **vercel.json**      | Vercel Serverless 的入口配置。             |
| **requirements.txt** | 项目依赖列表。                              |


## 🌐调试相关

本地运行时候
```shell
curl -H "x-api-token: 你的TOKEN" http://127.0.0.1:5000/api/cron-update-cache
```

ios上使用shortcuts
```markdown
TODO
```