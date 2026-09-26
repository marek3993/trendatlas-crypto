"""Data-only checks, independent of strategy outcomes; no price correction."""
import market,identity
from common import HERE,write

def main():
    raw=market.frames('spot_daily.zip','2025-12-31');intra=market.frames('spot_4h.zip','2025-12-31 20:00:00');checks=[];extremes=[]
    for s,f in raw.items():
        ratio=f.close/f.close.shift(1)
        for d,v in ratio[(ratio>10)|(ratio<.1)].items():extremes.append(dict(symbol=s,date=str(d),observed_close_ratio=float(v),known_epoch_event=s in {e['symbol'] for e in identity.events()},used_as_price_adjustment=False))
        if s not in intra:continue
        g=intra[s];count=g.close.resample('D').count();last=g.close.resample('D').last();days=f.index.intersection(last.index);days=days[count.reindex(days).eq(6)]
        ratio=(f.close.reindex(days)/last.reindex(days)-1).abs();bad=ratio[ratio>1e-7]
        checks.append(dict(symbol=s,complete_days=len(days),close_mismatches_over_1e_7=[dict(date=str(d),relative_error=float(v)) for d,v in bad.items()]))
    write(HERE/'data_quality.json',dict(complete_day_checks=checks,extreme_price_ratios=extremes,notes='Data-only audit, no performance-based exclusion. Epoch events use primary notices, crashes are retained unchanged. Daily-vs-4h compares complete six-bar days only; no resampling supplies unavailable trading prices.'))

if __name__=='__main__':main()
