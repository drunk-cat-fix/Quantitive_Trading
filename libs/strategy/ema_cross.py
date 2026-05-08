from collections import deque
from statistics import fmean


class EmaCrossStrategy:
    def __init__(self, fast_ma: int, slow_ma: int, min_bars: int):
        self.fast_ma = fast_ma
        self.slow_ma = slow_ma
        self.min_bars = max(min_bars, slow_ma)
        self.prices = deque(maxlen=max(self.min_bars, self.slow_ma + 5))

    def on_price(self, close_price: float) -> str:
        self.prices.append(close_price)
        if len(self.prices) < self.min_bars:
            return 'HOLD'

        values = list(self.prices)
        fast = fmean(values[-self.fast_ma:])
        slow = fmean(values[-self.slow_ma:])

        if fast > slow:
            return 'BUY'
        if fast < slow:
            return 'SELL'
        return 'HOLD'
