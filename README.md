# Quantitative Trading System / 量化交易系统

A Binance `ETHUSDT` paper-trading system with realtime sync, replay simulation, drift monitoring, and parameter optimization.
一个基于 Binance `ETHUSDT` 的模拟盘量化系统，支持实时同步、历史回放、偏差监控和参数优化。

## 1. Features / 功能

- Realtime market sync (`kline` + `bookTicker`)
- 实时行情同步（`kline` + `bookTicker`）
- Strategy engine (EMA crossover, closed-candle trigger)
- 策略引擎（EMA 交叉，仅收盘K线触发）
- Risk controls (position cap + cooldown)
- 风控（仓位上限 + 交易冷却）
- Paper execution (no live orders)
- 模拟成交（不发真实订单）
- Historical replay simulation
- 历史回放模拟
- Price drift monitor (local vs exchange REST)
- 价格偏差监控（本地价格 vs 交易所 REST）
- Historical optimization -> auto recommendation -> auto apply (paper)
- 历史优化 -> 自动推荐 -> 自动应用（paper）
- Web UI dashboard with one-click operations
- Web UI 可视化面板（支持一键操作）

## 2. Quick Start / 快速开始

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

Open dashboard / 打开面板：
- `http://localhost:8000/`

Check logs / 查看日志：

```powershell
docker compose logs -f market-data strategy-engine monitor-engine replay-engine api
```

## 3. Web UI Operations / Web UI 操作

- Start replay / 启动回放：`Start Replay`
- Run optimize + apply / 运行优化并自动应用：`Run Optimize+Apply`

## 4. API Endpoints / API 接口

- `GET /health`
- `GET /status`
- `GET /bars?limit=200`
- `POST /ops/replay?limit=300&speed_ms=20`
- `POST /ops/optimize?days=365`

## 5. Services (Docker Compose) / 服务列表

- `postgres`: persistent storage / 持久化数据库
- `redis`: event bus and cache / 事件总线与缓存
- `init-db`: initialize tables / 初始化数据表
- `market-data`: Binance realtime websocket / 实时行情接入
- `strategy-engine`: signal + risk + paper execution / 信号 + 风控 + 模拟成交
- `monitor-engine`: drift monitor and alerts / 偏差监控与告警
- `replay-engine`: replay publisher / 历史回放发布器
- `api`: REST API + Dashboard / REST 接口 + 可视化面板

## 6. Key Environment Variables / 关键环境变量

- `SYMBOL=ETHUSDT`
- `TIMEFRAME=1m`
- `ORDER_USDT=100`
- `MAX_POSITION_USDT=1000`
- `DRIFT_THRESHOLD_BPS=20`
- `DRIFT_CHECK_SECONDS=5`
- `OPTIMIZE_APPLY=true`
- `REPLAY_ENABLED=false`

See full config in `.env.example`.
完整配置请参考 `.env.example`。

## 7. Notes / 说明

- Current version is paper-only (no live trading).
- 当前版本仅支持 paper（不支持实盘下单）。
- Default exchange is Binance.
- 默认交易所为 Binance。

## 8. Export 5Y Dataset (CSV) / 导出近5年CSV训练集

Export Binance historical OHLCV for BTC/ETH (default: 5 years, `1m`):
导出 Binance 的 BTC/ETH 历史K线（默认：近5年、`1m`）：

```powershell
python apps/optimizer/export_binance_csv.py
```

Custom timeframe/output:
自定义周期和输出目录：

```powershell
python apps/optimizer/export_binance_csv.py --symbols BTC/USDT ETH/USDT --timeframe 5m --years 5 --out-dir data/datasets
```

Output files:
输出文件：

- `data/datasets/binance_BTCUSDT_1m_5y.csv`
- `data/datasets/binance_ETHUSDT_1m_5y.csv`
