"""2026-10-11 fixed candidate comparison; no live integration or parameter sweep."""
from pathlib import Path
import json
import hashlib
import sys
import zipfile
import pandas as pd

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from research.strategy_review import Variant,features,run,WINDOWS

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data_20261011'
OUTPUT=ROOT/'results_20261011'
END='2026-10-11 13:15:00'
VARIANTS=[Variant('baseline'),Variant('adx25',25),
          Variant('target45',target_fraction=.0045),
          Variant('exit_confirm2',exit_confirmation=2),
          Variant('bb_rsi_range',target_fraction=.0045,entry_mode='range')]
PERIODS=WINDOWS[:3]+[('new_period','2026-10-05',END)]


def acceptance(rows):
    outcomes={}
    for variant in VARIANTS[1:]:
        failures=[]
        for label in ('validation','historical_check'):
            for cost in (1,2):
                row=next(r for r in rows if r['window']==label and r['variant']==variant.name and r['cost_factor']==cost)
                base=next(r for r in rows if r['window']==label and r['variant']=='baseline' and r['cost_factor']==cost)
                if not (row['return_pct']>0 and (row['profit_factor'] or 0)>1.1 and row['trades']>=30
                        and .75<=row['frequency_ratio']<=1.25
                        and row['max_close_drawdown_pct']<=base['max_close_drawdown_pct']):
                    failures.append(f'{label}/cost{cost}')
        outcomes[variant.name]={'accepted':not failures,'failed_windows':failures}
    return outcomes


def download():
    # Old snapshot remains untouched, so the 10/06 report stays reproducible.
    from research import download_data as downloader
    downloader.ROOT=DATA
    downloader.START=pd.Timestamp('2026-10-05',tz='UTC')
    downloader.END=pd.Timestamp(END,tz='UTC')
    downloader.main()
    previous=ROOT/'data'
    if not (previous/'manifest.json').exists():
        with zipfile.ZipFile(ROOT/'market_data_snapshot.zip') as z:
            for name in ['btc_15m.csv','funding.csv','manifest.json']:
                previous.mkdir(parents=True,exist_ok=True)
                (previous/name).write_bytes(z.read(name))
    manifest=json.loads((previous/'manifest.json').read_text())
    for name in ['btc_15m.csv','funding.csv']:
        if hashlib.sha256((previous/name).read_bytes()).hexdigest()!=manifest['sha256'][name]:
            raise ValueError('Original snapshot hash mismatch')
        combined=pd.concat([pd.read_csv(previous/name),pd.read_csv(DATA/name)],ignore_index=True)
        if combined.time.duplicated().any():raise ValueError('Overlapping snapshots')
        combined.to_csv(DATA/name,index=False)
    manifest.update(end_exclusive=END+'+00:00',candles=len(pd.read_csv(DATA/'btc_15m.csv')),
                    funding_events=len(pd.read_csv(DATA/'funding.csv')),
                    sha256={name:hashlib.sha256((DATA/name).read_bytes()).hexdigest() for name in ['btc_15m.csv','funding.csv']})
    (DATA/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--download',action='store_true')
    args=parser.parse_args()
    if args.download:download()
    manifest=json.loads((DATA/'manifest.json').read_text())
    for name,digest in manifest['sha256'].items():
        if hashlib.sha256((DATA/name).read_bytes()).hexdigest()!=digest:raise ValueError('Data hash mismatch')
    candles=pd.read_csv(DATA/'btc_15m.csv',parse_dates=['time']).set_index('time')
    candles.index=pd.to_datetime(candles.index,utc=True)
    funding=pd.read_csv(DATA/'funding.csv',parse_dates=['time']);funding['time']=pd.to_datetime(funding.time,utc=True)
    sig=features(candles);rows=[]
    OUTPUT.mkdir(parents=True,exist_ok=True)
    for label,start,end in PERIODS:
        for variant in VARIANTS:
            for cost in (1,2):
                result,trades,_=run(candles,sig,funding,variant,start,end,cost)
                result['window']=label
                days=(pd.Timestamp(end)-pd.Timestamp(start)).total_seconds()/86400
                result['trades_per_week']=result['trades']/days*7
                baseline=result if variant.name=='baseline' else next(r for r in rows if r['window']==label and r['variant']=='baseline' and r['cost_factor']==cost)
                result['frequency_ratio']=result['trades']/baseline['trades'] if baseline['trades'] else None
                rows.append(result)
                pd.DataFrame(trades).to_csv(OUTPUT/f'{label}_{variant.name}_cost{cost}_trades.csv',index=False)
    pd.DataFrame(rows).to_csv(OUTPUT/'comparison.csv',index=False)
    decision={'candidate_results':acceptance(rows),'live_deployment':False,
              'frequency_band':[.75,1.25],'new_period_is_diagnostic':True,
              'criteria':'validation and historical_check at both costs: positive return, PF>1.1, trades>=30, 75%-125% baseline trade count, drawdown<=baseline'}
    (OUTPUT/'decision.json').write_text(json.dumps(decision,indent=2),encoding='utf-8')
    print(pd.DataFrame(rows)[['window','variant','cost_factor','trades','frequency_ratio','return_pct','max_close_drawdown_pct']].to_string(index=False))


if __name__=='__main__':main()
