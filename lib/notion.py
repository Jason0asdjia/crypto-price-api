from datetime import datetime
import time
from notion_client import Client
from flask import jsonify


symbol_to_page = {}


def notion_get(notion, NOTION_DATABASE_ID, NOTION_SYMBOL_PROPERTY_NAME):

    db_response = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
    data_sources = db_response.get("data_sources", [])  # 列表，可能多个
    if data_sources:
        data_source_id = data_sources[0]["id"]  # 假设用第一个源；多源时需循环或指定
    else:
        raise ValueError("No data sources found!")

    response = notion.data_sources.query(
            **{
                "data_source_id": data_source_id,
            }
        )
    symbols_list = []

    for result in response['results']:
        try:
            # 尝试获取 Symbol 属性的内容
            symbol_prop = result['properties'][NOTION_SYMBOL_PROPERTY_NAME]
            # 假设 Symbol 是 Rich Text 类型，提取纯文本并格式化
            symbol = symbol_prop['rich_text'][0]['plain_text'].strip().upper()
            if symbol:
                symbol_to_page[symbol] = result['id']
                symbols_list.append(symbol)
        except (KeyError, IndexError):
            # 忽略不符合预期结构的页面
            continue

    if not symbols_list:
        raise ValueError("symbols_list is empty")
    
    return symbols_list

def notion_update(notion, price_data, PRICE_FIELD, CHANGE_FIELD):
    updated_count = 0

    for symbol, page_id in symbol_to_page.items():
        info = price_data.get(symbol)

        if not info:
            continue

        notion.pages.update(
            page_id=page_id,
            properties={
                PRICE_FIELD: {"number": info["price"]},
                CHANGE_FIELD: {"number": info["change_24h"]},
            }
        )
        updated_count += 1

    return updated_count


def notion_get_holdings_rows(notion, HOLDINGS_DATABASE_ID):
    """
    【账户聚合读取】方法
    当前有效持仓的所有行
    """
    db_response = notion.databases.retrieve(database_id=HOLDINGS_DATABASE_ID)
    data_sources = db_response.get("data_sources", [])

    if not data_sources:
        raise ValueError("No data sources found!")

    data_source_id = data_sources[0]["id"]

    response = notion.data_sources.query(
        data_source_id=data_source_id,
        filter={
            "property": "当前持仓数量",
            "number": {"greater_than": 0}
        }
    )

    return response["results"]


def notion_create_account_snapshot(
    notion,
    SNAPSHOT_DATABASE_ID,
    total_market_value,
    total_invested,
    total_pnl,
    asset_count,
    snapshot_time
):
    """
    【Snapshot 写入】方法
    :param asset_count: Description
    """

    # 解析 ISO 时间字符串
    dt = datetime.fromisoformat(snapshot_time)

    date_str = dt.strftime("%Y-%m-%d")
    am_pm = "AM" if dt.hour < 12 else "PM"
    
    notion.pages.create(
        parent={"database_id": SNAPSHOT_DATABASE_ID},
        properties={
            # Title 是必填
            "Title": {
                "title": [
                    {
                        "text": {
                            "content": f"Snapshot {date_str} {am_pm}"
                        }
                    }
                ]
            },

            "时间": {
                "date": {
                    "start": snapshot_time
                }
            },

            "总市值": {
                "number": round(total_market_value, 4)
            },

            "总投入": {
                "number": round(total_invested, 4)
            },

            "总盈亏": {
                "number": round(total_pnl, 4)
            },

            # 总收益率是 Formula，不写

            "Asset Count": {
                "number": asset_count
            },

            "Snapshot Source": {
                "select": {
                    "name": "API"
                }
            }
        }
    )