import asyncio
import json
from datetime import datetime
import redis
import websockets
from libs.core.config import settings
from libs.core.db import SessionLocal
from libs.core.models import MarketBar, PriceTick
from libs.core.logger import get_logger

logger = get_logger('market_data')


def save_bar(bar: dict) -> None:
    with SessionLocal() as db:
        db.add(
            MarketBar(
                symbol=settings.symbol,
                timeframe=settings.timeframe,
                open=bar['open'],
                high=bar['high'],
                low=bar['low'],
                close=bar['close'],
                volume=bar['volume'],
                ts=bar['ts'],
            )
        )
        db.commit()


def save_tick(price: float, ts: datetime) -> None:
    with SessionLocal() as db:
        db.add(PriceTick(symbol=settings.symbol, price=price, ts=ts))
        db.commit()


async def run() -> None:
    r = redis.from_url(settings.redis_url, decode_responses=True)
    kline_stream = f"{settings.symbol.lower()}@kline_{settings.timeframe}"
    ticker_stream = f"{settings.symbol.lower()}@bookTicker"
    url = f"wss://stream.binance.com:9443/stream?streams={kline_stream}/{ticker_stream}"
    logger.info('connecting', url=url)
    last_tick_persist_ts = 0.0

    async for ws in websockets.connect(url, ping_interval=20, ping_timeout=20):
        try:
            async for msg in ws:
                payload = json.loads(msg)
                stream = payload.get('stream', '')
                data = payload.get('data', {})

                if '@kline_' in stream:
                    k = data.get('k', {})
                    bar = {
                        'open': float(k.get('o', 0)),
                        'high': float(k.get('h', 0)),
                        'low': float(k.get('l', 0)),
                        'close': float(k.get('c', 0)),
                        'volume': float(k.get('v', 0)),
                        'ts': datetime.utcfromtimestamp((k.get('T', 0) or 0) / 1000),
                        'is_closed': bool(k.get('x', False)),
                    }
                    r.set('md.last_price', str(bar['close']))
                    r.publish('md.kline', json.dumps({'symbol': settings.symbol, **bar}, default=str))
                    if bar['is_closed']:
                        save_bar(bar)

                elif '@bookTicker' in stream:
                    price = float(data.get('a') or data.get('b') or 0)
                    ts = datetime.utcnow()
                    if price > 0:
                        now_ts = ts.timestamp()
                        r.set('md.last_price', str(price))
                        r.publish('md.ticker', json.dumps({'symbol': settings.symbol, 'price': price, 'ts': ts.isoformat()}))
                        if now_ts - last_tick_persist_ts >= 2:
                            save_tick(price, ts)
                            last_tick_persist_ts = now_ts
        except Exception as exc:
            logger.error('ws_error', error=str(exc))
            await asyncio.sleep(2)
            continue


if __name__ == '__main__':
    asyncio.run(run())
