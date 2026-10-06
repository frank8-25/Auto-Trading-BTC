"""Download public Binance futures candles/funding only; no authentication."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import time
import urllib.request
import urllib.parse
import pandas as pd

ROOT=Path(__file__).resolve().parent/'data'
START=pd.Timestamp('2025-09-20',tz='UTC')
END=pd.Timestamp('2026-10-05',tz='UTC')
BASE='https://fapi.binance.com'


def fetch(path,params):
    url=BASE+path+'?'+urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url,timeout=30) as response:
                data=json.load(response)
            if not isinstance(data,list):
                raise ValueError('Expected public data list')
            return data
        except Exception:
            if attempt==2:raise
            time.sleep(attempt+1)


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    start,end=int(START.timestamp()*1000),int(END.timestamp()*1000)
    step=900000
    intervals=list(range(start,end,1000*step))
    def chunk(t):
        return fetch('/fapi/v1/klines',dict(symbol='BTCUSDT',interval='15m',startTime=t,
                     endTime=min(t+1000*step,end)-1,limit=1000))
    with ThreadPoolExecutor(max_workers=3) as pool:
        raw=[row for block in pool.map(chunk,intervals) for row in block]
    candles=pd.DataFrame([dict(time=pd.to_datetime(row[0],unit='ms',utc=True),
                              **{key:float(row[i]) for i,key in enumerate(['open','high','low','close','volume'],1)}) for row in raw])
    candles=candles.sort_values('time')
    expected=pd.date_range(START,END,freq='15min',inclusive='left')
    if candles.time.duplicated().any() or not pd.DatetimeIndex(candles.time).equals(expected):
        raise ValueError('Candle dates incomplete or duplicated; stop research')
    funds=[];cursor=start
    while cursor<end:
        block=fetch('/fapi/v1/fundingRate',dict(symbol='BTCUSDT',startTime=cursor,endTime=end-1,limit=1000))
        if not block:break
        funds.extend(block);cursor=int(block[-1]['fundingTime'])+1
    funding=pd.DataFrame([dict(time=pd.to_datetime(r['fundingTime'],unit='ms',utc=True),
                               rate=float(r['fundingRate']),mark_price=float(r['markPrice'])) for r in funds])
    if funding.empty or funding.time.duplicated().any() or (funding.mark_price<=0).any():
        raise ValueError('Funding data missing or invalid')
    if funding.time.min()>START+pd.Timedelta(hours=9) or funding.time.max()<END-pd.Timedelta(hours=9):
        raise ValueError('Funding window incomplete')
    if (funding.time.sort_values().diff().dropna()>pd.Timedelta(hours=9)).any():
        raise ValueError('Funding data contains a gap')
    # Funding is processed at bar opens; do not silently mishandle off-grid timestamps.
    funding['time']=funding.time.dt.round('s')
    if (funding.time.dt.floor('15min')!=funding.time).any():
        raise ValueError('Funding timestamps do not align with candle opens')
    candles.to_csv(ROOT/'btc_15m.csv',index=False)
    funding.to_csv(ROOT/'funding.csv',index=False)
    manifest=dict(source=BASE,start=str(START),end_exclusive=str(END),candles=len(candles),funding_events=len(funding),
                  sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'btc_15m.csv',ROOT/'funding.csv']})
    (ROOT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':main()
