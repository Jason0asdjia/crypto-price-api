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
