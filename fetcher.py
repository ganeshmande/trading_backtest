import threading, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import yfinance as yf
import pandas as pd
from data_provider import get_yahoo_symbol
from historical_store import save_rows

IST=ZoneInfo('Asia/Kolkata')
JOB={'running':False,'done':0,'total':0,'status':'Idle','started':None,'finished':None,'errors':[],'rows':0,'warning':''}
LOCK=threading.Lock()
LIMIT_DAYS={'1m':7,'2m':60,'5m':60,'15m':60,'30m':60,'60m':730,'1h':730,'1d':3650}

def _set(**kw):
    with LOCK: JOB.update(kw)

def status():
    with LOCK:return dict(JOB)

def _fetch_one(symbol, interval, start, end):
    ticker=get_yahoo_symbol(symbol)
    try:
        df=yf.download(ticker,start=start,end=end,interval=interval,group_by='column',auto_adjust=False,prepost=False,progress=False,threads=False)
        if df is None or df.empty:return [],None
        if isinstance(df.columns,pd.MultiIndex):
            try: df=df.xs(ticker,axis=1,level=1,drop_level=True)
            except Exception:
                try: df=df.droplevel(-1,axis=1)
                except Exception: pass
        rows=[]
        for ts,row in df.iterrows():
            if pd.isna(row.get('Open')): continue
            if ts.tzinfo is None: ts=ts.tz_localize('UTC')
            ts=ts.tz_convert(IST); day=ts.date().isoformat()
            rows.append((symbol,interval,ts.isoformat(),day,float(row['Open']),float(row['High']),float(row['Low']),float(row['Close']),float(row.get('Volume',0) or 0),'yahoo'))
        return rows,None
    except Exception as e:return [],str(e)

def start_job(symbols,interval,date_from,date_to):
    with LOCK:
        if JOB['running']: return False
        JOB.update({'running':True,'done':0,'total':len(symbols),'status':'Starting','started':datetime.now(IST).isoformat(),'finished':None,'errors':[],'rows':0,'warning':''})
    threading.Thread(target=_run,args=(symbols,interval,date_from,date_to),daemon=True).start();return True

def _run(symbols,interval,date_from,date_to):
    try:
        maxdays=LIMIT_DAYS.get(interval,60)
        end_dt=datetime.fromisoformat(date_to).replace(tzinfo=IST)+timedelta(days=1)
        start_dt=datetime.fromisoformat(date_from).replace(tzinfo=IST)
        warning=''
        if (end_dt-start_dt).days>maxdays:
            effective_start=end_dt-timedelta(days=maxdays)
            warning=f'{interval} historical data source limit applied: only the most recent {maxdays} days can be fetched.'
            start_dt=max(start_dt,effective_start)
        for i,s in enumerate(symbols,1):
            _set(done=i,status=f'Fetching {s} ({i}/{len(symbols)})',warning=warning)
            rows,err=_fetch_one(s,interval,start_dt.strftime('%Y-%m-%d'),end_dt.strftime('%Y-%m-%d'))
            if rows:
                n=save_rows(rows);_set(rows=JOB['rows']+n)
            if err:
                with LOCK: JOB['errors'].append({'symbol':s,'error':err})
        _set(running=False,status='Completed',finished=datetime.now(IST).isoformat())
    except Exception as e:
        _set(running=False,status='Failed: '+str(e),finished=datetime.now(IST).isoformat())
