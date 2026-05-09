import json
import threading
import time
from datetime import datetime
from sqlalchemy import select, desc, func
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
import redis
import ccxt
from libs.core.config import settings
from libs.core.db import SessionLocal
from libs.core.models import Trade, Position, MarketBar, PriceTick, Alert, StrategyConfig
from apps.optimizer.service import run_optimization

app = FastAPI(title='Quant Trading API')
exchange = ccxt.binance({'enableRateLimit': True})
SUPPORTED_TIMEFRAMES = {'1m', '5m', '15m', '1h', '1w'}


def run_replay_once(limit: int, speed_ms: int):
    r = redis.from_url(settings.redis_url, decode_responses=True)
    ex = ccxt.binance({'enableRateLimit': True})
    symbol = f"{settings.symbol[:-4]}/USDT"
    rows = ex.fetch_ohlcv(symbol, timeframe=settings.timeframe, limit=limit)
    for row in rows:
        ts_ms, o, h, l, c, v = row
        bar = {
            'symbol': settings.symbol,
            'open': float(o),
            'high': float(h),
            'low': float(l),
            'close': float(c),
            'volume': float(v),
            'ts': datetime.utcfromtimestamp(ts_ms / 1000).isoformat(),
            'is_closed': True,
            'is_replay': True,
        }
        r.publish('md.kline', json.dumps(bar))
        r.set('md.last_price', str(c))
        time.sleep(max(speed_ms, 1) / 1000)


@app.get('/health')
def health():
    return {'status': 'ok', 'symbol': settings.symbol, 'paper_mode': settings.paper_mode}


@app.post('/ops/replay')
def start_replay(limit: int = 300, speed_ms: int = 20):
    t = threading.Thread(target=run_replay_once, args=(limit, speed_ms), daemon=True)
    t.start()
    return {'status': 'started', 'limit': limit, 'speed_ms': speed_ms}


@app.post('/ops/optimize')
def optimize(days: int = 365):
    best = run_optimization(days=days)
    return {'status': 'ok', 'best': best, 'applied': settings.optimize_apply}


@app.post('/ops/auto-trade')
def set_auto_trade(enabled: bool = True):
    r = redis.from_url(settings.redis_url, decode_responses=True)
    r.set('strategy.auto_trade_enabled', 'true' if enabled else 'false')
    return {'status': 'ok', 'auto_trade_enabled': enabled}


@app.get('/status')
def status():
    r = redis.from_url(settings.redis_url, decode_responses=True)
    with SessionLocal() as db:
        trades = db.scalars(select(Trade).order_by(desc(Trade.created_at)).limit(30)).all()
        positions = db.scalars(select(Position)).all()
        bars = db.scalar(select(func.count(MarketBar.id))) or 0
        latest_tick = db.scalar(select(PriceTick).order_by(desc(PriceTick.ts)).limit(1))
        realized_pnl = db.scalar(select(func.coalesce(func.sum(Trade.pnl), 0.0))) or 0.0
        alerts = db.scalars(select(Alert).order_by(desc(Alert.created_at)).limit(20)).all()
        active_cfg = db.scalar(select(StrategyConfig).where(StrategyConfig.symbol == settings.symbol, StrategyConfig.active.is_(True)).order_by(desc(StrategyConfig.created_at)).limit(1))

    active_params = r.get('strategy.active_params')
    redis_last_price = r.get('md.last_price')
    auto_trade_enabled_raw = r.get('strategy.auto_trade_enabled')
    return {
        'symbol': settings.symbol,
        'bars': bars,
        'latest_price': float(redis_last_price) if redis_last_price else (latest_tick.price if latest_tick else None),
        'auto_trade_enabled': (auto_trade_enabled_raw or 'true').lower() == 'true',
        'realized_pnl': realized_pnl,
        'drift_bps': float(r.get('monitor.price_drift_bps') or 0.0),
        'active_params': json.loads(active_params) if active_params else None,
        'active_cfg_db': {
            'fast_ma': active_cfg.fast_ma,
            'slow_ma': active_cfg.slow_ma,
            'min_bars': active_cfg.min_bars,
            'score': active_cfg.score,
        } if active_cfg else None,
        'positions': [
            {'symbol': p.symbol, 'qty': p.qty, 'avg_price': p.avg_price} for p in positions
        ],
        'recent_alerts': [
            {'level': a.level, 'source': a.source, 'message': a.message, 'created_at': a.created_at.isoformat()} for a in alerts
        ],
        'recent_trades': [
            {
                'id': t.id,
                'side': t.side,
                'price': t.price,
                'qty': t.qty,
                'notional': t.notional,
                'pnl': t.pnl,
                'mode': t.mode,
                'created_at': t.created_at.isoformat(),
            }
            for t in trades
        ],
    }


@app.get('/official-price')
def official_price():
    market = f"{settings.symbol[:-4]}/USDT"
    ticker = exchange.fetch_ticker(market)
    return {'symbol': settings.symbol, 'official_price': float(ticker['last'])}


@app.get('/official-bars')
def official_bars(timeframe: str = '1m', limit: int = 200):
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f'unsupported timeframe: {timeframe}')
    safe_limit = max(20, min(limit, 500))
    market = f"{settings.symbol[:-4]}/USDT"
    rows = exchange.fetch_ohlcv(market, timeframe=timeframe, limit=safe_limit)
    return [
        {
            'ts': datetime.utcfromtimestamp(ts_ms / 1000).isoformat(),
            'open': float(o),
            'high': float(h),
            'low': float(l),
            'close': float(c),
            'volume': float(v),
        }
        for ts_ms, o, h, l, c, v in rows
    ]


@app.get('/bars')
def bars(limit: int = 200):
    with SessionLocal() as db:
        data = db.scalars(select(MarketBar).order_by(desc(MarketBar.ts)).limit(limit)).all()
    rows = list(reversed(data))
    return [
        {
            'ts': x.ts.isoformat(),
            'open': x.open,
            'high': x.high,
            'low': x.low,
            'close': x.close,
            'volume': x.volume,
        }
        for x in rows
    ]


@app.get('/', response_class=HTMLResponse)
def dashboard():
    html = """
<!doctype html><html><head><meta charset='utf-8'><title>Quant Dashboard</title>
<script src='https://cdn.jsdelivr.net/npm/chart.js'></script>
<style>
body { font-family: Segoe UI, sans-serif; background:#0b1220; color:#e8eefc; margin:20px; }
.grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; }
.card { background:#121a2b; border:1px solid #27324a; border-radius:12px; padding:12px; }
button { padding:8px 12px; margin-right:8px; background:#234a8a; color:#fff; border:none; border-radius:8px; cursor:pointer; }
input { width:80px; }
table { width:100%; border-collapse:collapse; } th, td { border-bottom:1px solid #2a3348; padding:6px; font-size:12px; text-align:left; }
.kpi { font-size:20px; margin:4px 0; }
</style></head><body>
<h2 id='title'>Quant Dashboard (ETHUSDT / Binance / Paper)</h2>
<div class='card'>
  <button id='langToggle' onclick='toggleLang()'>中文</button>
  <span id='labelReplayLimit'>Replay limit</span> <input id='replayLimit' value='300'/> <span id='labelReplaySpeed'>speed_ms</span> <input id='replaySpeed' value='20'/>
  <button id='btnReplay' onclick='startReplay()'>Start Replay</button>
  <span id='labelOptimizeDays'>Optimize days</span> <input id='optDays' value='365'/>
  <button id='btnOptimize' onclick='startOptimize()'>Run Optimize+Apply</button>
  <button id='btnAutoTrade' onclick='toggleAutoTrade()'>Auto Trade: ON</button>
  <span id='labelTimeframe'>Kline</span>
  <select id='timeframe' onchange='refresh()'>
    <option value='1m'>1m</option>
    <option value='5m'>5m</option>
    <option value='15m'>15m</option>
    <option value='1h'>1h</option>
    <option value='1w'>1w</option>
  </select>
  <span id='opMsg'></span>
</div>
<div class='grid'>
<div class='card'><div id='labelLatestPrice'>Latest Price</div><div id='latestPrice' class='kpi'>-</div><div id='labelOfficialPrice'>Official Price</div><div id='officialPrice' class='kpi'>-</div><div id='labelRealizedPnl'>Realized PnL</div><div id='realizedPnl' class='kpi'>-</div></div>
<div class='card'><div id='labelPosition'>Position</div><div id='positionText' class='kpi'>-</div><div id='labelDrift'>Drift (bps)</div><div id='driftBps' class='kpi'>-</div></div>
<div class='card'><div id='labelActiveParams'>Active Params</div><div id='activeParams' class='kpi'>-</div></div>
</div>
<div class='card' style='margin-top:16px;'><canvas id='priceChart' height='80'></canvas></div>
<div class='card' style='margin-top:16px;'><h3 id='titleTrades'>Recent Trades</h3><table><thead><tr><th id='thTradeTime'>Time</th><th id='thTradeSide'>Side</th><th id='thTradePrice'>Price</th><th id='thTradeQty'>Qty</th><th id='thTradePnl'>PnL</th><th id='thTradeMode'>Mode</th></tr></thead><tbody id='tradeRows'></tbody></table></div>
<div class='card' style='margin-top:16px;'><h3 id='titleAlerts'>Recent Alerts</h3><table><thead><tr><th id='thAlertTime'>Time</th><th id='thAlertLevel'>Level</th><th id='thAlertSource'>Source</th><th id='thAlertMessage'>Message</th></tr></thead><tbody id='alertRows'></tbody></table></div>
<script>
let chart;
let currentLang = localStorage.getItem('lang') || 'zh';
const i18n = {
  zh: {
    title: '量化看板 (ETHUSDT / Binance / 模拟盘)',
    toggle: 'English',
    replayLimit: '回放条数',
    replaySpeed: '速度_ms',
    btnReplay: '启动回放',
    optimizeDays: '优化天数',
    btnOptimize: '运行优化并应用',
    autoTradeOn: '自动交易：开启',
    autoTradeOff: '自动交易：关闭',
    timeframe: 'K线周期',
    latestPrice: '最新价格',
    officialPrice: '官网实时价',
    realizedPnl: '已实现盈亏',
    position: '持仓',
    drift: '偏差 (bps)',
    activeParams: '当前参数',
    trades: '最近成交',
    alerts: '最近告警',
    time: '时间',
    side: '方向',
    price: '价格',
    qty: '数量',
    pnl: '盈亏',
    mode: '模式',
    level: '等级',
    source: '来源',
    message: '消息',
    noPosition: '无持仓',
    defaultParam: '默认',
    close: '收盘价'
  },
  en: {
    title: 'Quant Dashboard (ETHUSDT / Binance / Paper)',
    toggle: '中文',
    replayLimit: 'Replay limit',
    replaySpeed: 'speed_ms',
    btnReplay: 'Start Replay',
    optimizeDays: 'Optimize days',
    btnOptimize: 'Run Optimize+Apply',
    autoTradeOn: 'Auto Trade: ON',
    autoTradeOff: 'Auto Trade: OFF',
    timeframe: 'Kline',
    latestPrice: 'Latest Price',
    officialPrice: 'Official Price',
    realizedPnl: 'Realized PnL',
    position: 'Position',
    drift: 'Drift (bps)',
    activeParams: 'Active Params',
    trades: 'Recent Trades',
    alerts: 'Recent Alerts',
    time: 'Time',
    side: 'Side',
    price: 'Price',
    qty: 'Qty',
    pnl: 'PnL',
    mode: 'Mode',
    level: 'Level',
    source: 'Source',
    message: 'Message',
    noPosition: 'no position',
    defaultParam: 'default',
    close: 'Close'
  }
};
function t(k){return i18n[currentLang][k] || k;}
function applyI18n(){
  document.getElementById('title').innerText=t('title');
  document.getElementById('langToggle').innerText=t('toggle');
  document.getElementById('labelReplayLimit').innerText=t('replayLimit');
  document.getElementById('labelReplaySpeed').innerText=t('replaySpeed');
  document.getElementById('btnReplay').innerText=t('btnReplay');
  document.getElementById('labelOptimizeDays').innerText=t('optimizeDays');
  document.getElementById('btnOptimize').innerText=t('btnOptimize');
  document.getElementById('labelTimeframe').innerText=t('timeframe');
  document.getElementById('labelLatestPrice').innerText=t('latestPrice');
  document.getElementById('labelOfficialPrice').innerText=t('officialPrice');
  document.getElementById('labelRealizedPnl').innerText=t('realizedPnl');
  document.getElementById('labelPosition').innerText=t('position');
  document.getElementById('labelDrift').innerText=t('drift');
  document.getElementById('labelActiveParams').innerText=t('activeParams');
  document.getElementById('titleTrades').innerText=t('trades');
  document.getElementById('titleAlerts').innerText=t('alerts');
  document.getElementById('thTradeTime').innerText=t('time');
  document.getElementById('thTradeSide').innerText=t('side');
  document.getElementById('thTradePrice').innerText=t('price');
  document.getElementById('thTradeQty').innerText=t('qty');
  document.getElementById('thTradePnl').innerText=t('pnl');
  document.getElementById('thTradeMode').innerText=t('mode');
  document.getElementById('thAlertTime').innerText=t('time');
  document.getElementById('thAlertLevel').innerText=t('level');
  document.getElementById('thAlertSource').innerText=t('source');
  document.getElementById('thAlertMessage').innerText=t('message');
}
function toggleLang(){
  currentLang = currentLang === 'zh' ? 'en' : 'zh';
  localStorage.setItem('lang', currentLang);
  applyI18n();
  refresh();
}
async function startReplay(){const l=document.getElementById('replayLimit').value; const s=document.getElementById('replaySpeed').value; const r=await fetch(`/ops/replay?limit=${l}&speed_ms=${s}`,{method:'POST'}); document.getElementById('opMsg').innerText=JSON.stringify(await r.json());}
async function startOptimize(){const d=document.getElementById('optDays').value; const r=await fetch(`/ops/optimize?days=${d}`,{method:'POST'}); document.getElementById('opMsg').innerText=JSON.stringify(await r.json());}
async function toggleAutoTrade(){
 const current=document.getElementById('btnAutoTrade').dataset.enabled === 'true';
 const next=!current;
 const r=await fetch(`/ops/auto-trade?enabled=${next}`,{method:'POST'});
 const j=await r.json();
 document.getElementById('btnAutoTrade').dataset.enabled=String(j.auto_trade_enabled);
 document.getElementById('btnAutoTrade').innerText=j.auto_trade_enabled?t('autoTradeOn'):t('autoTradeOff');
}
async function refresh(){
 const tf=document.getElementById('timeframe').value;
 const [sres,bres,ores]=await Promise.all([fetch('/status'),fetch(`/official-bars?timeframe=${tf}&limit=120`),fetch('/official-price')]);
 const s=await sres.json(); const bars=await bres.json();
 const o=await ores.json();
 document.getElementById('btnAutoTrade').dataset.enabled=String(Boolean(s.auto_trade_enabled));
 document.getElementById('btnAutoTrade').innerText=Boolean(s.auto_trade_enabled)?t('autoTradeOn'):t('autoTradeOff');
 const officialPrice=(o.official_price!==undefined && o.official_price!==null)?Number(o.official_price):null;
 document.getElementById('latestPrice').innerText=officialPrice?officialPrice.toFixed(4):'-';
 document.getElementById('officialPrice').innerText=o.official_price?Number(o.official_price).toFixed(4):'-';
 document.getElementById('realizedPnl').innerText=Number(s.realized_pnl||0).toFixed(4);
 const p=(s.positions||[])[0]; document.getElementById('positionText').innerText=p?`qty=${Number(p.qty).toFixed(6)} avg=${Number(p.avg_price).toFixed(4)}`:t('noPosition');
 document.getElementById('driftBps').innerText=Number(s.drift_bps||0).toFixed(2);
 const ap=s.active_params || s.active_cfg_db; document.getElementById('activeParams').innerText=ap?`fast=${ap.fast_ma} slow=${ap.slow_ma} min=${ap.min_bars}`:t('defaultParam');
 const tb=document.getElementById('tradeRows'); tb.innerHTML=''; for(const t of (s.recent_trades||[])){const tr=document.createElement('tr'); tr.innerHTML=`<td>${t.created_at}</td><td>${t.side}</td><td>${Number(t.price).toFixed(4)}</td><td>${Number(t.qty).toFixed(6)}</td><td>${Number(t.pnl).toFixed(4)}</td><td>${t.mode}</td>`; tb.appendChild(tr);} 
 const ab=document.getElementById('alertRows'); ab.innerHTML=''; for(const a of (s.recent_alerts||[])){const tr=document.createElement('tr'); tr.innerHTML=`<td>${a.created_at}</td><td>${a.level}</td><td>${a.source}</td><td>${a.message}</td>`; ab.appendChild(tr);} 
 const labels=bars.map(x=>x.ts.slice(0,16).replace('T',' ')); const closes=bars.map(x=>x.close);
 if(!chart){chart=new Chart(document.getElementById('priceChart').getContext('2d'),{type:'line',data:{labels:labels,datasets:[{label:t('close'),data:closes,borderColor:'#4ea1ff'}]},options:{animation:false,responsive:true,plugins:{legend:{labels:{color:'#e8eefc'}}},scales:{x:{ticks:{color:'#b4c0d8'}},y:{ticks:{color:'#b4c0d8'}}}}});}
 else{chart.data.labels=labels; chart.data.datasets[0].data=closes; chart.data.datasets[0].label=t('close'); chart.update();}
}
applyI18n();
refresh(); setInterval(refresh,2000);
</script></body></html>
"""
    return HTMLResponse(content=html)
