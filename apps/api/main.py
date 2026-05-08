import json
import threading
import time
from datetime import datetime
from sqlalchemy import select, desc, func
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import redis
import ccxt
from libs.core.config import settings
from libs.core.db import SessionLocal
from libs.core.models import Trade, Position, MarketBar, PriceTick, Alert, StrategyConfig
from apps.optimizer.service import run_optimization

app = FastAPI(title='Quant Trading API')


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
    return {
        'symbol': settings.symbol,
        'bars': bars,
        'latest_price': latest_tick.price if latest_tick else None,
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
<h2>Quant Dashboard (ETHUSDT / Binance / Paper)</h2>
<div class='card'>
  Replay limit <input id='replayLimit' value='300'/> speed_ms <input id='replaySpeed' value='20'/>
  <button onclick='startReplay()'>Start Replay</button>
  Optimize days <input id='optDays' value='365'/>
  <button onclick='startOptimize()'>Run Optimize+Apply</button>
  <span id='opMsg'></span>
</div>
<div class='grid'>
<div class='card'><div>Latest Price</div><div id='latestPrice' class='kpi'>-</div><div>Realized PnL</div><div id='realizedPnl' class='kpi'>-</div></div>
<div class='card'><div>Position</div><div id='positionText' class='kpi'>-</div><div>Drift (bps)</div><div id='driftBps' class='kpi'>-</div></div>
<div class='card'><div>Active Params</div><div id='activeParams' class='kpi'>-</div></div>
</div>
<div class='card' style='margin-top:16px;'><canvas id='priceChart' height='80'></canvas></div>
<div class='card' style='margin-top:16px;'><h3>Recent Trades</h3><table><thead><tr><th>Time</th><th>Side</th><th>Price</th><th>Qty</th><th>PnL</th><th>Mode</th></tr></thead><tbody id='tradeRows'></tbody></table></div>
<div class='card' style='margin-top:16px;'><h3>Recent Alerts</h3><table><thead><tr><th>Time</th><th>Level</th><th>Source</th><th>Message</th></tr></thead><tbody id='alertRows'></tbody></table></div>
<script>
let chart;
async function startReplay(){const l=document.getElementById('replayLimit').value; const s=document.getElementById('replaySpeed').value; const r=await fetch(`/ops/replay?limit=${l}&speed_ms=${s}`,{method:'POST'}); document.getElementById('opMsg').innerText=JSON.stringify(await r.json());}
async function startOptimize(){const d=document.getElementById('optDays').value; const r=await fetch(`/ops/optimize?days=${d}`,{method:'POST'}); document.getElementById('opMsg').innerText=JSON.stringify(await r.json());}
async function refresh(){
 const [sres,bres]=await Promise.all([fetch('/status'),fetch('/bars?limit=120')]);
 const s=await sres.json(); const bars=await bres.json();
 document.getElementById('latestPrice').innerText=s.latest_price?Number(s.latest_price).toFixed(4):'-';
 document.getElementById('realizedPnl').innerText=Number(s.realized_pnl||0).toFixed(4);
 const p=(s.positions||[])[0]; document.getElementById('positionText').innerText=p?`qty=${Number(p.qty).toFixed(6)} avg=${Number(p.avg_price).toFixed(4)}`:'no position';
 document.getElementById('driftBps').innerText=Number(s.drift_bps||0).toFixed(2);
 const ap=s.active_params || s.active_cfg_db; document.getElementById('activeParams').innerText=ap?`fast=${ap.fast_ma} slow=${ap.slow_ma} min=${ap.min_bars}`:'default';
 const tb=document.getElementById('tradeRows'); tb.innerHTML=''; for(const t of (s.recent_trades||[])){const tr=document.createElement('tr'); tr.innerHTML=`<td>${t.created_at}</td><td>${t.side}</td><td>${Number(t.price).toFixed(4)}</td><td>${Number(t.qty).toFixed(6)}</td><td>${Number(t.pnl).toFixed(4)}</td><td>${t.mode}</td>`; tb.appendChild(tr);} 
 const ab=document.getElementById('alertRows'); ab.innerHTML=''; for(const a of (s.recent_alerts||[])){const tr=document.createElement('tr'); tr.innerHTML=`<td>${a.created_at}</td><td>${a.level}</td><td>${a.source}</td><td>${a.message}</td>`; ab.appendChild(tr);} 
 const labels=bars.map(x=>x.ts.slice(11,16)); const closes=bars.map(x=>x.close);
 if(!chart){chart=new Chart(document.getElementById('priceChart').getContext('2d'),{type:'line',data:{labels:labels,datasets:[{label:'Close',data:closes,borderColor:'#4ea1ff'}]},options:{animation:false,responsive:true,plugins:{legend:{labels:{color:'#e8eefc'}}},scales:{x:{ticks:{color:'#b4c0d8'}},y:{ticks:{color:'#b4c0d8'}}}}});}
 else{chart.data.labels=labels; chart.data.datasets[0].data=closes; chart.update();}
}
refresh(); setInterval(refresh,2000);
</script></body></html>
"""
    return HTMLResponse(content=html)
