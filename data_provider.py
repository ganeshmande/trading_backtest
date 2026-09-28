import yfinance as yf
import pandas as pd
from datetime import datetime,time,timedelta
from zoneinfo import ZoneInfo
try:
    from historical_store import query as local_query, save_rows as local_save_rows
except Exception:
    local_query = None; local_save_rows = None
IST=ZoneInfo('Asia/Kolkata')
YAHOO_SYMBOLS={'NIFTY50':'^NSEI','SENSEX':'^BSESN','BANKNIFTY':'^NSEBANK','TATAMOTORS':'TMCV.NS'}
PERIODS={'1m':'7d','5m':'1mo','15m':'1mo','30m':'1mo','1h':'3mo','1d':'1y'}
INTERVAL_MINUTES={'1m':1,'5m':5,'15m':15,'30m':30,'1h':60}
def now_ist():return datetime.now(IST)
def get_yahoo_symbol(symbol):return YAHOO_SYMBOLS.get(symbol,f'{symbol}.NS')
def candle_close_time(candle_time,interval):
    candle_time=candle_time.astimezone(IST)
    if interval=='1d':return datetime.combine(candle_time.date(),time(15,30),tzinfo=IST)
    return candle_time+timedelta(minutes=INTERVAL_MINUTES[interval])
def candle_is_closed(candle_time,interval):return candle_close_time(candle_time,interval)<=now_ist()
def prepare_dataframe(data,interval,count=7):
    if data is None or data.empty:return []
    req=['Open','High','Low','Close']
    if isinstance(data.columns,pd.MultiIndex):
        cols=[]
        for c in data.columns:
            vals=list(c) if isinstance(c,tuple) else [c]; cols.append(next((str(v) for v in vals if str(v) in req),str(vals[0])))
        data=data.copy();data.columns=cols
    if any(c not in data.columns for c in req):return []
    data=data[req].copy();data.dropna(subset=req,inplace=True)
    if data.empty:return []
    try:
        if data.index.tz is None:data.index=data.index.tz_localize('UTC')
        data.index=data.index.tz_convert(IST)
    except Exception:return []
    data=data.loc[[candle_is_closed(t.to_pydatetime(),interval) for t in data.index]]
    if data.empty:return []
    data=data.sort_index().tail(int(count));out=[]
    for ts,row in data.iterrows():
        ts=ts.astimezone(IST);o,h,l,c=map(float,[row['Open'],row['High'],row['Low'],row['Close']]); typ='GREEN' if c>o else 'RED' if c<o else 'DOJI'; ct=candle_close_time(ts,interval)
        out.append({'time':ts.isoformat(),'time_display':ts.strftime('%d-%m-%Y %I:%M:%S %p'),'closed_at':ct.isoformat(),'closed_at_display':ct.strftime('%d-%m-%Y %I:%M:%S %p'),'open':round(o,2),'high':round(h,2),'low':round(l,2),'close':round(c,2),'type':typ,'closed':True})
    return out
def extract_ticker_data(data,ticker):
    if data is None or data.empty:return None
    if not isinstance(data.columns,pd.MultiIndex):return data
    for level in range(data.columns.nlevels):
        vals=[str(v) for v in data.columns.get_level_values(level)]
        if ticker in vals:
            try:return data.xs(ticker,axis=1,level=level,drop_level=True)
            except Exception:pass
    try:return data[ticker]
    except Exception:return None
class MarketDataProvider:
    def _local_candles(self, symbol, interval, count):
        if local_query is None: return []
        try:
            rows=local_query([symbol], interval, limit=max(count, 200))
            if not rows:return []
            # query is newest first
            rows=list(reversed(rows))[-int(count):]
            out=[]
            for _,_,ts,o,h,l,c,v,_src in rows:
                t=datetime.fromisoformat(ts)
                ct=candle_close_time(t,interval)
                if ct>now_ist(): continue
                typ='GREEN' if c>o else 'RED' if c<o else 'DOJI'
                out.append({'time':t.isoformat(),'time_display':t.strftime('%d-%m-%Y %I:%M:%S %p'),'closed_at':ct.isoformat(),'closed_at_display':ct.strftime('%d-%m-%Y %I:%M:%S %p'),'open':round(float(o),2),'high':round(float(h),2),'low':round(float(l),2),'close':round(float(c),2),'type':typ,'closed':True})
            return out
        except Exception:return []

    def get_many_candles(self,symbols,interval,count=7):
        if interval not in PERIODS:return {s:[] for s in symbols}
        symbols=list(dict.fromkeys(symbols)); tickers=[get_yahoo_symbol(s) for s in symbols]
        try:data=yf.download(tickers=tickers,period=PERIODS[interval],interval=interval,group_by='ticker',auto_adjust=False,prepost=False,threads=True,progress=False)
        except Exception as e:
            print(f'[BATCH DATA ERROR] {interval}: {e}')
            return {s:self._local_candles(s,interval,count) for s in symbols}
        out={}
        for s in symbols:
            try:
                td=extract_ticker_data(data,get_yahoo_symbol(s)) if data is not None and not data.empty else None
                fresh=prepare_dataframe(td,interval,count) if td is not None and not td.empty else []
                if fresh:
                    if local_save_rows:
                        rows=[]
                        for c in fresh:
                            t=datetime.fromisoformat(c['time']); rows.append((s,interval,t.isoformat(),t.date().isoformat(),c['open'],c['high'],c['low'],c['close'],0,'yahoo_live'))
                        try: local_save_rows(rows)
                        except Exception: pass
                    out[s]=fresh
                else:
                    out[s]=self._local_candles(s,interval,count)
            except Exception as e:
                print(f'[DATA ERROR] {s}: {e}'); out[s]=self._local_candles(s,interval,count)
        return out
    def get_many_candles_for_date_range_local(self, symbols, interval, start_date, end_date):
        """Read a date range from local archive in one query per symbol.
        Returns {YYYY-MM-DD: {symbol: candles}} and never performs an online request.
        """
        if interval not in PERIODS:
            return {}
        symbols=list(dict.fromkeys(symbols))
        try:
            start_day=datetime.fromisoformat(str(start_date)[:10]).date()
            end_day=datetime.fromisoformat(str(end_date)[:10]).date()
        except Exception:
            return {}
        start_dt=datetime.combine(start_day,time(0,0),tzinfo=IST)
        end_dt=datetime.combine(end_day,time(0,0),tzinfo=IST)+timedelta(days=1)
        out={}
        if local_query is None:
            return out
        for s in symbols:
            try:
                rows=local_query([s],interval,start_dt.isoformat(),end_dt.isoformat(),limit=100000)
                for _,_,ts,o,h,l,c,v,_src in reversed(rows):
                    t=datetime.fromisoformat(ts).astimezone(IST)
                    day=t.date()
                    ct=candle_close_time(t,interval)
                    if day<start_day or day>end_day or ct>now_ist():
                        continue
                    if interval!='1d' and not (time(9,15)<=t.timetz().replace(tzinfo=None)<=time(15,30)):
                        continue
                    typ='GREEN' if c>o else 'RED' if c<o else 'DOJI'
                    candle={'time':t.isoformat(),'time_display':t.strftime('%d-%m-%Y %I:%M:%S %p'),'closed_at':ct.isoformat(),'closed_at_display':ct.strftime('%d-%m-%Y %I:%M:%S %p'),'open':round(float(o),2),'high':round(float(h),2),'low':round(float(l),2),'close':round(float(c),2),'type':typ,'closed':True}
                    out.setdefault(day.isoformat(),{}).setdefault(s,[]).append(candle)
            except Exception:
                continue
        for day_data in out.values():
            for s in symbols:
                day_data.setdefault(s,[])
                day_data[s].sort(key=lambda c:c.get('time',''))
        return out

    def get_many_candles_for_date_local(self, symbols, interval, backtest_date):
        """Read exactly one IST calendar date from the local archive only.
        Never performs an online request. Used by historical Strategy studies.
        """
        if interval not in PERIODS:
            return {s: [] for s in symbols}
        symbols=list(dict.fromkeys(symbols))
        try:
            day = datetime.fromisoformat(str(backtest_date)[:10]).date()
        except Exception:
            return {s: [] for s in symbols}
        start_dt=datetime.combine(day,time(0,0),tzinfo=IST)
        end_dt=start_dt+timedelta(days=1)
        out={s:[] for s in symbols}
        if local_query is None:
            return out
        for s in symbols:
            try:
                rows=local_query([s],interval,start_dt.isoformat(),end_dt.isoformat(),limit=10000)
                rows=list(reversed(rows))
                candles=[]
                for _,_,ts,o,h,l,c,v,_src in rows:
                    t=datetime.fromisoformat(ts).astimezone(IST)
                    ct=candle_close_time(t,interval)
                    if t.date()!=day or ct>now_ist():
                        continue
                    if interval!='1d' and not (time(9,15)<=t.timetz().replace(tzinfo=None)<=time(15,30)):
                        continue
                    typ='GREEN' if c>o else 'RED' if c<o else 'DOJI'
                    candles.append({'time':t.isoformat(),'time_display':t.strftime('%d-%m-%Y %I:%M:%S %p'),'closed_at':ct.isoformat(),'closed_at_display':ct.strftime('%d-%m-%Y %I:%M:%S %p'),'open':round(float(o),2),'high':round(float(h),2),'low':round(float(l),2),'close':round(float(c),2),'type':typ,'closed':True})
                out[s]=candles
            except Exception:
                out[s]=[]
        return out

    def get_many_candles_for_date(self, symbols, interval, backtest_date):
        """Return all completed candles for exactly one IST calendar date.
        Local Data Center data is preferred. If the selected date is not stored,
        attempt a bounded Yahoo range fetch, then return whatever the source can provide.
        """
        if interval not in PERIODS:
            return {s: [] for s in symbols}
        symbols=list(dict.fromkeys(symbols))
        try:
            day = datetime.fromisoformat(str(backtest_date)[:10]).date()
        except Exception:
            day = now_ist().date()
        start_dt=datetime.combine(day,time(0,0),tzinfo=IST)
        end_dt=start_dt+timedelta(days=1)
        out={s:[] for s in symbols}
        missing=[]
        if local_query is not None:
            for s in symbols:
                try:
                    rows=local_query([s],interval,start_dt.isoformat(),end_dt.isoformat(),limit=10000)
                    rows=list(reversed(rows))
                    candles=[]
                    for _,_,ts,o,h,l,c,v,_src in rows:
                        t=datetime.fromisoformat(ts).astimezone(IST)
                        ct=candle_close_time(t,interval)
                        if t.date()!=day or ct>now_ist():
                            continue
                        # Intraday backtests use the regular NSE session only.
                        if interval!='1d' and not (time(9,15)<=t.timetz().replace(tzinfo=None)<=time(15,30)):
                            continue
                        typ='GREEN' if c>o else 'RED' if c<o else 'DOJI'
                        candles.append({'time':t.isoformat(),'time_display':t.strftime('%d-%m-%Y %I:%M:%S %p'),'closed_at':ct.isoformat(),'closed_at_display':ct.strftime('%d-%m-%Y %I:%M:%S %p'),'open':round(float(o),2),'high':round(float(h),2),'low':round(float(l),2),'close':round(float(c),2),'type':typ,'closed':True})
                    out[s]=candles
                    if not candles: missing.append(s)
                except Exception:
                    missing.append(s)
        else:
            missing=list(symbols)

        # If local archive has no selected-day data, try the online source for that
        # exact date. This does not resample another timeframe.
        if missing:
            tickers=[get_yahoo_symbol(s) for s in missing]
            try:
                data=yf.download(tickers=tickers,start=start_dt,end=end_dt,interval=interval,group_by='ticker',auto_adjust=False,prepost=False,threads=True,progress=False)
            except Exception as e:
                print(f'[BACKTEST DATA ERROR] {interval} {day}: {e}')
                data=None
            for s in missing:
                try:
                    td=extract_ticker_data(data,get_yahoo_symbol(s)) if data is not None and not data.empty else None
                    fresh=prepare_dataframe(td,interval,10000) if td is not None and not td.empty else []
                    fresh=[c for c in fresh if str(c.get('time',''))[:10]==day.isoformat()]
                    if fresh:
                        out[s]=fresh
                        if local_save_rows:
                            rows=[]
                            for c in fresh:
                                t=datetime.fromisoformat(c['time']); rows.append((s,interval,t.isoformat(),day.isoformat(),c['open'],c['high'],c['low'],c['close'],0,'yahoo_backtest'))
                            try: local_save_rows(rows)
                            except Exception: pass
                except Exception as e:
                    print(f'[BACKTEST DATA SYMBOL ERROR] {s}: {e}')
        return out

    def get_candles(self,symbol,interval,count=7):return self.get_many_candles([symbol],interval,count).get(symbol,[])
    def get_last_7_closed_candles(self,symbol,interval):return self.get_candles(symbol,interval,7)
def get_candles(symbol,interval,count=7):return MarketDataProvider().get_candles(symbol,interval,count)
def get_last_7_closed_candles(symbol,interval):return MarketDataProvider().get_last_7_closed_candles(symbol,interval)
