import json
from datetime import datetime, timedelta
import ccxt
import redis
from libs.core.config import settings
from libs.core.db import SessionLocal
from libs.core.models import StrategyConfig, Alert
from libs.strategy.ema_cross import EmaCrossStrategy


def backtest(prices, fast_ma: int, slow_ma: int, min_bars: int):
    s = EmaCrossStrategy(fast_ma=fast_ma, slow_ma=slow_ma, min_bars=min_bars)
    position = 0.0
    avg_price = 0.0
    cash_pnl = 0.0
    trades = 0
    for price in prices:
        sig = s.on_price(price)
        qty = settings.order_usdt / price
        if sig == 'BUY':
            new_qty = position + qty
            avg_price = ((position * avg_price) + (qty * price)) / new_qty if position > 0 else price
            position = new_qty
            trades += 1
        elif sig == 'SELL' and position > 0:
            sell_qty = min(qty, position)
            cash_pnl += (price - avg_price) * sell_qty
            position -= sell_qty
            if position == 0:
                avg_price = 0.0
            trades += 1
    return {'pnl': cash_pnl, 'trades': trades, 'score': cash_pnl - trades * 0.02}


def run_optimization(days: int):
    ex = ccxt.binance({'enableRateLimit': True})
    symbol = f"{settings.symbol[:-4]}/USDT"
    since = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)
    rows = ex.fetch_ohlcv(symbol, timeframe=settings.timeframe, since=since, limit=1500)
    prices = [float(r[4]) for r in rows]

    best = None
    for fast in [5, 8, 10, 12, 15]:
        for slow in [20, 26, 30, 35, 40, 50]:
            if fast >= slow:
                continue
            for min_bars in [30, 40, 50, 60]:
                result = backtest(prices, fast, slow, min_bars)
                candidate = {
                    'fast_ma': fast,
                    'slow_ma': slow,
                    'min_bars': min_bars,
                    **result,
                }
                if best is None or candidate['score'] > best['score']:
                    best = candidate

    if best is None:
        raise RuntimeError('no optimization result')

    r = redis.from_url(settings.redis_url, decode_responses=True)
    with SessionLocal() as db:
        db.query(StrategyConfig).filter(StrategyConfig.symbol == settings.symbol).update({'active': False})
        row = StrategyConfig(
            symbol=settings.symbol,
            fast_ma=best['fast_ma'],
            slow_ma=best['slow_ma'],
            min_bars=best['min_bars'],
            score=best['score'],
            active=True,
        )
        db.add(row)
        db.add(Alert(level='INFO', source='optimizer', message=f"best params: {best}", created_at=datetime.utcnow()))
        db.commit()

    payload = {'fast_ma': best['fast_ma'], 'slow_ma': best['slow_ma'], 'min_bars': best['min_bars'], 'updated_at': datetime.utcnow().isoformat()}
    if settings.optimize_apply:
        r.set('strategy.active_params', json.dumps(payload))

    return best
