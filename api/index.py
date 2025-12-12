from flask import Flask, jsonify, request
import os
import sys
# ==================== Vercel 关键修复 ====================
# 把项目根目录加入 Python 路径，这样才能 import lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from notion_client import Client
from dotenv import load_dotenv
from pprint import pprint
import time
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from lib.utils import get_cmc_field_data
from lib.notion import notion_get, notion_update

# 加载环境变量
load_dotenv()

app = Flask(__name__)


# --- 环境变量配置 (在 Vercel 中设置) ---
CMC_API_KEY = os.environ.get("CMC_API_KEY")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
API_SECRET = os.getenv("API_SECRET")


# === Vercel KV 缓存配置 ===
# Vercel 会自动注入这些环境变量（只需在 dashboard 开通 KV 并绑定）
KV_URL = os.environ.get("KV_URL")  # Vercel 自动提供


# 初始化 Redis 客户端（兼容 Vercel KV）
redis_client = None
if KV_URL:
    try:
        redis_client = Redis.from_url(KV_URL, decode_responses=True)
        # 测试连接（可选）
        redis_client.ping()
        print("Vercel KV 连接成功！")
    except Exception as e:
        print("Vercel KV 连接失败，将禁用缓存:", e)
        redis_client = None

CACHE_TTL = 300  # 5分钟 = 300秒
CACHE_KEY_PREFIX = "cmc_api_cache:"


# --- Notion 属性名 ---
NOTION_SYMBOL_PROPERTY_NAME = "Symbol"
NOTION_PRICE_PROPERTY_NAME = "Price"
NOTION_CHANGE_24H_PROPERTY_NAME = "24H Change"

CMC_BASE_URL = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"

# 本地开发时用内存模拟（可选）
if not redis_client and os.environ.get("VERCEL_ENV") != "production":
    class FakeRedis:
        def __init__(self):
            self.store = {}
            self.ttl = {}
        def setex(self, key, ttl, value):
            self.store[key] = value
            self.ttl[key] = time.time() + ttl
        def get(self, key):
            if key in self.store and (not key in self.ttl or time.time() < self.ttl[key]):
                return self.store[key]
            self.store.pop(key, None)
            self.ttl.pop(key, None)
            return None
        def ping(self): return True

    redis_client = FakeRedis()
    print("Using in-memory cache for local development")


# 注册 Token 验证中间件
from lib.utils import register_token_verifier
register_token_verifier(app)

@app.route('/api/cron-update-cache', methods=['GET'])
def cron_update_cache():
    if not all([CMC_API_KEY, NOTION_TOKEN, NOTION_DATABASE_ID]):
        return jsonify({"error": "Missing environment variables."}), 500

    try:
         
        notion = Client(auth=NOTION_TOKEN)
        symbols_list = notion_get(notion, NOTION_DATABASE_ID, NOTION_SYMBOL_PROPERTY_NAME)
        # === 缓存逻辑：批量读取已有缓存 ===
        price_data = {}
        symbols_to_fetch = []

        for symbol in symbols_list:
            cache_key_price = f"{CACHE_KEY_PREFIX}{symbol}:price"
            cache_key_change = f"{CACHE_KEY_PREFIX}{symbol}:change"

            cached_price = redis_client.get(cache_key_price) if redis_client else None
            cached_change = redis_client.get(cache_key_change) if redis_client else None

            if cached_price and cached_change:
                price_data[symbol] = {
                    "price": float(cached_price),
                    "change_24h": float(cached_change)
                }
                print(f"Cache hit: {symbol} | price={cached_price} | change={cached_change}")
                continue

            symbols_to_fetch.append(symbol)


        # === 如果全部命中缓存，直接跳过请求 ===
        if not symbols_to_fetch:
            print("All prices from cache!")
        else:
            print(f"Fetching {len(symbols_to_fetch)} symbols from CMC: {symbols_to_fetch}")

            # 构造请求参数
            symbols_str = ",".join(symbols_to_fetch)
            headers = {
                "Accept": "application/json",
                "X-CMC_PRO_API_KEY": CMC_API_KEY,
            }
            params = {
                "symbol": symbols_str,
                "convert": "USD"
            }

            try:
                cmc_response = requests.get(CMC_BASE_URL, headers=headers, params=params, timeout=15)
                cmc_response.raise_for_status()
                cmc_data = cmc_response.json()

                # 写入缓存 + 收集价格
                for symbol in symbols_to_fetch:
                    try:
                        # 价格
                        price = get_cmc_field_data(cmc_data, symbol, "price")

                        # 24小时涨跌幅
                        change_24h = get_cmc_field_data(cmc_data, symbol, "percent_change_24h")

                        # 放入本地数据结构
                        price_data[symbol] = {
                            "price": price,
                            "change_24h": change_24h
                        }

                        # 缓存
                        if redis_client:
                            redis_client.setex(f"{CACHE_KEY_PREFIX}{symbol}:price", CACHE_TTL, price)
                            redis_client.setex(f"{CACHE_KEY_PREFIX}{symbol}:change", CACHE_TTL, change_24h)
                            print(f"Fresh {symbol}: ${price:,.4f} -> cached for 5min")
                    except Exception as e:
                        print(f"获取 {symbol} 失败: {e}")
                        price_data[symbol] = None

            except requests.exceptions.RequestException as e:
                print("CMC 请求失败:", e)
                # CMC 请求失败 fallback（读取旧缓存）
                cached_price = redis_client.get(f"{CACHE_KEY_PREFIX}{symbol}:price")
                cached_change = redis_client.get(f"{CACHE_KEY_PREFIX}{symbol}:change")

                if cached_price and cached_change:
                    price_data[symbol] = {
                        "price": float(cached_price),
                        "change_24h": float(cached_change)
                    }
                    print(f"Fallback to old cache for {symbol}")
                else:
                    price_data[symbol] = None



        # 更新 Notion 页面
        updated_count = notion_update(
            notion,
            price_data,
            NOTION_PRICE_PROPERTY_NAME,
            NOTION_CHANGE_24H_PROPERTY_NAME
        )


        return jsonify({
            "status": "Success",
            "updated": updated_count,
            "symbols": symbols_list
        }), 200

    except ValueError as e:
        return jsonify({"status": "Success", "message": "No symbols found"}), 200

    except requests.exceptions.HTTPError as e:
        # 处理 CMC API 错误
        try:
            error_data = e.response.json()
            cmc_error = error_data.get('status', {}).get('error_message', f"HTTP Error: {e.response.status_code}")
            return jsonify({"error": f"CMC API 错误: {cmc_error}"}), e.response.status_code
        except:
            return jsonify({"error": f"CMC API HTTP 错误: {e}"}), e.response.status_code

    except Exception as e:
        # 处理其他未知错误
        return jsonify({"error": f"Internal Server Error: {str(e)}"}), 500



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)