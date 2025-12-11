from flask import request, jsonify
import os
API_SECRET = os.getenv("API_SECRET")

def register_token_verifier(app):
    @app.before_request
    def verify_token():
        token = request.headers.get("x-api-token")
        if token != API_SECRET:
            return jsonify({"error": "Invalid token"}), 401
        

def get_price_from_cmc_data(cmc_data, symbol):
    """
    从 CMC v2 quotes/latest 返回的 cmc_data 中安全取出 price
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
    
    return coin['quote']['USD']['price']
