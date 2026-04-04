import os

from flask_caching import Cache

cache = Cache()


def init_cache(app):
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    cache.init_app(
        app,
        config={
            "CACHE_TYPE": "RedisCache",
            "CACHE_REDIS_URL": redis_url,
            "CACHE_DEFAULT_TIMEOUT": 60,
        },
    )
