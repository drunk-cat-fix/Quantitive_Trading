import time
from datetime import datetime
import ccxt
import redis
from libs.core.config import settings
from libs.core.db import SessionLocal
from libs.core.models import Alert
from libs.core.logger import get_logger

logger = get_logger('monitor_engine')


def save_alert(level: str, source: str, message: str) -> None:
    with SessionLocal() as db:
        db.add(Alert(level=level, source=source, message=message, created_at=datetime.utcnow()))
        db.commit()


def run() -> None:
    r = redis.from_url(settings.redis_url, decode_responses=True)
    ex = ccxt.binance({'enableRateLimit': True})
    market = f"{settings.symbol[:-4]}/USDT"

    while True:
        try:
            local_raw = r.get('md.last_price')
            if not local_raw:
                time.sleep(settings.drift_check_seconds)
                continue

            local_price = float(local_raw)
            ticker = ex.fetch_ticker(market)
            remote_price = float(ticker['last'])
            diff_bps = abs(local_price - remote_price) / remote_price * 10000 if remote_price > 0 else 0.0

            r.set('monitor.price_drift_bps', f'{diff_bps:.4f}')
            if diff_bps >= settings.drift_threshold_bps:
                msg = f'drift alert: local={local_price:.4f}, remote={remote_price:.4f}, diff_bps={diff_bps:.2f}'
                save_alert('WARN', 'price_drift', msg)
                logger.warning('price_drift_alert', local=local_price, remote=remote_price, diff_bps=diff_bps)

        except Exception as exc:
            save_alert('ERROR', 'price_drift', f'check failed: {exc}')
            logger.error('monitor_error', error=str(exc))

        time.sleep(settings.drift_check_seconds)


if __name__ == '__main__':
    run()
