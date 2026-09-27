"""Worker-side development-only serialization; no network dependency."""
from .protocol import CONTRACT
SAFE_METRICS={'cagr','mdd','sharpe','calmar','turnover','costs_usd','trades','asset_concentration','episode_concentration','reliable','worst_fold'}

def make_payload(run,generation,rows,seen):
    safe=[]
    for row in rows:
        folds=[]
        for fold in row['folds']:
            if fold['scope'] not in CONTRACT['deepseek']['allowed_scopes']:raise ValueError('Outer/forward prompt boundary')
            folds.append(dict(scope=fold['scope'],fold=fold['fold'],start=fold['start'],end=fold['end'],metrics={k:v for k,v in fold['metrics'].items() if k in SAFE_METRICS}))
        safe.append(dict(id=row['id'],genes=row['genes'],folds=folds))
    return dict(run=run,generation=generation,schema=CONTRACT['schema'],parents=safe,seen=sorted(seen))
