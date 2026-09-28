import csv, os, sqlite3, threading
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

BASE_DIR=os.path.dirname(os.path.abspath(__file__))
DATA_DIR=os.path.join(BASE_DIR,'data')
HIST_DIR=os.path.join(DATA_DIR,'market_data')
DB_PATH=os.path.join(HIST_DIR,'market_data.db')
IST=ZoneInfo('Asia/Kolkata')
LOCK=threading.Lock()
os.makedirs(HIST_DIR,exist_ok=True)

SCHEMA='''CREATE TABLE IF NOT EXISTS candles (
 symbol TEXT NOT NULL, interval TEXT NOT NULL, ts TEXT NOT NULL, date TEXT NOT NULL,
 open REAL, high REAL, low REAL, close REAL, volume REAL, source TEXT,
 PRIMARY KEY(symbol, interval, ts)
); CREATE INDEX IF NOT EXISTS idx_candles_date ON candles(date, interval, symbol);'''

def connect():
    c=sqlite3.connect(DB_PATH, timeout=30)
    c.executescript(SCHEMA); c.commit(); return c

def save_rows(rows):
    if not rows:return 0
    with LOCK:
        c=connect()
        c.executemany('''INSERT OR REPLACE INTO candles(symbol,interval,ts,date,open,high,low,close,volume,source) VALUES(?,?,?,?,?,?,?,?,?,?)''',rows)
        c.commit(); n=c.total_changes; c.close()
    _write_daily_csv(rows)
    return n

def _write_daily_csv(rows):
    by={}
    for r in rows: by.setdefault((r[3],r[1]),[]).append(r)
    fields=['symbol','interval','timestamp','open','high','low','close','volume','source']
    for (day,interval),items in by.items():
        d=os.path.join(HIST_DIR,day); os.makedirs(d,exist_ok=True)
        path=os.path.join(d,f'{interval}.csv'); tmp=path+'.tmp'
        # Rebuild from DB for deterministic date-wise archive.
        c=connect(); cur=c.execute('SELECT symbol,interval,ts,open,high,low,close,volume,source FROM candles WHERE date=? AND interval=? ORDER BY symbol,ts',(day,interval)); data=cur.fetchall(); c.close()
        with open(tmp,'w',newline='',encoding='utf-8-sig') as f:
            w=csv.writer(f); w.writerow(fields); w.writerows(data)
        os.replace(tmp,path)

def query(symbols,interval,start=None,end=None,limit=200000):
    symbols=list(dict.fromkeys(symbols or [])); c=connect()
    where=['interval=?']; params=[interval]
    if symbols:
        where.append('symbol IN (%s)'%','.join('?'*len(symbols))); params.extend(symbols)
    if start: where.append('ts>=?'); params.append(start)
    if end: where.append('ts<?'); params.append(end)
    sql='SELECT symbol,interval,ts,open,high,low,close,volume,source FROM candles WHERE '+' AND '.join(where)+' ORDER BY ts DESC LIMIT ?'
    params.append(limit); rows=c.execute(sql,params).fetchall(); c.close(); return rows

def coverage(symbols,interval):
    c=connect();
    q='SELECT MIN(date),MAX(date),COUNT(*) FROM candles WHERE interval=?'
    args=[interval]
    if symbols:q+=' AND symbol IN (%s)'%','.join('?'*len(symbols));args+=symbols
    r=c.execute(q,args).fetchone();c.close();return {'min_date':r[0],'max_date':r[1],'rows':r[2]}

def dates():
    c=connect(); r=c.execute('SELECT DISTINCT date FROM candles ORDER BY date DESC').fetchall();c.close();return [x[0] for x in r]
