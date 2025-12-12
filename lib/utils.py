from flask import request, jsonify
import os
API_SECRET = os.getenv("API_SECRET")

def register_token_verifier(app):
    @app.before_request
    def verify_token():
        token = request.headers.get("x-api-token")
        if token != API_SECRET:
            return jsonify({"error": "Invalid token"}), 401
        

def get_cmc_field_data(cmc_data, symbol, field="price"):
    """
    从 CMC v2 quotes/latest 返回的 cmc_data 中安全取出指定 field 的数据。
    field 可为 "price" 或 "percent_change_24h" 等。
    """
    symbol_data = cmc_data.get('data', {}).get(symbol)
    
    if not symbol_data:
        raise ValueError(f"Symbol {symbol} 不存在于返回数据中")
    
    # symbol_data 一定是 list（官方保证）
    if isinstance(symbol_data, list):
        if len(symbol_data) == 0:
            raise ValueError(f"Symbol {symbol} 数据为空")
        # 永远取第一个（99.99% 情况只有一个）
        coin = symbol_data[0]
    elif isinstance(symbol_data, dict):
        # 极少见：某些旧端点返回 dict with "00", "01" keys
        # 按 key 排序取第一个（最可靠的那个）
        keys = sorted(symbol_data.keys(), key=lambda x: int(x) if x.isdigit() else 999)
        coin = symbol_data[keys[0]]
    else:
        raise TypeError(f"意外的数据类型: {type(symbol_data)}")
    
    # 提取所需字段的数据
    if field not in coin['quote']['USD']:
         raise KeyError(f"CMC 数据中缺少字段: {field}")
    
    return coin['quote']['USD'][field]
