import os
from datetime import datetime, timezone

from supabase import create_client, Client


SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

SOURCE = "crypto-price-api"
TABLE = "crypto_prices"
HOLDINGS_TABLE = "crypto_holdings_snapshot"

supabase_client: Client | None = None

if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        print("Supabase 连接成功！")
    except Exception as e:
        print("Supabase 连接失败，禁用历史写入:", e)
        supabase_client = None
else:
    print("未找到 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY，禁止 Supabase 历史写入")


def floor_to_hour(dt: datetime) -> datetime:
    """
    把时间向下取整到整点小时，作为去重键 bucket_time。
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def save_prices_snapshot(price_data: dict, now_iso: str | None = None):
    """
    把一份价格快照批量写入 crypto_prices。

    参数:
        price_data: {symbol: {"price":..., "change_24h":..., "name":...,
                              "market_cap":..., "volume_24h":..., "cmc_rank":...}}
        now_iso: 可选，ISO 格式时间；默认当前时间（UTC）

    以 (symbol, bucket_time) 为唯一键做 upsert，保证同一小时每个币只保留一条。
    返回写入行数。
    """
    if supabase_client is None:
        print("Supabase 未配置，跳过历史写入")
        return 0

    now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(timezone.utc)
    bucket_time = floor_to_hour(now).isoformat()

    rows = []
    for symbol, info in price_data.items():
        if not info or not info.get("price"):
            continue

        row = {
            "symbol": symbol,
            "name": info.get("name"),
            "price": info["price"],
            "change_24h": info.get("change_24h"),
            "market_cap": info.get("market_cap"),
            "volume_24h": info.get("volume_24h"),
            "cmc_rank": info.get("cmc_rank"),
            "recorded_at": now.isoformat(),
            "bucket_time": bucket_time,
            "source": SOURCE,
        }
        rows.append(row)

    if not rows:
        print("没有可写入的价格数据")
        return 0

    try:
        res = (
            supabase_client.table(TABLE)
            .upsert(rows, on_conflict="symbol,bucket_time")
            .execute()
        )
        inserted = len(getattr(res, "data", []) or [])
        print(f"Supabase 写入 {inserted} 条 ({bucket_time})")
        return inserted
    except Exception as e:
        print(f"Supabase 写入失败: {e}")
        raise


def save_holdings_snapshot(holdings: list, now_iso: str | None = None):
    """
    把一份「分币种持仓快照」批量写入 crypto_holdings_snapshot。

    参数:
        holdings: [{
            "symbol":..., "name":..., "quantity":...,
            "price":..., "cost":..., "market_value":...,
            "pnl":..., "pnl_rate":...
        }]
        now_iso: 可选，ISO 格式时间；默认当前时间（UTC）

    以 (symbol, bucket_time) 为唯一键做 upsert，保证同一小时每个币只保留一条。
    返回写入行数。
    """
    if supabase_client is None:
        print("Supabase 未配置，跳过持仓快照写入")
        return 0

    now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(timezone.utc)
    bucket_time = floor_to_hour(now).isoformat()

    rows = []
    for h in holdings:
        if not h or not h.get("symbol") or not h.get("market_value"):
            continue

        rows.append({
            "symbol": h["symbol"],
            "name": h.get("name"),
            "quantity": h.get("quantity"),
            "price": h.get("price"),
            "cost": h.get("cost"),
            "market_value": h["market_value"],
            "pnl": h.get("pnl"),
            "pnl_rate": h.get("pnl_rate"),
            "recorded_at": now.isoformat(),
            "bucket_time": bucket_time,
            "source": SOURCE,
        })

    if not rows:
        print("没有可写入的持仓数据")
        return 0

    try:
        res = (
            supabase_client.table(HOLDINGS_TABLE)
            .upsert(rows, on_conflict="symbol,bucket_time")
            .execute()
        )
        inserted = len(getattr(res, "data", []) or [])
        print(f"Supabase 持仓快照写入 {inserted} 条 ({bucket_time})")
        return inserted
    except Exception as e:
        print(f"Supabase 持仓快照写入失败: {e}")
        raise
