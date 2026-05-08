from datetime import datetime
from sqlalchemy import select
from libs.core.db import SessionLocal
from libs.core.models import Position, Trade
from libs.core.config import settings


class PaperExecutor:
    def execute(self, symbol: str, side: str, price: float, mode: str = 'paper') -> dict:
        qty = round(settings.order_usdt / price, 6)
        with SessionLocal() as db:
            pos = db.scalar(select(Position).where(Position.symbol == symbol))
            if not pos:
                pos = Position(symbol=symbol, qty=0.0, avg_price=0.0)
                db.add(pos)
                db.flush()

            pnl = 0.0
            if side == 'BUY':
                new_qty = pos.qty + qty
                if new_qty > 0:
                    pos.avg_price = ((pos.qty * pos.avg_price) + (qty * price)) / new_qty if pos.qty > 0 else price
                pos.qty = new_qty
            elif side == 'SELL':
                sell_qty = min(qty, max(pos.qty, 0.0))
                if sell_qty <= 0:
                    db.commit()
                    return {'status': 'skipped', 'reason': 'no_position'}
                pnl = (price - pos.avg_price) * sell_qty
                pos.qty -= sell_qty
                if pos.qty == 0:
                    pos.avg_price = 0.0
                qty = sell_qty

            trade = Trade(
                symbol=symbol,
                side=side,
                price=price,
                qty=qty,
                notional=qty * price,
                pnl=pnl,
                mode=mode,
                created_at=datetime.utcnow(),
            )
            db.add(trade)
            db.commit()
            return {'status': 'filled', 'side': side, 'qty': qty, 'price': price, 'pnl': pnl, 'mode': mode}
