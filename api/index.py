from flask import Flask, jsonify, request
import os
import sys
# ==================== Vercel 关键修复 ====================
# 把项目根目录加入 Python 路径，这样才能 import lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from notion_client import APIResponseError, Client
from dotenv import load_dotenv
from pprint import pprint
import time
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from lib.utils import get_cmc_field_data, now_with_timezone
from lib.notion import notion_get, notion_update, notion_get_holdings_rows, notion_create_account_snapshot,\
                        notion_get_pending_or_error_holdings, mark_holdings_as_error, mark_holdings_as_synced,\
                        sync_summary_for_new_holdings_rows




# 加载环境变量
load_dotenv()

app = Flask(__name__)

# === Import Redis module ===
from lib.redis import redis_client, CACHE_TTL, CACHE_KEY_PREFIX


# --- 环境变量配置 (在 Vercel 中设置) ---
CMC_API_KEY = os.environ.get("CMC_API_KEY")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
NOTION_HOLDINGS_DATABASE_ID = os.environ["NOTION_HOLDINGS_DATABASE_ID"]
NOTION_SNAPSHOT_DATABASE_ID = os.environ["NOTION_SNAPSHOT_DATABASE_ID"]
NOTION_SUMMARY_DATABASE_ID = os.environ["NOTION_SUMMARY_DATABASE_ID"]
API_SECRET = os.getenv("API_SECRET")


# --- Notion 属性名 ---
NOTION_SYMBOL_PROPERTY_NAME = "Symbol"
NOTION_PRICE_PROPERTY_NAME = "Price"
NOTION_CHANGE_24H_PROPERTY_NAME = "24H Change"

CMC_BASE_URL = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"


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



@app.route('/api/update-account-snapshot', methods=['GET'])
def update_account_snapshot():
    """
    更新账户快照（Account Snapshot）

    功能：
    - 从 Holdings 数据库读取当前持仓
    - 计算账户总市值 / 总投入 / 总盈亏
    - 写入一条 Snapshot 记录到 Snapshot 数据库

    请求参数（Query）：
    - timezone: IANA 时区名（默认 UTC），如 Asia/Tokyo

    返回：
    - 账户统计汇总信息
    """
    try:
        # 读取并生成快照时间
        tz_name = request.args.get("timezone", "UTC")
        snapshot_time = now_with_timezone(tz_name)

        notion = Client(auth=NOTION_TOKEN)

        holdings = notion_get_holdings_rows(
            notion,
            NOTION_HOLDINGS_DATABASE_ID
        )

        # 计算账户级指标
        total_market_value = 0.0   # 账户总市值
        total_invested = 0.0       # 账户总投入（历史买入成本）

        for row in holdings:
            props = row["properties"]

            # 当前市值（Formula 字段）
            total_market_value += props["当前市值"]["formula"]["number"] or 0

            # 总买入成本（Rollup 字段）
            total_invested += props["总买入成本"]["rollup"]["number"] or 0

        # 总盈亏 = 当前市值 - 总投入
        total_pnl = total_market_value - total_invested

        # 写入 Snapshot 数据库
        notion_create_account_snapshot(
            notion,
            NOTION_SNAPSHOT_DATABASE_ID,
            total_market_value,
            total_invested,
            total_pnl,
            len(holdings),
            snapshot_time
        )

        return jsonify({
            "status": "success",
            "snapshot_time": snapshot_time,
            "timezone": tz_name,
            "总市值": total_market_value,
            "总投入": total_invested,
            "总盈亏": total_pnl,
            "资产数量": len(holdings)
        })

    # ❌ 异常处理（分类型）
    except APIResponseError as e:
        # Notion API 返回的错误（403 / 404 / 429 等）
        return jsonify({
            "error": "Notion API error",
            "message": str(e),
            "status_code": e.status
        }), 502

    except KeyError as e:
        # Notion 字段名不存在 / 拼写错误
        return jsonify({
            "error": "Notion schema error",
            "message": f"Missing property: {str(e)}"
        }), 500

    except ValueError as e:
        # 数据格式错误（如时间解析）
        return jsonify({
            "error": "Value error",
            "message": str(e)
        }), 400

    except Exception as e:
        # 未知错误
        return jsonify({
            "error": "Internal server error",
            "message": str(e)
        }), 500
    

@app.route('/api/sync-crypto-summary', methods=['GET'])
def sync_crypto_summary():
    """
    最终版：
    - 程序自动筛选新增 Holdings（pending）
    - 同步 Summary（继承账本）
    - 保证唯一性
    - 成功后标记 synced，失败标记 error
    """
    try:
        notion = Client(auth=NOTION_TOKEN)

        # ① 筛选“新增的 Holdings”
        new_rows = notion_get_pending_or_error_holdings(
            notion,
            NOTION_HOLDINGS_DATABASE_ID
        )

        if not new_rows:
            return jsonify({
                "status": "skipped",
                "message": "No pending holdings"
            }), 200

        # ② 同步 Summary（原子）
        result = sync_summary_for_new_holdings_rows(
            notion=notion,
            new_holdings_rows=new_rows,
            SUMMARY_DB_ID=NOTION_SUMMARY_DATABASE_ID
        )

        # ③ 标记为 synced
        mark_holdings_as_synced(notion, new_rows)

        return jsonify({
            "status": "success",
            "processed": len(new_rows),
            **result
        }), 200

    except Exception as e:
        # ❌ 出错则标记 error
        try:
            mark_holdings_as_error(notion, new_rows)
        except:
            pass

        return jsonify({
            "error": "Summary sync failed",
            "message": str(e)
        }), 500

# # 仅本地测试用
# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=5000, debug=True)