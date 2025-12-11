# @app.route('/api/cron-update', methods=['GET'])
def cron_update():

    if not all([CMC_API_KEY, NOTION_TOKEN, NOTION_DATABASE_ID]):
        return jsonify({"error": "Missing environment variables."}), 500

    try:
        notion = Client(auth=NOTION_TOKEN)
        print("Notion 客户端初始化成功！")

        list_users_response = notion.users.list()
        pprint(list_users_response)
        # ✅ 修正后的调用方式：直接传递参数
        # response = notion.databases.query(
        #     database_id=NOTION_DATABASE_ID,
        #     filter={
        #         "property": NOTION_SYMBOL_PROPERTY_NAME,
        #         "type": "rich_text",                 # 必须加这一行！v2 的新要求
        #         "rich_text": {
        #             "is_not_empty": True
        #         }
        #     }
        # )
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
        symbol_to_page = {}
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
            return jsonify({"status": "Success", "message": "No symbols found"}), 200

        # CoinMarketCap 批量查询
        symbols_str = ",".join(symbols_list)
        headers = {
            "Accept": "application/json",
            "X-CMC_PRO_API_KEY": CMC_API_KEY,
        }

        params = {
            "symbol": symbols_str,
            "convert": "USD"
        }

        cmc_response = requests.get(CMC_BASE_URL, headers=headers, params=params, timeout=12)
        cmc_response.raise_for_status()
        cmc_data = cmc_response.json()

        price_data = {}
        for symbol in symbols_list:
            try:
                price_data[symbol] = get_price_from_cmc_data(cmc_data, symbol)
                print(f"{symbol}: ${price_data[symbol]:,.4f}")
            except Exception as e:
                print(f"获取 {symbol} 失败: {e}")
                price_data[symbol] = None  # 或 0

        # 更新 Notion 页面
        updated_count = 0
        for symbol, page_id in symbol_to_page.items():
            price = price_data.get(symbol)

            if price is not None:
                # ✅ notion.pages.update 调用方式正确
                notion.pages.update(
                    page_id=page_id,
                    properties={
                        NOTION_PRICE_PROPERTY_NAME: {
                            "number": price
                        }
                    }
                )

                updated_count += 1

        return jsonify({
            "status": "Success",
            "updated": updated_count,
            "symbols": symbols_list
        }), 200

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



@app.route('/test', methods=['GET'])
def test():
    import requests
    from flask import jsonify

    URL = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"
    CMC_API_KEY = ""   # 建议后面改成 os.getenv

    headers = {
        "Accept": "application/json",
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
    }

    params = {
        "symbol": "BTC,ETH,SOL,ADA,DOGE,XRP",
        "convert": "USD"
    }

    try:
        response = requests.get(URL, headers=headers, params=params, timeout=12)
        response.raise_for_status()
        data = response.json()

        # ────── 控制台打印（仅后端看得见） ──────
        print("CMC 请求成功！")
        result_list = []
        for symbol, coin_list in data["data"].items():
            coin = coin_list[0]
            price = coin["quote"]["USD"]["price"]
            change_24h = coin["quote"]["USD"]["percent_change_24h"]
            print(f"{symbol:6}  ${price:12,.4f}    24h: {change_24h:+8.2f}%")
            result_list.append({
                "symbol": symbol,
                "price_usd": round(price, 4),
                "change_24h": round(change_24h, 2)
            })

        # ────── 返回给前端的统一结构 ──────
        return jsonify({
            "success": True,
            "message": "获取价格成功",
            "count": len(result_list),
            "data": result_list,
            "timestamp": data["status"]["timestamp"]
        })

    # ────── 各种异常统一处理 ──────
    except requests.exceptions.HTTPError as e:
        error_msg = response.text if 'response' in locals() else str(e)
        print("CMC HTTP 错误:", e)
        print("响应内容:", error_msg)

        return jsonify({
            "success": False,
            "message": "CMC API HTTP 错误",
            "detail": error_msg[:500]   # 防止太长
        }), 502

    except requests.exceptions.ConnectionError:
        print("CMC 连接失败，网络或域名问题")
        return jsonify({
            "success": False,
            "message": "无法连接到 CoinMarketCap"
        }), 503

    except requests.exceptions.Timeout:
        print("CMC 请求超时")
        return jsonify({
            "success": False,
            "message": "CMC 请求超时"
        }), 504

    except requests.exceptions.RequestException as e:
        print("CMC 其他请求异常:", e)
        return jsonify({
            "success": False,
            "message": "CMC 请求失败",
            "detail": str(e)
        }), 500

    except Exception as e:
        print("未知错误:", e)
        return jsonify({
            "success": False,
            "message": "服务器内部错误",
            "detail": str(e)
        }), 500

