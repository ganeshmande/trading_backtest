from flask import Flask, jsonify, render_template, request
from datetime import datetime, time
from zoneinfo import ZoneInfo
import json, os, threading

from data_provider import MarketDataProvider

app = Flask(__name__)
provider = MarketDataProvider()
IST = ZoneInfo('Asia/Kolkata')
INTERVALS = ['1m','5m','15m','30m','1h','1d']
WATCHLIST = [
    '360ONE','ABCAPITAL','ABB','ADANIENT','ADANIPORTS','ATHERENERG','APOLLOHOSP','ASIANPAINT','AXISBANK',
    'BAJAJ-AUTO','BAJAJFINSV','BAJFINANCE','BANDHANBNK','BANKBARODA','BANKINDIA','BEL','BHARTIARTL','BIOCON',
    'BSE','CANBK','CDSL','CGPOWER','CIPLA','COALINDIA','DELHIVERY','DLF','DRREDDY','EICHERMOT','ETERNAL',
    'GODFRYPHLP','GRASIM','HCLTECH','HDFCBANK','HDFCLIFE','HEROMOTOCO','HINDALCO','HINDPETRO','HINDUNILVR',
    'HINDZINC','ICICIBANK','INDUSINDBK','INFY','ITC','JIOFIN','JSWENERGY','JSWSTEEL','KOTAKBANK','LTF','LT',
    'LUPIN','M&M','MARUTI','MAXHEALTH','MCX','MOTILALOFS','NESTLEIND','NMDC','NTPC','OBEROIRLTY','ONGC',
    'PERSISTENT','PNB','POWERGRID','RELIANCE','SAIL','SBILIFE','SBIN','SHRIRAMFIN','SIEMENS','SUNPHARMA',
    'SUZLON','TATACONSUM','TATAMOTORS','TATASTEEL','TCS','TECHM','TITAN','TRENT','UNITDSPR','ULTRACEMCO','VEDL'
]
INDICES = ['NIFTY50','SENSEX','BANKNIFTY']
ALL_SYMBOLS = INDICES + WATCHLIST
NIFTY50 = {'ADANIENT','ADANIPORTS','APOLLOHOSP','ASIANPAINT','AXISBANK','BAJAJ-AUTO','BAJFINANCE','BAJAJFINSV','BEL','BHARTIARTL','CIPLA','COALINDIA','DRREDDY','EICHERMOT','ETERNAL','GRASIM','HCLTECH','HDFCBANK','HDFCLIFE','HEROMOTOCO','HINDALCO','HINDUNILVR','ICICIBANK','INDUSINDBK','INFY','ITC','JIOFIN','JSWSTEEL','KOTAKBANK','LT','M&M','MARUTI','NESTLEIND','NTPC','ONGC','POWERGRID','RELIANCE','SBILIFE','SBIN','SHRIRAMFIN','SUNPHARMA','TATACONSUM','TATASTEEL','TCS','TECHM','TITAN','TRENT','ULTRACEMCO','WIPRO'}
NIFTY100_ONLY = {'ABB','BANKBARODA','CANBK','CGPOWER','DLF','HINDZINC','PNB','SIEMENS','TATAMOTORS','UNITDSPR','VEDL'}
STORE = os.path.join(os.path.dirname(__file__), 'data', 'strategy_trades.jsonl')
os.makedirs(os.path.dirname(STORE), exist_ok=True)
lock = threading.Lock()


def now(): return datetime.now(IST)
def membership(s):
    if s in INDICES: return 'INDEX'
    if s in NIFTY50: return 'N50 & N100'
    if s in NIFTY100_ONLY: return 'N100'
    return 'OTHER'

def candle_type(c):
    o,h,l,cl = c['open'],c['high'],c['low'],c['close']
    return 'GREEN' if cl > o else 'RED' if cl < o else 'DOJI'

def body_pct(c):
    rng=max(c['high']-c['low'], 1e-9)
    return abs(c['close']-c['open'])/rng*100

def classify_strength(c):
    p=body_pct(c)
    return 'DOJI' if p <= 10 else 'WEAK' if p <= 35 else 'NORMAL' if p <= 65 else 'STRONG'

def load_trades():
    if not os.path.exists(STORE): return []
    out=[]
    with open(STORE,'r',encoding='utf-8') as f:
        for line in f:
            try: out.append(json.loads(line))
            except: pass
    return out

def save_trade(t):
    with lock:
        with open(STORE,'a',encoding='utf-8') as f: f.write(json.dumps(t,separators=(',',':'))+'\n')

def detect_setups(symbol,candles,rr=2.0,trigger='wick',buffer_pct=0,max_bars=20):
    out=[]
    if len(candles)<4:return out
    for i in range(3,len(candles)):
        a,b,c,d=candles[i-3:i+1]
        types=[candle_type(x) for x in (a,b,c,d)]
        # Bullish breakout: G,G,G,R then breakout above the three green highs.
        if types == ['GREEN','GREEN','GREEN','RED']:
            level=max(a['high'],b['high'],c['high'])
            sl=c['low']; risk=level-sl
            if risk>0:
                out.append(make_setup(symbol,'LONG','G G G R',i,(a,b,c,d),level,sl,rr,max_bars,buffer_pct))
        # Bearish breakout: R,R,R,G then breakdown below the three red lows.
        if types == ['RED','RED','RED','GREEN']:
            level=min(a['low'],b['low'],c['low'])
            sl=c['high']; risk=sl-level
            if risk>0:
                out.append(make_setup(symbol,'SHORT','R R R G',i,(a,b,c,d),level,sl,rr,max_bars,buffer_pct))
    return out

def make_setup(symbol,direction,pattern,idx,cs,level,sl,rr,max_bars,buffer_pct):
    trigger_level=level*(1+buffer_pct/100) if direction=='LONG' else level*(1-buffer_pct/100)
    risk=trigger_level-sl if direction=='LONG' else sl-trigger_level
    target=trigger_level+rr*risk if direction=='LONG' else trigger_level-rr*risk
    return {'setup_id':f"{symbol}|{cs[3]['time']}|{direction}|{pattern}",'symbol':symbol,'membership':membership(symbol),'direction':direction,'pattern':pattern,'setup_candles':[dict(x, type=candle_type(x), strength=classify_strength(x)) for x in cs], 'breakout_level':round(level,2),'trigger_level':round(trigger_level,2),'sl_level':round(sl,2),'target_level':round(target,2),'rr':rr,'setup_index':idx,'created_from':cs[3]['time'],'status':'WAITING','entry':None,'entry_time':None,'exit':None,'exit_time':None,'result':None,'bars_after_setup':0,'max_bars':max_bars}

def trigger_and_update(setups,candles,trigger='wick',max_bars=20):
    changed=[]
    if not candles:return setups,changed
    for s in setups:
        if s['status'] in ('TARGET HIT','SL HIT','EXPIRED','CANCELLED'): continue
        base_time=s['setup_candles'][-1]['time']
        future=[c for c in candles if c['time']>base_time]
        s['bars_after_setup']=len(future)
        for c in future:
            if s['status']=='WAITING':
                hit = c['high']>=s['trigger_level'] if s['direction']=='LONG' else c['low']<=s['trigger_level']
                if hit:
                    s['status']='ACTIVE';s['entry']=s['trigger_level'];s['entry_time']=c['time'];s['entry_candle']=dict(c);changed.append(s)
            if s['status']=='ACTIVE':
                # Conservative same-candle rule: if SL and target are both touched, SL is assumed first.
                sl_hit = c['low']<=s['sl_level'] if s['direction']=='LONG' else c['high']>=s['sl_level']
                tp_hit = c['high']>=s['target_level'] if s['direction']=='LONG' else c['low']<=s['target_level']
                if sl_hit:
                    s['status']='SL HIT';s['exit']=s['sl_level'];s['exit_time']=c['time'];s['result']='LOSS';changed.append(s);break
                if tp_hit:
                    s['status']='TARGET HIT';s['exit']=s['target_level'];s['exit_time']=c['time'];s['result']='TARGET';changed.append(s);break
            if s['status']=='WAITING' and len(future)>max_bars:
                s['status']='EXPIRED';s['result']='EXPIRED';changed.append(s);break
    return setups,changed

def compute(interval, rr=2.0, buffer_pct=0, max_bars=20, mode='wick'):
    data=provider.get_many_candles(ALL_SYMBOLS,interval,100)
    old={x['setup_id']:x for x in load_trades()}
    all_setups=[]
    for symbol in ALL_SYMBOLS:
        candles=data.get(symbol,[])
        setups=detect_setups(symbol,candles,rr=rr,trigger=mode,buffer_pct=buffer_pct,max_bars=max_bars)
        for s in setups:
            if s['setup_id'] in old:
                merged=old[s['setup_id']]
                # keep latest market state from current candles
                s.update({k:v for k,v in merged.items() if k not in ('setup_candles','setup_index')})
            all_setups.append(s)
        # Update using all candles after each setup.
        all_setups_for_symbol=[s for s in all_setups if s['symbol']==symbol]
        all_setups_for_symbol,changed=trigger_and_update(all_setups_for_symbol,candles,mode,max_bars)
        byid={s['setup_id']:s for s in all_setups_for_symbol}
        for j,s in enumerate(all_setups):
            if s['symbol']==symbol and s['setup_id'] in byid: all_setups[j]=byid[s['setup_id']]
    # dedupe and persist only new/changed snapshots by setup id
    current=load_trades(); known={x['setup_id']:x for x in current}
    for s in all_setups: known[s['setup_id']]=s
    # Rewrite compact state store, separate page only.
    with lock:
        with open(STORE,'w',encoding='utf-8') as f:
            for s in known.values(): f.write(json.dumps(s,separators=(',',':'))+'\n')
    return all_setups

@app.get('/')
def page(): return render_template('strategy.html')
@app.get('/api/trades')
def trades():
    interval=request.args.get('interval','5m')
    if interval not in INTERVALS:return jsonify({'error':'Invalid interval'}),400
    try: rr=float(request.args.get('rr','2')); buffer=float(request.args.get('buffer','0')); max_bars=int(request.args.get('max_bars','20'))
    except: rr,buffer,max_bars=2.0,0,20
    setups=compute(interval,max(0.5,min(rr,10)),max(0,min(buffer,2)),max(1,min(max_bars,100)),request.args.get('mode','wick'))
    # newest first
    setups.sort(key=lambda x:x.get('entry_time') or x['created_from'],reverse=True)
    counts={k:sum(1 for s in setups if s['status']==k) for k in ['WAITING','ACTIVE','TARGET HIT','SL HIT','EXPIRED']}
    return jsonify({'success':True,'server_time':now().isoformat(),'interval':interval,'settings':{'rr':rr,'buffer':buffer,'max_bars':max_bars},'counts':counts,'trades':setups})

if __name__=='__main__':
    print('STRATEGY TEST PAGE — separate app')
    print('Open: http://127.0.0.1:5001')
    app.run(host='127.0.0.1',port=5001,debug=False,threaded=True)
