"""Describe the measured frontier without fitting or promoting another policy."""
from pathlib import Path
import json
import pandas as pd
from prepare import write_json

HERE=Path(__file__).resolve().parent


def main():
    out=HERE/'results';result=json.loads((out/'results.json').read_text())
    policies=result['policies'];spec=json.loads((HERE/'pre_registration.json').read_text())
    folds=pd.read_csv(out/'oos_folds.csv');records=[]
    for mode in ['robust','aggressive']:
        for dd_cap in [.20,.25,.30,.35]:
            pool=[p for p in policies if p['mode']==mode and p['oos']['max_drawdown']<=dd_cap
                  and p['oos']['max_realized_exposure']<=p['cap']+1e-9 and not p['oos']['bankrupt']]
            best=max(pool,key=lambda p:p['oos']['cagr']) if pool else None
            records.append(dict(mode=mode,dd_limit=dd_cap,policy=best['id'] if best else None,
                cagr=best['oos']['cagr'] if best else None,max_drawdown=best['oos']['max_drawdown'] if best else None,
                within_requested_mode_dd_limit=dd_cap<=(.25 if mode=='robust' else .35)))
    pd.DataFrame(records).to_csv(out/'observed_frontier_by_drawdown.csv',index=False,lineterminator='\n')
    best_raw=max(policies,key=lambda p:p['oos']['cagr'])
    above=[dict(policy=p['id'],cagr=p['oos']['cagr'],failures=p['high_return_failures']) for p in policies if p['oos']['cagr']>=1.5]
    write_json(out/'empirical_summary.json',dict(best_observed_cagr_policy=best_raw['id'],
        best_observed_cagr=best_raw['oos']['cagr'],best_observed_cagr_dd=best_raw['oos']['max_drawdown'],
        above_150=above,frontier=records,A=None,B=result['B_observed_best_robust'],C=result['C_observed_aggressive_pareto'],D=True,
        scope='Only the frozen search space and 18 predeclared OOS policies; not a global attainable-return bound',
        new_search_or_parameter_selection=False))
    pct=lambda v:f'{100*v:.2f} %'
    lines=['# Výsledný verdikt','',
        '**Cieľ 150–200 % CAGR zostáva nezmenený. Platný víťaz A nebol potvrdený.**','',
        'Reálne prebehlo 1 944 variantov v šiestich oddelených rozpočtoch a ich 3 888 nákladových/vstupných stresov. '
        'OOS porovnáva 18 vopred určených adaptačných politík, každú v šiestich chronologických foldoch od 2021-01-01 do 2026-09-25. '
        'Nehodnotí najlepší dodatočne vybraný pevný variant na celom OOS.','',
        '| Kategória | Výsledok | OOS CAGR | Maximum DD | Sharpe | Calmar |',
        '|---|---|---:|---:|---:|---:|',
        '| A | Žiadny potvrdený víťaz 150–200 % | — | — | — | — |']
    for category,key in [('B','B_observed_best_robust'),('C','C_observed_aggressive_pareto')]:
        name=result[key]
        if name:
            m=next(p['oos'] for p in policies if p['id']==name)
            lines.append(f'| {category} | `{name}` | {pct(m["cagr"])} | {pct(m["max_drawdown"])} | {m["sharpe"]:.3f} | {m["calmar"]:.3f} |')
        else:lines.append(f'| {category} | Žiadna politika v limitoch režimu | — | — | — | — |')
    lines+=['| D | Žiadny platný high-return víťaz | — | — | — | — |','',
        'B je najvyšší pozorovaný CAGR pri robustnom limite 1,25× a DD ≤25 %. '
        'C je vopred deklarovaný výber podľa najvyššieho Calmar z rizikovo prípustného agresívneho OOS Pareto frontu. '
        'Ide o opisné historické porovnanie; neposúva zmrazené forward nominácie.','',
        f'Najvyšší OOS CAGR zo všetkých 18 politík: **{pct(best_raw["oos"]["cagr"])}**, '
        f'DD **{pct(best_raw["oos"]["max_drawdown"])}**, `{best_raw["id"]}`. '
        f'Počet politík s CAGR aspoň 150 %: **{len(above)}**. Počet prechodov všetkých numerických high-return podmienok: **{len(result["oos_numeric_passes"])}**.','',
        '## Pozorovaná hranica výnosu a drawdownu','',
        '| Režim | Povolený DD v tomto porovnaní | Najlepší pozorovaný CAGR | Skutočný DD | Politika |',
        '|---|---:|---:|---:|---|']
    for r in records:
        label=r['mode']+(' (mimo robustného DD limitu)' if not r['within_requested_mode_dd_limit'] else '')
        lines.append('| '+label+' | '+pct(r['dd_limit'])+' | '+(pct(r['cagr']) if r['policy'] else 'žiadna')+' | '+(pct(r['max_drawdown']) if r['policy'] else '—')+' | '+(r['policy'] or '—')+' |')
    lines+=['','Táto hranica platí pre zmrazený priestor testov. Nie je dôkazom globálneho maxima trhu. '
        'Ak vyšší limit expozície nepridal výnos, tabuľka ho za výhodu nepovažuje. '
        'Cena vyššieho výnosu sa dá tvrdiť iba tam, kde ju ukazuje konkrétna dvojica zmeraných výsledkov; '
        'z týchto behov nemožno dopočítať, koľko páky by spoľahlivo prinieslo 150 %.','',
        '## Samostatné expozičné režimy','',
        '| Režim | Politika growth: CAGR | DD | Maximum skutočnej expozície | Ročný turnover | Ročný súčet nákladov / equity |',
        '|---|---:|---:|---:|---:|---:|']
    for p in policies:
        if p['selector']!='growth':continue
        m=p['oos'];lines.append(f'| {p["mode"]} {p["cap"]:g}× | {pct(m["cagr"])} | {pct(m["max_drawdown"])} | {m["max_realized_exposure"]:.4f}× | {m["turnover"]:.2f}× | {pct(m["cost_drag"])} |')
    lines+=['','Turnover je súčet zobchodovaného notionalu / equity za rok. Nákladový údaj je súčet eventových '
        'nákladových podielov za rok, nie presný rozdiel CAGR medzi beznákladovým a nákladovým modelom.','',
        '## Stresy a stabilita pozorovaných B/C','']
    for key in ['B_observed_best_robust','C_observed_aggressive_pareto']:
        name=result[key]
        if not name:continue
        p=next(p for p in policies if p['id']==name);m=p['oos']
        lines += [f'### {name}','',
            f'- CAGR pri 2× poplatkoch, sklze a fundingu: **{pct(m["double_cost_cagr"])}**.',
            f'- CAGR pri vstupe o jeden realizovateľný bar neskôr: **{pct(m["delayed_entry_cagr"])}**.',
            f'- Bez najlepšieho dňa: **{pct(m["without_best_day_cagr"])}**; bez top 3 obchodov: **{pct(m["without_top_three_trades_cagr"])}**.',
            f'- Najväčší podiel aktíva na čistom log raste: **{pct(m["asset_log_growth_share"])}**; obchodu: **{pct(m["trade_log_growth_share"])}**.',
            f'- Ziskové foldy: **{round(m["profitable_fold_fraction"]*6)}/6**; najhorší fold **{pct(m["worst_fold_return"])}**; susedia **{round(m["parameter_stability"]*6)}/6**.',
            '- Nesplnené numerické high-return podmienky: `'+', '.join(p['high_return_failures'])+'`.','',
            '| Fold | Zvolený variant | Čistý výnos foldu | Max. DD foldu |','|---|---|---:|---:|']
        for f in folds[folds.policy==name].itertuples():
            lines.append(f'| {f.fold} | {f.variant if pd.notna(f.variant) else "CASH"} | {pct(f.total_return)} | {pct(f.max_drawdown)} |')
        lines.append('')
    lines+=['## Audity a nový sealed interval','',
        'Rozšírený anti-lookahead a asset-lineage audit prebehol pre všetkých 18 politík: '
        'prepočet indikátorov z odrezaného prefixu, zmena budúcich cien, kontrola D+2 dostupnosti, '
        'konkrétneho aktíva a OHLC fillov, logaritmického PnL a samostatné účtovanie quantity × zmena ceny mínus náklady. '
        'Detailné výsledky sú v `results/expanded_audits.json` a `results/verification.json`.','',
        'Historický sealed test neexistuje. Výnosy sú podmienené pevným survivor universe a spotovým/funding proxy; '
        'nezávislá historická identita obchodovateľných derivátov, likvidita a venue funding nie sú preukázané. '
        'Tieto dôkazové podmienky zostali neúspešné, aj keby numerický výsledok prekročil cieľ.','',
        'Zmrazené forward nominácie: `'+json.dumps({k:result['forward_nominees'][k] for k in ['A','B','C']})+'`. '
        'Prospektívny paper interval je 2026-09-27 až 2027-09-26, bez refitu. '
        'Stav po zmrazení je WAITING_FOR_FUTURE_DATA; žiadne budúce výsledky neboli vygenerované.','',
        'Úplná [Pareto tabuľka](results/pareto_table.csv), [všetky politiky](RESULTS.md), '
        '[equity krivky](results/equity_curves.png), [Pareto graf](results/pareto_frontier.png), '
        '[reprodukčné príkazy](README.md) a [technický audit](AUDIT.md).']
    (HERE/'DECISION.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')


if __name__=='__main__':main()
