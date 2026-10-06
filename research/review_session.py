"""Read private local journals, output only aggregate review statistics by default.

No balances, quantities, order IDs, or individual trades in the generated summary.
"""
from pathlib import Path
import argparse
import json
import re
import pandas as pd


def review(root):
    history=pd.read_csv(root/'testnet_trade_history.csv')
    summary=history[history.Symbol=='SESSION_SUMMARY'].iloc[-1]
    start=pd.Timestamp(re.search(r'start=(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',summary.Reason).group(1))
    income=pd.read_csv(root/'testnet_trade_history_income.csv')
    matched=income[pd.to_datetime(income.Start).dt.floor('s')==start]
    if len(matched)!=1 or matched.iloc[0].Status!='CONFIRMED':
        raise ValueError('Cannot identify one confirmed income window')
    income=matched.iloc[0];end=pd.Timestamp(income.End)
    trade=history[history.Symbol!='SESSION_SUMMARY'].copy()
    trade['time']=pd.to_datetime(trade.Timestamp,format='mixed')
    trade=trade[(trade.time>=start)&(trade.time<=end)]
    if len(trade)!=int(re.search(r'trades=(\d+)',summary.Reason).group(1)):
        raise ValueError('Session summary and journal trade counts disagree')
    if not trade.Reason.str.contains('basis=EXECUTED_GROSS',regex=False).all():
        raise ValueError('Mixed accounting bases')
    pnl=trade['PnL USDT'];profits=pnl[pnl>0].sum();losses=-pnl[pnl<0].sum()
    exits=trade.Reason.str.split().str[0]
    net=float(income['Net USDT']);commission=float(income['Commission USDT'])
    total=float(income['Realized Gross USDT'])+commission+float(income['Funding USDT'])
    if abs(net-total)>1e-5:raise ValueError('Income components do not reconcile')
    return dict(session_start=str(start),session_end=str(end),environment='TESTNET',trades=len(trade),
                gross_wins=int((pnl>0).sum()),gross_losses=int((pnl<0).sum()),
                gross_win_rate_pct=float((pnl>0).mean()*100),gross_profit_factor=float(profits/losses),
                exit_counts={str(k):int(v) for k,v in exits.value_counts().items()},
                gross_result='negative' if pnl.sum()<0 else 'nonnegative',
                account_net_result='negative' if net<0 else 'nonnegative',
                commission_share_of_account_net_loss_pct=abs(commission/net)*100 if net<0 else None,
                gross_journal_vs_account_difference=round(float(pnl.sum()-float(income['Realized Gross USDT'])),4),
                caveat='Account income may include other activity; rounded trade journal is gross, not per-trade net.')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path('.'))
    parser.add_argument('--output',type=Path,default=Path('research/results/session_review.json'))
    args=parser.parse_args();result=review(args.root)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,indent=2,ensure_ascii=False))
