from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep

import ccxt
import pandas as pd


def fetch_ohlcv_full(
    exchange: ccxt.binance,
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int,
    limit: int = 1000,
) -> list[list[float]]:
    all_rows: list[list[float]] = []
    cursor = since_ms

    while cursor < until_ms:
        rows = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=limit)
        if not rows:
            break

        all_rows.extend(rows)
        last_ts = int(rows[-1][0])
        next_cursor = last_ts + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        sleep(exchange.rateLimit / 1000.0)

    return all_rows


def to_dataframe(rows: list[list[float]], symbol: str, timeframe: str) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    df["datetime_utc"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df["symbol"] = symbol
    df["timeframe"] = timeframe
    return df[["datetime_utc", "ts", "symbol", "timeframe", "open", "high", "low", "close", "volume"]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Binance OHLCV to CSV")
    parser.add_argument("--symbols", nargs="+", default=["BTC/USDT", "ETH/USDT"], help="Symbols, e.g. BTC/USDT ETH/USDT")
    parser.add_argument("--timeframe", default="1m", help="Kline timeframe, e.g. 1m, 5m, 1h")
    parser.add_argument("--years", type=int, default=5, help="How many years to fetch backwards from now")
    parser.add_argument("--out-dir", default="data/datasets", help="Output directory for CSV files")
    args = parser.parse_args()

    exchange = ccxt.binance({"enableRateLimit": True})

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=365 * args.years)
    since_ms = int(since.timestamp() * 1000)
    until_ms = int(now.timestamp() * 1000)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for symbol in args.symbols:
        print(f"[INFO] Fetching {symbol} {args.timeframe} from {since.isoformat()} to {now.isoformat()} ...")
        rows = fetch_ohlcv_full(
            exchange=exchange,
            symbol=symbol,
            timeframe=args.timeframe,
            since_ms=since_ms,
            until_ms=until_ms,
            limit=1000,
        )
        if not rows:
            print(f"[WARN] No rows fetched for {symbol}")
            continue

        df = to_dataframe(rows, symbol=symbol, timeframe=args.timeframe)
        safe_symbol = symbol.replace("/", "")
        output_path = out_dir / f"binance_{safe_symbol}_{args.timeframe}_{args.years}y.csv"
        df.to_csv(output_path, index=False)
        print(f"[INFO] Saved {len(df)} rows -> {output_path}")


if __name__ == "__main__":
    main()
