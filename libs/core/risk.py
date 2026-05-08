from libs.core.config import settings


class RiskManager:
    def __init__(self):
        self.max_position_usdt = settings.max_position_usdt
        self.order_usdt = settings.order_usdt

    def can_open(self, current_position_qty: float, price: float) -> bool:
        current_notional = abs(current_position_qty) * price
        return current_notional + self.order_usdt <= self.max_position_usdt
