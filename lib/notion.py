from datetime import datetime
import time
from notion_client import Client
from flask import jsonify


symbol_to_page = {}


def notion_get(notion, NOTION_DATABASE_ID, NOTION_SYMBOL_PROPERTY_NAME):
    """
    Crypto Market 数据库 读取方法
    """
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
    """
    Crypto Market 数据库 更新方法
    """
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
    Holdings 数据库
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


def notion_get_all_holdings_rows(notion, HOLDINGS_DATABASE_ID):
    """
    Holdings 数据库
    【账户聚合读取】方法
    读取全部持仓行（含已清仓/持仓数量<=0 的行），用于「累计」口径的账户汇总。
    """
    db_response = notion.databases.retrieve(database_id=HOLDINGS_DATABASE_ID)
    data_sources = db_response.get("data_sources", [])

    if not data_sources:
        raise ValueError("No data sources found!")

    data_source_id = data_sources[0]["id"]

    response = notion.data_sources.query(
        data_source_id=data_source_id,
    )

    return response["results"]


def notion_upsert_account_summary(
    notion: Client,
    GLOBAL_DB_ID: str,
    total_market_value: float,
    total_cost: float,
    total_cumulative_pnl: float,
):
    """
    更新 Holdings GLobal 的「All Holdings」汇总行（账户级，累计口径）。

    行为：
    - 查找 "All Holdings" 行（Holdings GLobal 汇总所有持仓的那一行）
    - 存在则更新；不存在则创建
    - 账户累计收益率 为 formula，由 Notion 根据 账户累计总成本/账户累计总盈亏 自动计算
    """
    db_response = notion.databases.retrieve(database_id=GLOBAL_DB_ID)
    data_sources = db_response.get("data_sources", [])
    if not data_sources:
        raise ValueError("No data sources found in Holdings GLobal DB")

    data_source_id = data_sources[0]["id"]
    resp = notion.data_sources.query(data_source_id=data_source_id)

    global_row_id = None
    for row in resp["results"]:
        props = row.get("properties", {})
        title_arr = props.get("All Holdings", {}).get("title", [])
        if not title_arr:
            continue
        if title_arr[0]["plain_text"].strip() == "All Holdings":
            global_row_id = row["id"]
            break

    properties = {
        "账户累计总成本": {"number": round(total_cost, 4)},
        "账户累计总盈亏": {"number": round(total_cumulative_pnl, 4)},
    }

    if global_row_id:
        notion.pages.update(
            page_id=global_row_id,
            properties=properties,
        )
        updated = global_row_id
    else:
        page = notion.pages.create(
            parent={"database_id": GLOBAL_DB_ID},
            properties={
                "All Holdings": {
                    "title": [{"text": {"content": "All Holdings"}}]
                },
                **properties,
            },
        )
        updated = page["id"]

    return {"updated": updated}


def notion_sync_summary_values(
    notion: Client,
    HOLDINGS_DB_ID: str,
    SUMMARY_DB_ID: str,
):
    """
    把每币种的「累计总成本 / 累计总盈亏」写入 Crypto Summary 的对应行。

    背景：Crypto Summary 的 累计总成本 / 累计总盈亏 曾是 rollup（汇总持仓对应字段），
    但 Notion 无法对「单 rollup 透传公式」做二次 rollup，跨库汇总恒为 0，
    导致每币种 累计收益率 = 0%。这里改为由 API 直接写入 number。

    行为：
    - 读取 Holdings 全部行（含已清仓）
    - 读取 Crypto Summary 全部行，按 持仓币种 关系匹配到 Holdings 行
    - 把 Holdings 行的 总买入成本（rollup）、累计总盈亏（formula）分别写入 Summary 行的 累计总成本 / 累计总盈亏（number）
    """
    # 1. Holdings 全部行 → {holdings_id: {cost, cumulative_pnl}}
    holdings_db = notion.databases.retrieve(database_id=HOLDINGS_DB_ID)
    holdings_sources = holdings_db.get("data_sources", [])
    if not holdings_sources:
        raise ValueError("No data sources found in Holdings DB")

    holdings_response = notion.data_sources.query(
        data_source_id=holdings_sources[0]["id"],
    )
    holdings_values = {}
    for row in holdings_response["results"]:
        props = row.get("properties", {})
        cost = props.get("总买入成本", {}).get("rollup", {}).get("number") or 0
        cumulative_pnl = (
            props.get("累计总盈亏", {}).get("formula", {}).get("number") or 0
        )
        holdings_values[row["id"]] = {
            "cost": cost,
            "cumulative_pnl": cumulative_pnl,
        }

    # 2. Summary 全部行 → 按 持仓币种 关系匹配，写入 累计总成本 / 累计总盈亏
    db_response = notion.databases.retrieve(database_id=SUMMARY_DB_ID)
    data_sources = db_response.get("data_sources", [])
    if not data_sources:
        raise ValueError("No data sources found in Summary DB")

    summary_response = notion.data_sources.query(
        data_source_id=data_sources[0]["id"],
    )

    updated = []
    for row in summary_response["results"]:
        props = row.get("properties", {})
        rel = props.get("持仓币种", {}).get("relation", [])
        if not rel:
            continue
        values = holdings_values.get(rel[0]["id"])

        if values is None:
            continue

        notion.pages.update(
            page_id=row["id"],
            properties={
                "累计总成本": {"number": round(values["cost"], 4)},
                "累计总盈亏": {"number": round(values["cumulative_pnl"], 4)},
            },
        )
        updated.append(row["id"])

    return {"updated_count": len(updated)}


def notion_get_pending_or_error_holdings(
    notion: Client,
    HOLDINGS_DB_ID: str,
):
    """
    获取需要进行 Summary 同步的 Holdings 行：
    - Summary Sync Status = pending
    - Summary Sync Status = error
    - Summary Sync Status 为空（未设置）
    """

    db_response = notion.databases.retrieve(
        database_id=HOLDINGS_DB_ID
    )

    data_sources = db_response.get("data_sources", [])
    if not data_sources:
        raise ValueError("No data sources found in Holdings DB")

    data_source_id = data_sources[0]["id"]

    # ⚠️ 不在 query 里做复杂筛选，全部拉回后代码判断
    response = notion.data_sources.query(
        data_source_id=data_source_id
    )

    result = []

    for row in response["results"]:
        props = row["properties"]

        status_prop = props.get("Summary Sync Status")

        # 没有这个字段（理论不该发生，但兜底）
        if not status_prop:
            result.append(row)
            continue

        select_val = status_prop.get("select")

        # 为空（未选择）
        if select_val is None:
            result.append(row)
            continue

        status_name = select_val.get("name")

        if status_name in ("pending", "error"):
            result.append(row)

    return result




def mark_holdings_as_synced(notion: Client, rows: list):
    for row in rows:
        notion.pages.update(
            page_id=row["id"],
            properties={
                "Summary Sync Status": {
                    "select": {
                        "name": "synced"
                    }
                }
            }
        )

def mark_holdings_as_error(notion: Client, rows: list, message: str = ""):
    for row in rows:
        notion.pages.update(
            page_id=row["id"],
            properties={
                "Summary Sync Status": {
                    "select": {
                        "name": "error"
                    }
                }
            }
        )


def sync_summary_for_new_holdings_rows(
    notion: Client,
    new_holdings_rows: list,
    SUMMARY_DB_ID: str,
):
    """
    根据 Holdings 行同步 Crypto Summary（最终生产版）

    行为：
    - Summary 唯一键：(币种 + Global/账本)
    - Summary.Global 继承 Holdings.账本
    - 单行失败不中断整体
    - 失败行标记为 error，并打印关键信息
    """

    # ==================================================
    # 1. 读取已有 Summary 的 (symbol, ledger) 键
    # ==================================================
    summary_keys = set()

    db_response = notion.databases.retrieve(
        database_id=SUMMARY_DB_ID
    )

    data_sources = db_response.get("data_sources", [])
    if not data_sources:
        raise ValueError("No data sources found in Summary DB")

    data_source_id = data_sources[0]["id"]

    resp = notion.data_sources.query(
        data_source_id=data_source_id
    )

    for row in resp["results"]:
        props = row.get("properties", {})

        title_arr = props.get("币种", {}).get("title", [])
        if not title_arr:
            continue
        symbol = title_arr[0]["plain_text"].strip()
        if not symbol:
            continue

        ledger_rel = props.get("Global", {}).get("relation", [])
        if not ledger_rel:
            continue
        ledger_id = ledger_rel[0]["id"]

        summary_keys.add((symbol, ledger_id))

    # ==================================================
    # 2. 逐行处理 Holdings（单行容错）
    # ==================================================
    created = []
    failed = []

    for row in new_holdings_rows:
        holding_id = row.get("id")

        try:
            props = row.get("properties", {})

            # ---------- 币种 ----------
            title_arr = props.get("币种", {}).get("title", [])
            if not title_arr:
                raise ValueError("Missing 币种")

            symbol = title_arr[0]["plain_text"].strip()
            if not symbol:
                raise ValueError("Empty 币种")

            # ---------- 账本 ----------
            ledger_rel = props.get("账本", {}).get("relation", [])
            if not ledger_rel:
                raise ValueError("Missing 账本 relation")

            ledger_id = ledger_rel[0]["id"]
            key = (symbol, ledger_id)

            # ---------- 已存在则跳过 ----------
            if key in summary_keys:
                continue

            # ---------- 创建 Summary ----------
            notion.pages.create(
                parent={"database_id": SUMMARY_DB_ID},
                properties={
                    "币种": {
                        "title": [
                            {"text": {"content": symbol}}
                        ]
                    },
                    # 🔑 关键修复点
                    "持仓币种": {
                        "relation": [
                            {
                                "id": holding_id  # 当前这条 Holdings 行
                            }
                        ]
                    },
                    "Global": {
                        "relation": ledger_rel
                    }
                }
            )


            summary_keys.add(key)

            created.append({
                # "holding_id": holding_id,
                "symbol": symbol
                # "ledger_id": ledger_id
            })

        except Exception as e:
            # ==================================================
            # ❌ 单行失败：打印关键信息 + 标记 error
            # ==================================================
            error_msg = str(e)

            print(
                "[Summary Sync ERROR]",
                f"holding_id={holding_id}",
                f"symbol={symbol if 'symbol' in locals() else 'UNKNOWN'}",
                f"ledger_id={ledger_id if 'ledger_id' in locals() else 'NONE'}",
                f"error={error_msg}"
            )

            try:
                notion.pages.update(
                    page_id=holding_id,
                    properties={
                        "Summary Sync Status": {
                            "select": {
                                "name": "error"
                            }
                        }
                    }
                )
            except Exception as update_err:
                print(
                    "[Summary Sync ERROR][Status Update Failed]",
                    f"holding_id={holding_id}",
                    f"error={update_err}"
                )

            failed.append({
                # "holding_id": holding_id,
                "error": error_msg
            })

    return {
        "created_count": len(created),
        "failed_count": len(failed),
        "created": created,
        "failed": failed
    }
