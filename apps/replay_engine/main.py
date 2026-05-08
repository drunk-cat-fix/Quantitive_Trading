import json
import time
from datetime import datetime
import ccxt
import redis
from libs.core.config import settings
from libs.core.logger import get_logger

logger = get_logger('replay_engine')


def run() -> None:
    if not settings.replay_enabled:
        logger.info('replay_disabled')
        while True:
            time.sleep(3600)

    r = redis.from_url(settings.redis_url, decode_responses=True)
    ex = ccxt.binance({'enableRateLimit': True})
    symbol = f"{settings.symbol[:-4]}/USDT"

    logger.info('fetching_history', symbol=symbol, timeframe=settings.timeframe, limit=settings.replay_limit)
    rows = ex.fetch_ohlcv(symbol, timeframe=settings.timeframe, limit=settings.replay_limit)

    logger.info('replay_start', bars=len(rows), speed_ms=settings.replay_speed_ms)
    for row in rows:
        ts_ms, o, h, l, c, v = row
        bar = {
            'symbol': settings.symbol,
            'open': float(o),
            'high': float(h),
            'low': float(l),
            'close': float(c),
            'volume': float(v),
            'ts': datetime.utcfromtimestamp(ts_ms / 1000).isoformat(),
            'is_closed': True,
            'is_replay': True,
        }
        r.publish('md.kline', json.dumps(bar))
        r.set('md.last_price', str(c))
        time.sleep(max(settings.replay_speed_ms, 1) / 1000)

    logger.info('replay_done')


if __name__ == '__main__':
    run()
