"""Additional dollar and turnover attribution from actual recorded fills."""
import json
from ledger_archive import Evidence
from common import HERE,write

def main():
    rows=[]
    with Evidence() as z:
        for name in z.namelist():
            if not name.endswith('/fills.json'):continue
            fills=json.loads(z.read(name));eps=json.loads(z.read(name.replace('fills.json','episodes.json')));prefix=name.rsplit('/',1)[0];by_asset={};by_trade={};costs={}
            for f in fills:
                a=f['asset'];ep=str(f['episode']);by_asset[a]=by_asset.get(a,0.)+f['notional'];by_trade[ep]=by_trade.get(ep,0.)+f['notional'];costs[a]=costs.get(a,0.)+f['fee']+f['slippage']
            pnl={}
            for ep in eps:
                if ep['exit'] is not None:pnl[ep['asset']]=pnl.get(ep['asset'],0.)+ep['dollar_pnl']
            total=sum(by_asset.values());positive=sum(max(0.,v) for v in pnl.values())
            rows.append(dict(replay=prefix,asset_turnover_usd=by_asset,trade_turnover_usd=by_trade,asset_costs_usd=costs,asset_realized_dollar_pnl=pnl,max_asset_turnover_share=max(by_asset.values(),default=0)/total if total else None,max_trade_turnover_share=max(by_trade.values(),default=0)/total if total else None,max_positive_realized_asset_pnl_share=max([max(0.,v) for v in pnl.values()],default=0)/positive if positive else None,scope='Per annual replay; open/failed episodes not falsely realized. Aggregate log concentration remains in common_table.json.'))
    write(HERE/'results/concentration.json',rows);print('Attributed',len(rows),'annual replay fill sets')

if __name__=='__main__':main()
