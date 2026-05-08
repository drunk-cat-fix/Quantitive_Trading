import json
import time
from sqlalchemy import select
import redis
from libs.core.config import settings
from libs.core.db import SessionLocal
from libs.core.models import Position
from libs.core.risk import RiskManager
from libs.core.logger import get_logger
from libs.strategy.ema_cross import EmaCrossStrategy
from libs.exchange.paper_executor import PaperExecutor

logger = get_logger('strategy_engine')


def get_position_qty(symbol: str) -> float:
    with SessionLocal() as db:
        pos = db.scalar(select(Position).where(Position.symbol == symbol))
        return pos.qty if pos else 0.0


def load_active_params(r):
    raw = r.get('strategy.active_params')
    if raw:
        p = json.loads(raw)
        return int(p['fast_ma']), int(p['slow_ma']), int(p['min_bars'])
    return settings.fast_ma, settings.slow_ma, settings.min_bars


def run() -> None:
    r = redis.from_url(settings.redis_url, decode_responses=True)
    p = r.pubsub()
    p.subscribe('md.kline')

    fast_ma, slow_ma, min_bars = load_active_params(r)
    strategy = EmaCrossStrategy(fast_ma=fast_ma, slow_ma=slow_ma, min_bars=min_bars)
    risk = RiskManager()
    executor = PaperExecutor()
    last_trade_ts = 0.0

    logger.info('strategy_started', symbol=settings.symbol, paper_mode=settings.paper_mode, fast_ma=fast_ma, slow_ma=slow_ma, min_bars=min_bars)

    for message in p.listen():
        if message['type'] != 'message':
            continue

        new_fast, new_slow, new_min = load_active_params(r)
        if (new_fast, new_slow, new_min) != (fast_ma, slow_ma, min_bars):
            fast_ma, slow_ma, min_bars = new_fast, new_slow, new_min
            strategy = EmaCrossStrategy(fast_ma=fast_ma, slow_ma=slow_ma, min_bars=min_bars)
            logger.info('strategy_params_reloaded', fast_ma=fast_ma, slow_ma=slow_ma, min_bars=min_bars)

        payload = json.loads(message['data'])
        if not bool(payload.get('is_closed', False)):
            continue

        close = float(payload['close'])
        signal = strategy.on_price(close)
        now = time.time()

        if signal == 'HOLD':
            continue
        if now - last_trade_ts < settings.cooldown_seconds:
            continue

        position_qty = get_position_qty(settings.symbol)
        if signal == 'BUY' and not risk.can_open(position_qty, close):
            logger.info('risk_blocked', signal=signal, price=close, position_qty=position_qty)
            continue

        trade_mode = 'replay' if bool(payload.get('is_replay', False)) else 'paper'
        result = executor.execute(settings.symbol, signal, close, mode=trade_mode)
        if result.get('status') == 'filled':
            last_trade_ts = now
            logger.info('trade_filled', **result)
        else:
            logger.info('trade_skipped', **result)


if __name__ == '__main__':
    run()
