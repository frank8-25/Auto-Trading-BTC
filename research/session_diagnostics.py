"""Aggregate the latest local testnet session, including its unclosed position."""
from pathlib import Path
import json
import sys
import pandas as pd
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from research.review_session import review


def diagnose(root):
    result=review(root)
    start,end=pd.Timestamp(result['session_start']),pd.Timestamp(result['session_end'])
    events=pd.read_csv(root/'testnet_position_events.csv')
    events['time']=pd.to_datetime(events.Timestamp,format='mixed')
    events=events[(events.time>=start)&(events.time<=end)].sort_values('time')
    monitor=pd.read_csv(root/'testnet_monitor_log.csv')
    monitor['time']=pd.to_datetime(monitor.Timestamp,format='mixed')
    monitor=monitor[(monitor.time>=start)&(monitor.time<=end)].sort_values('time')
    opens=events[events['Position Change'].str.strip().isin(['no->long','no->short'])]
    closes=events[events['Position Change'].str.strip().isin(['long->no','short->no'])]
    last=monitor.iloc[-1]
    result.update(open_events=len(opens),close_events=len(closes),
                  ending_position=str(last.Position),ending_position_observed_at=str(last.time),
                  closed_trades_per_active_day=len(closes)/((end-start).total_seconds()/86400),
                  open_position_included_in_realized_pnl=False)
    # Directional sample excursions are not tick-level extrema, and fees are excluded.
    pairs=[];pending={}
    for row in events.to_dict('records'):
        change=row['Position Change'].strip();symbol=row['Symbol']
        if change in ('no->long','no->short'):
            if symbol in pending:raise ValueError('Overlapping position events')
            pending[symbol]=row
        elif change in ('long->no','short->no'):
            if symbol not in pending:raise ValueError('Close without session open')
            entry=pending.pop(symbol);side=1 if entry['Side']=='long' else -1
            observed=monitor[(monitor.time>=entry['time'])&(monitor.time<=row['time'])&(monitor.Symbol==symbol)]
            returns=side*(pd.to_numeric(observed['Current Price'])/float(entry['Entry Price'])-1)*100
            pairs.append(dict(reason=row['Reason'].split()[0],minutes=(row['time']-entry['time']).total_seconds()/60,
                              sampled_favorable_pct=max(0,float(returns.max())) if len(returns) else None))
    if len(closes)!=result['trades']:raise ValueError('Trade and event counts disagree')
    result['unclosed_event_positions']=len(pending)
    result['exit_diagnostics']={}
    for reason in sorted(set(p['reason'] for p in pairs)):
        subset=[p for p in pairs if p['reason']==reason]
        result['exit_diagnostics'][reason]=dict(count=len(subset),
            mean_holding_minutes=sum(p['minutes'] for p in subset)/len(subset),
            reached_sampled_015pct=sum(p['sampled_favorable_pct'] is not None and p['sampled_favorable_pct']>=.15 for p in subset))
    income=pd.read_csv(root/'testnet_trade_history_income.csv')
    income=income[pd.to_datetime(income.Start).dt.floor('s')==start].iloc[0]
    gross=float(income['Realized Gross USDT'])
    result['commission_to_positive_account_gross_pct']=abs(float(income['Commission USDT']))/gross*100 if gross>0 else None
    result['account_cost_scope']='Includes entry fees for any unclosed position and possibly other account activity; not a closed-trade net allocation.'
    return result


if __name__=='__main__':
    result=diagnose(Path('.'))
    target=Path('research/results_20261011/session_review.json')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(result,indent=2,allow_nan=False))
