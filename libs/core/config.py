from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'quant-trading'
    env: str = 'dev'

    exchange: str = 'binance'
    symbol: str = 'ETHUSDT'
    timeframe: str = '1m'

    paper_mode: bool = True
    dry_run: bool = True

    redis_url: str = 'redis://redis:6379/0'
    database_url: str = 'postgresql+psycopg2://postgres:postgres@postgres:5432/quant'

    fast_ma: int = 8
    slow_ma: int = 21
    min_bars: int = 30

    max_position_usdt: float = 1000.0
    order_usdt: float = 100.0
    cooldown_seconds: int = 30

    replay_enabled: bool = False
    replay_limit: int = 500
    replay_speed_ms: int = 50

    drift_threshold_bps: float = 20.0
    drift_check_seconds: int = 5

    optimize_enabled: bool = False
    optimize_days: int = 365
    optimize_apply: bool = True

    api_host: str = '0.0.0.0'
    api_port: int = 8000


settings = Settings()
