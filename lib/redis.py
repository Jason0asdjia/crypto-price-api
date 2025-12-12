import os
import time
from redis import Redis

# === Redis（Vercel Redis 数据库）配置 ===
REDIS_URL = os.environ.get("REDIS_URL")

# === 缓存配置 ===
CACHE_TTL = 300  # 5分钟
CACHE_KEY_PREFIX = "cmc_api_cache:"

redis_client = None

if REDIS_URL:
    try:
        redis_client = Redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
        print("Redis 连接成功！")
    except Exception as e:
        print("Redis 连接失败，将禁用缓存:", e)
        redis_client = None
else:
    print("未找到 REDIS_URL 环境变量，Redis 缓存禁用")



# === 本地开发模式使用 FakeRedis（仅非 production）===
if not redis_client and os.environ.get("VERCEL_ENV") != "production":
    class FakeRedis:
        def __init__(self):
            self.store = {}
            self.ttl = {}

        def setex(self, key, ttl, value):
            self.store[key] = value
            self.ttl[key] = time.time() + ttl

        def get(self, key):
            if key in self.store and (key not in self.ttl or time.time() < self.ttl[key]):
                return self.store[key]
            self.store.pop(key, None)
            self.ttl.pop(key, None)
            return None

        def ping(self):
            return True

    redis_client = FakeRedis()
    print("Using in-memory FakeRedis for local development")
