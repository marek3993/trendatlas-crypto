"""Reports are derived only after the frozen experiment completes; no selection feedback."""
import io,json,sys,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from common import HERE,OLD,SPEC,ROOT,write,digest,now

def read(n):return json.loads((HERE/'results'/n).read_text())
def percent(x):return '—' if x is None else f'{0 if abs(x)<1e-12 else 100*x:.2f} %'
def number(x):return '—' if x is None else f'{x:.2f}'
def table(headers,rows):return '| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(str(v).replace('|','/') for v in row)+' |' for row in rows)+'\n'

def main():
    assert (HERE/'results/completed.json').exists()
    oos=read('oos.json');rows={r['candidate_id']:r for r in oos};frozen=read('finalists_frozen.json');unique=frozen['unique'];stress=read('stress.json');caps=read('capacity.json');folds=read('folds.json');neighbors=read('neighbors.json');decision=read('decision.json');dev=read('development.json');val=read('validation.json');ds=read('deepseek_summary.json');gens=read('generations.json')
    stressmap={(r['candidate_id'],r['stress']):r for r in stress};valmap={r['candidate_id']:r for r in val};devmap={r['candidate_id']:r for r in dev}
    fidelity=read('capacity_fidelity.json') if (HERE/'results/capacity_fidelity.json').exists() else []
    compact=[]
    for r in oos:
        i=r['candidate_id'];n=dict(r)
        benchmark=rows['BTC_SMA200_'+r['track']]
        for metric in ['cagr','mdd','sharpe','calmar','asset_concentration','profitable_folds']:
            n['delta_vs_btc_sma200_'+metric]=r[metric]-benchmark[metric] if r[metric] is not None and benchmark[metric] is not None else None
        for s in ['double_cost','delay','coarse','margin10','margin20','funding_adverse']:
            sr=stressmap.get((i,s));n[s+'_cagr']=sr['cagr'] if sr else None;n[s+'_mdd']=sr['mdd'] if sr else None;n[s+'_reliable']=sr['reliable'] if sr else None
        validcaps=[a['capital'] for a in caps+[r] if a['candidate_id']==i and a['reliable']]
        n['max_reliable_tested_capital']=max(validcaps) if validcaps else None
        faithful=[x['capital'] for x in fidelity if x['candidate_id']==i and x['stress']=='nominal' and x['overlay']=='none' and x['reliable'] and x['addition_fill_fraction'] is not None and x['addition_fill_fraction']>=.95]
        n['max_tested_capital_at_95pct_addition_fill']=max(faithful) if faithful else None
        n['primary_addition_fill_fraction']=next((x['addition_fill_fraction'] for x in fidelity if x['candidate_id']==i and x['capital']==100 and x['stress']=='nominal' and x['overlay']=='none'),None)
        n['decision']=decision['candidates'].get(i,{}).get('decision','DESCRIPTIVE_PANEL' if r['candidate'] else 'BENCHMARK')
        n['drawdown_tier']='TARGET_20' if r['mdd']<=.20 else 'ACCEPTABLE_30' if r['mdd']<=.30 else 'ABSOLUTE_LIMIT_ONLY_35' if r['mdd']<=.35 else 'OVER_ABSOLUTE_LIMIT'
        n['neighbor_positive_fraction']=sum(x['reliable'] and x['cagr']>0 and x['mdd']<=.35 for x in neighbors if x['parent']==i)/max(1,sum(x['parent']==i for x in neighbors)) if i in unique else None
        compact.append(n)
    pd.DataFrame(compact).to_csv(HERE/'results/complete_comparison.csv',index=False);write(HERE/'results/complete_comparison.json',compact);cr={r['candidate_id']:r for r in compact}
    family=[]
    for f in ['F','G','H','D']:
        rs=[r for r in oos if r['family']==f];valid=[r for r in rs if r['reliable']];p=[r for r in valid if r['mdd']<=.25 and r['cagr']>0]
        family.append(dict(family=f,oos_rows=len(rs),reliable_rows=len(valid),validation_qualified=sum(r.get('validation_qualified',False) for r in rs),target_numeric_rows=sum(r['cagr']>=1.5 and r['mdd']<=.35 and r['sharpe']>=1.5 and r['calmar']>=4 for r in valid),positive_mdd25_rows=len(p),cagr_range=[min(r['cagr'] for r in rs),max(r['cagr'] for r in rs)],minimum_mdd=min(r['mdd'] for r in rs),decision='PASS' if any(decision['candidates'].get(r['candidate_id'],{}).get('decision')=='PASS' for r in rs) else 'REJECT'))
    write(HERE/'results/family_summary.json',family);pd.DataFrame(family).to_csv(HERE/'results/family_summary.csv',index=False)
    arms=[]
    for g in gens:
        if g['generation']!=3:continue
        assert len(g['seen'])==22
        survivors=[devmap[i] for i in g['survivors']];arms.append(dict(family=g['family'],arm=g['arm'],budget_slots=len(g['seen']),survivors=len(survivors),dev_max_cagr=max(r['cagr'] for r in survivors),dev_min_mdd=min(r['mdd'] for r in survivors),validation_qualified_survivors=sum(valmap[i]['qualified'] for i in g['survivors']),frozen_oos_slot_ids=sorted({v['candidate_id'] for v in frozen['finalists'][g['family']+'_'+g['arm']].values()})))
    pd.DataFrame(arms).to_csv(HERE/'results/arm_comparison.csv',index=False);write(HERE/'results/arm_comparison.json',arms)
    # Exact one-factor fixed-panel differences, including BTC-core versus default satellite.
    panel=json.loads((HERE/'candidate_panel_frozen.json').read_text())['panel'];pairs=[]
    from common import cid
    for x,c in enumerate(panel):
        for d in panel[x+1:]:
            changed=[k for k in c if c[k]!=d[k]]
            if len(changed)!=1:continue
            if changed==['family'] and {c['family'],d['family']}!={'F','G'}:continue
            a,b=rows[cid(c)],rows[cid(d)]
            pairs.append(dict(component=changed[0],from_id=cid(c),to_id=cid(d),from_value=c[changed[0]],to_value=d[changed[0]],delta_cagr=b['cagr']-a['cagr'],delta_mdd=b['mdd']-a['mdd'],delta_sharpe=b['sharpe']-a['sharpe'],delta_calmar=b['calmar']-a['calmar'],delta_turnover=b['turnover']-a['turnover'],delta_cost_usd=b['costs_usd']-a['costs_usd'],both_reliable=a['reliable'] and b['reliable']))
    pd.DataFrame(pairs).to_csv(HERE/'results/component_ablations.csv',index=False)
    # Reporting categories never change configurations, frozen finalists or forward nominations.
    fr=[cr[i] for i in unique];target=[r for r in fr if decision['candidates'][r['candidate_id']]['decision']=='PASS']
    low=[r for r in fr if r['reliable'] and r['mdd']<=.25 and r['cagr']>0]
    valid=[r for r in fr if r['reliable'] and r['mdd']<=.35 and r['cagr']>0 and all(v for k,v in decision['candidates'][r['candidate_id']]['checks'].items() if k!='target')]
    best_low=max(low,key=lambda r:(r['calmar'],r['sharpe'],-r['mdd'])) if low else None
    compromise=max(valid,key=lambda r:(r['calmar'],r['sharpe'],-r['mdd'])) if valid else None
    diagnostic=max([r for r in fr if r['reliable']],key=lambda r:r['cagr'],default=None)
    # The user also requested the best observed <=25% DD candidate across the full
    # prespecified panel. Do not hide such a row merely because it failed validation.
    panelids={cid(c) for c in panel}
    panelrows=[r for r in compact if r['candidate_id'] in panelids and r['reliable'] and r['cagr']>0]
    panel_low=max([r for r in panelrows if r['mdd']<=.25],key=lambda r:(r['calmar'],r['sharpe'],-r['mdd']),default=None)
    panel_aggressive=max(panelrows,key=lambda r:r['cagr'],default=None)
    leaders={r['candidate_id']:r for r in [panel_low,panel_aggressive] if r is not None}
    leader_evidence=[]
    for i,r in leaders.items():
        leader_evidence.append(dict(candidate_id=i,candidate=r['candidate'],oos=r,development=devmap[i],validation=valmap[i],pre_oos_finalist=i in unique,status='DESCRIPTIVE_FIXED_PANEL_REJECT',not_run_stresses=['double_cost','delay','coarse','capacity','parameter_neighbors'] if i not in unique else [],note='Already frozen panel rule, identified descriptively after OOS; not promoted, mutated, forward-nominated or claimed stress-qualified.'))
    write(HERE/'results/descriptive_panel_leaders.json',leader_evidence)
    write(HERE/'results/decision_slots.json',dict(A=[r['candidate_id'] for r in target],B_descriptive_panel=panel_low['candidate_id'] if panel_low else None,B_qualified_frozen=best_low['candidate_id'] if best_low else None,C=compromise['candidate_id'] if compromise else None,D=decision['overall'],diagnostic_aggressive_frozen=diagnostic['candidate_id'] if diagnostic else None,descriptive_aggressive_panel=panel_aggressive['candidate_id'] if panel_aggressive else None,note='Full-panel B and aggressive rows are descriptive, validation-rejected and not stress-qualified. No change to pre-OOS finalists, decisions or forward nominations.'))
    leader_table=table(['ID / opisný panel','CAGR','MDD','Sharpe','Calmar','náklady USD','bez najlepšieho dňa','bez top 3 obchodov','development MDD','validation CAGR','validation gate'],[[i,percent(r['cagr']),percent(r['mdd']),number(r['sharpe']),number(r['calmar']),number(r['costs_usd']),percent(r['no_best_day_cagr']),percent(r['no_top3_cagr']),percent(devmap[i]['mdd']),percent(valmap[i]['cagr']),valmap[i]['qualified']] for i,r in leaders.items()])
    # Equity and annual folds for every frozen slot; same-track benchmark only.
    try:import matplotlib
    except ImportError:
        sys.path.append('C:/Users/benda/AppData/Local/Temp/ta-archeology-plot-deps');import matplotlib
    matplotlib.use('Agg');import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':9,'axes.spines.top':False,'axes.spines.right':False})
    with zipfile.ZipFile(HERE/'results/ledgers.zip') as z:
        fig,axes=plt.subplots(2,2,figsize=(14,9),constrained_layout=True)
        for ax,f in zip(axes.flat,['F','G','H','D']):
            ids=[i for i,c in unique.items() if c['family']==f];t='perp' if f=='D' else 'spot';ids=['BTC_SMA200_'+t]+ids
            for i in ids:
                d=pd.read_csv(io.BytesIO(z.read(i+'/100/nominal/none/daily.csv')),index_col=0,parse_dates=True)
                ax.plot(d.index,d.nav,label=i+(' [unreliable]' if not cr[i]['reliable'] else ''),linewidth=2.1 if i.startswith('BTC') else 1.1,color='black' if i.startswith('BTC') else None,linestyle='-' if cr[i]['reliable'] else '--')
            ax.set_title(f'{f} / '+('perpetual PROXY' if f=='D' else 'spot research'));ax.set_ylabel('Simulated NAV, USD (initial $100)');ax.legend(fontsize=6);ax.grid(alpha=.2)
        fig.savefig(HERE/'equity.png',dpi=160);fig.savefig(HERE/'equity.svg');plt.close(fig)
        svg=HERE/'equity.svg';svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n',encoding='utf-8')
        fig,ax=plt.subplots(figsize=(11,5),constrained_layout=True)
        for i in ['BTC_SMA200_spot']+list(leaders):
            d=pd.read_csv(io.BytesIO(z.read(i+'/100/nominal/none/daily.csv')),index_col=0,parse_dates=True)
            ax.plot(d.index,d.nav,label=i,linewidth=1.8)
        ax.set_title('Prespecified panel leaders — descriptive OOS, validation REJECT')
        ax.set_ylabel('Simulated spot NAV, USD (initial $100)');ax.grid(alpha=.2);ax.legend()
        fig.savefig(HERE/'panel_leaders.png',dpi=160);plt.close(fig)
    ff=pd.DataFrame([f for f in folds if f['candidate_id'] in unique or f['candidate_id'].startswith('BTC')]);pivot=ff.pivot(index='candidate_id',columns='year',values='cagr')
    fig,ax=plt.subplots(figsize=(10,max(4,len(pivot)*.35)),constrained_layout=True);im=ax.imshow(pivot.to_numpy()*100,aspect='auto',cmap='RdYlGn',vmin=-70,vmax=100);ax.set_yticks(range(len(pivot)),pivot.index);ax.set_xticks(range(len(pivot.columns)),pivot.columns);ax.set_title('Annual OOS CAGR (%) — continuous books, no invented year-end exit')
    for i in range(len(pivot)):
        for j in range(len(pivot.columns)):ax.text(j,i,f'{pivot.iloc[i,j]*100:.1f}',ha='center',va='center',fontsize=8)
    fig.colorbar(im,ax=ax);fig.savefig(HERE/'folds.png',dpi=160);plt.close(fig)
    fig,axs=plt.subplots(1,2,figsize=(13,5),constrained_layout=True)
    for ax,t in zip(axs,['spot','perp']):
        for f,color in [('F','#2864b4'),('G','#d98022'),('H','#168c7c'),('D','#8964bb')]:
            rs=[r for r in oos if r['track']==t and r['family']==f and r['reliable']]
            if rs:ax.scatter([r['mdd']*100 for r in rs],[r['cagr']*100 for r in rs],label=f,color=color,s=22,alpha=.55)
        br=cr['BTC_SMA200_'+t];ax.scatter([br['mdd']*100],[br['cagr']*100],marker='*',s=180,color='black',label='BTC SMA200')
        ax.axvspan(0,20,color='green',alpha=.06);ax.axvline(30,color='orange',linestyle='--');ax.axvline(35,color='red',linestyle=':');ax.axhline(150,color='red',linestyle='--',label='150% CAGR target');ax.set_ylim(-100,205);ax.set_xlim(0,105);ax.set_xlabel('Conservative MDD (%)');ax.set_ylabel('OOS CAGR (%)');ax.set_title(t.upper()+(' CONSERVATIVE PROXY' if t=='perp' else ' research'));ax.legend(fontsize=8);ax.grid(alpha=.15)
    fig.savefig(HERE/'pareto.png',dpi=160);plt.close(fig)
    headers=['ID','Track','reliable','CAGR','MDD','Sharpe','Calmar','turn/yr','cost USD','closed/open','median days','+folds','worst fold','2× CAGR','delay CAGR','no best day','no top3','max nominal test USD']
    table_rows=[]
    for r in [cr['BTC_SMA200_spot'],cr['BTC_SMA200_perp']]+sorted(fr,key=lambda r:(r['family'],r['candidate_id'])):
        table_rows.append([r['candidate_id'],r['track'],r['reliable'],percent(r['cagr']),percent(r['mdd']),number(r['sharpe']),number(r['calmar']),number(r['turnover']),number(r['costs_usd']),str(r['trades'])+'/'+str(r['open_episodes']),number(r['median_holding_days']),str(r['profitable_folds'])+'/3',percent(r['worst_fold']),percent(r['double_cost_cagr']),percent(r['delay_cagr']),percent(r['no_best_day_cagr']),percent(r['no_top3_cagr']),str(r['max_reliable_tested_capital'])])
    family_table=table(['Family','OOS rows / reliable','CAGR range','min MDD','numeric target rows','decision'],[[f['family'],str(f['oos_rows'])+'/'+str(f['reliable_rows']),percent(f['cagr_range'][0])+' … '+percent(f['cagr_range'][1]),percent(f['minimum_mdd']),f['target_numeric_rows'],f['decision']] for f in family])
    status='Žiadny zmrazený kandidát neprešiel všetkými cieľmi a stresmi.' if not target else 'Cieľom a stresom prešli: '+', '.join(r['candidate_id'] for r in target)
    numeric_count=sum(f['target_numeric_rows'] for f in family)
    context=read('benchmark_2022_2025_context.json') if (HERE/'results/benchmark_2022_2025_context.json').exists() else []
    context_text='; '.join(r['track']+': '+percent(r['cagr'])+' CAGR / '+percent(r['mdd'])+' MDD' for r in context)
    rule_rows=[]
    for i,c in sorted(unique.items()):
        extras='scope='+c['scope'] if c['family']=='F' else ('satellite='+str(c['satellite'])+', k='+str(c['satellite_k']) if c['family']=='G' else 'top_k='+str(c['top_k'])+', '+c['weighting'])
        if c['family']=='D':extras+='; '+c['recipe']+'; gross='+str(c['gross'])
        rule_rows.append([i,c['signal'],c['cadence'],c['confirm'],percent(c['hysteresis']),extras])
    txt=f'''# TrendAtlas — pomalé trendy a režimy, 2026-09-27

**Verdikt: {decision['overall']}.** {status} Výskum reálne prebehol. Žiadna stratégia nebola nasadená.

Zdroj: `{SPEC['source_commit']}`; vetva `codex/slow-trend-research-20260927`. Predchádzajúci experiment zostáva nezmenený. B/C sú archivované; žiadne ich mutácie. Primárny účet je simulovaných 100 USD, nie reálny stav účtu.

## A / B / C / D — rozhodnutie

- A, cieľ 150–200 % CAGR: {', '.join(r['candidate_id'] for r in target) or 'NEEXISTUJE'}. Počet riadkov spĺňajúcich súčasne numerický cieľ v celom hlavnom OOS paneli: **{numeric_count}**.
- B, najlepší nominálny člen vopred zmrazeného panelu s MDD ≤25 % podľa Calmar/Sharpe: **{panel_low['candidate_id'] if panel_low else 'NEEXISTUJE'}**. Je to opisný, validačne zamietnutý výsledok; nie robustný finalista ani nominácia na forward. Kvalifikovaný zmrazený finalista v tejto kategórii: **{best_low['candidate_id'] if best_low else 'NEEXISTUJE'}**.
- C, platný kompromis s MDD≤35%, ktorý prešiel všetkými podmienkami okrem hlavného numerického cieľa: {compromise['candidate_id'] if compromise else 'NEEXISTUJE'}.
- D: **{decision['overall']}** pre hlavný cieľ. Najvyšší CAGR medzi spoľahlivými zmrazenými finalistami: {diagnostic['candidate_id'] if diagnostic else 'žiadny'}; tento údaj sám nie je odporúčanie.

Presné jednotlivé dôvody: [decision.json](results/decision.json), kategórie [decision_slots.json](results/decision_slots.json). Cieľ MDD 20 %, prijateľné 30 %, absolútne 35 %; Sharpe ≥1,5 a Calmar ≥4 zostali zachované. Nižšie riziková alternatíva nesmie byť označená za splnenie cieľa 150 % CAGR.

{leader_table}
**B: BTC 90-dňové momentum, mesačné vstupy**, bez potvrdenia a hysterézie, 1× spot, pri opačnom signále kauzálny exit. OOS má 46,43 % CAGR / 23,35 % MDD a 3/3 ziskové roky, ale development MDD bol 58,84 %, validation CAGR −0,94 % a bez troch najlepších celých obchodov ostáva iba 1,14 % CAGR. OOS Sharpe 1,24 a Calmar 1,99 sú pod cieľom.

**Najvyšší nominálny CAGR: BTC 120-dňový breakout, týždenné vstupy**, bez potvrdenia a hysterézie, 1× spot. OOS 64,94 % CAGR / 33,58 % MDD tvorí jeden uzavretý obchod trvajúci 1 017 dní; po jeho odobratí je CAGR prakticky nula. Development MDD bol 55,58 % a validation CAGR −22,69 %. Ani tento výsledok nesplnil kvalifikáciu.

Tieto dva panelové riadky sa po prezretí OOS nestali finalistami. Majú uložené pôvodné pravidlá, náklady, ročné foldy, koncentráciu a citlivosti deň/epizódy, ale **2× náklady, oneskorený fill, kapacita a susedia sú pre ne NOT_RUN**. Povinné úplné stresy boli určené a vykonané pre 15 finalistov zmrazených pred OOS. [Presná evidencia opisných lídrov](results/descriptive_panel_leaders.json). Žiadny robustný alebo agresívny kandidát nebol schválený.

## Časové oddelenie a zmrazenie

Warmup 2019; development 2020–2021; validation 2022; OOS 2023–2025; forward 2026 **neotvorený**. Každá fáza začína vlastným 100 USD účtom. OOS pokračuje cez tri roky s rovnakými pozíciami a pravidlami; ročné foldy sú rezy kontinuálnej knihy, nie fiktívne predaje 31. decembra. Ide o jeden zmrazený selection origin, nie každoročný refit. Historické OOS už bolo v starších fázach skúmané, preto nie je nové nedotknuté sealed obdobie.

[contract.json](contract.json), [protocol_freeze.json](protocol_freeze.json), [candidate_panel_frozen.json](candidate_panel_frozen.json), [engine_freeze.json](engine_freeze.json), [validation nominees](results/validation_nominees_frozen.json), [finalisti](results/finalists_frozen.json) dokumentujú poradie. Po OOS neboli žiadne mutácie. Zachované technické pokusy pred validation/OOS: [risk timing](attempts/pre_causal_risk_fix/attempt.json), [delay stress](attempts/pre_delay_audit_fix/attempt.json), [H schema](attempts/pre_H_schema_fix/attempt.json).

## Rodiny a spoločná tabuľka

{family_table}
Rozsah CAGR zahŕňa aj výslovne označené nespoľahlivé diagnostické riadky. MDD 0 % môže znamenať výlučne CASH a žiadnu obchodnú aktivitu; taký výsledok nie je alpha ani kvalifikovaná alternatíva. Najvyšší spoľahlivý nominálny CAGR v G je 30,58 %, v H 30,38 % a v D 5,41 %; žiadny z nich neprešiel validačným gate.

{table(headers,table_rows)}
Tabuľka je OOS 2023–2025, rovnaké obdobie a 100 USD. Perp riadky sú **CONSERVATIVE_PROXY**; spot je samostatný výskumný track. Náklady sú kumulatívne skutočne účtované simulované doláre: fees+slippage+funding debits−credits. Turnover je jednostranný zobchodovaný notional/NAV za rok. MDD používa nepriaznivé intrabar extrémy; pri viacerých aktívach simultánne nepriaznivé ceny predstavujú konzervatívny bound. Najväčšia kapacita je iba najväčší spoľahlivý nominálny testovaný účet; nejde o živú certifikáciu venue ani interpoláciu. Veľký účet môže zostať čiastočne CASH: [capacity_fidelity.csv](results/capacity_fidelity.csv) preto osobitne ukazuje podiel požadovaného otvorenia, ktorý sa reálne vyplnil. Úplná tabuľka pridáva aj najväčší testovaný účet pri 95 % fill; ide o opisnú toleranciu, nie zmenu zmrazeného PASS gate. V CSV sú CAGR/MDD frakcie (0.35=35%).

Úplné riadky všetkých základov, finalistov a benchmarkov: [complete_comparison.csv](results/complete_comparison.csv). Vrátane explicitných príznakov reliability a benchmark gain/noninferiority; neúspešná diagnostická krivka nie je validovaný kandidát. [Každý ročný fold](results/annual_folds.csv), [všetky evaluácie](results/all_evaluations.csv), [Pareto front oddelene podľa venue tracku](results/pareto_front.csv), [kapacita 100–1m USD](results/capacity.csv).

BTC SMA200 bol znovu vypočítaný z konkrétneho BTC, nie načítaný zo starých ~30 % / 33 %. Spot OOS: {percent(cr['BTC_SMA200_spot']['cagr'])} CAGR / {percent(cr['BTC_SMA200_spot']['mdd'])} MDD; perp PROXY: {percent(cr['BTC_SMA200_perp']['cagr'])} / {percent(cr['BTC_SMA200_perp']['mdd'])}. Presný benchmark gate a rozdiely CAGR/MDD/Sharpe/Calmar/koncentrácie/foldov sú pri každom riadku, vždy s rovnakým trackom a obdobím. Kontextové nové prepočítanie za dlhšie obdobie 2022–2025: **{context_text}**. Rok 2022 bol v tomto benchmarku CASH; rozdiel CAGR teda vysvetľuje aj iný časový menovateľ. [Kontextový replay](results/benchmark_2022_2025_context.json).

## Presné pravidlá

F: samostatné SMA 50/100/150/200, dual 50/200, 100/200, 50/150, breakout 20/55/120/200, momentum 90/180/270/365 a dve vopred určené konjunkcie. BTC/ETH alebo päť likviditných slotov. G: BTC core s daným pomalým signálom; satelit 25/50/75 % v 1–2 likvidných altoch iba pri pozitívnom BTC aj vlastnom trende. H: top 2/3/5 podľa likvidity, vlastný absolútny signál, inverse-vol alebo covariance equal-risk. Záporné/chýbajúce sloty sú CASH; nie relatívny momentum víťaz. D: BTC signed regime, vlastné signed trendy, beta-neutral kladné/záporné trendy, funding-aware filter. D nepoužíva spot cenu na short ani na perp NAV.

Weekly znamená nedeľný dokončený close, monthly posledný deň mesiaca. Potvrdenie 0/3/7/14 po sebe idúcich dní, hysteresis ±0/1/3 %. Opačný potvrdený režim môže vyvolať denný exit; denné vstupy/rotácia povolené nie sú. Breakout používa predchádzajúce n-dňové maximum HIGH/minimum LOW, nikdy dnešné budúce high. Každý vstup prichádza až po dostupnosti signálu a latencii. Plné rovnice a canonical parameter schema: [contract.json](contract.json), implementácia [signals.py](signals.py).

{table(['Finalista','Signál','Cadence','Potvrdenie dní','Symetrická hysterézia','Ďalšie aktívne pravidlá'],rule_rows)}
Úplné canonical konfigurácie vrátane mapovania oboch evolučných vetiev a všetkých troch výberových slotov: [finalists_frozen.json](results/finalists_frozen.json). Všetkých 184 pravidiel panelu bolo uložených v [candidate_panel_frozen.json](candidate_panel_frozen.json) pred výpočtami.

## Ablácie, náklady a stresy

[component_ablations.csv](results/component_ablations.csv) obsahuje{len(pairs)} presných jednoparametrových porovnaní zmrazeného základného panelu, vrátane BTC core→default satelitu tam, kde sa ostatné pravidlá zhodujú. Záporná delta MDD je zlepšenie. Nie je to post-OOS optimalizácia. [overlay_ablations.json](results/overlay_ablations.json) obsahuje iba overlaye základov, ktoré samostatne prešli development+validation gate; počet eligible základov: {len(frozen['overlays'])}. Ak žiadny neprešiel, stop/trailing/TP boli správne NOT_RUN, nie predstierané zlepšenie alphy.

Každý zmrazený finalista má 2× fees/slippage/funding **debits** (credits sa nezdvojnásobujú), oneskorenie o jeden vykonateľný 4h bar, odstránenie najlepšieho portfolio dňa, odstránenie troch najlepších celých uzavretých epizód, všetkých povolených susedov, koncentráciu, ročné foldy, expozíciu a dolárové náklady. [Stresy](results/stresses.csv), [susedia](results/neighbors.csv), [asset/episode koncentrácia](results/concentration.csv), [presná expozícia vrátane driftu](results/exposure.csv), [dolárové náklady za každý rok](results/dollar_costs.csv), [otvorené pozície](results/open_positions.csv). Otvorená epizóda nie je fiktívne uzatvorená, preto sa nepočíta medzi tri ukončené obchody; jej hodnota a koncentrácia zostávajú reportované. Odobratie dňa/epizód je citlivosť presného log-PnL účtu, nie nový obchodovateľný backtest; ich drawdown je close/bar-based, nominálny MDD zahŕňa intrabar bound.

D navyše prešiel maintenance 5/10/20 %, nepriaznivou mark neistotou 0/1/3 %, nulovými funding credits a dodatočným 10 % pa gross debitom. Maržová blízkosť <3× maintenance alebo breach sa označí a spôsobí REJECT; ochranný exit čaká na publikáciu baru a skutočnú exekúciu, nezachráni spätne stratu. Reálny vstupný gross strop je 1/1,25; medzi fillmi môže trhový pohyb spôsobiť drift, preto sa neeviduje fiktívne kontinuálne rebalansovanie.

## Venue, PIT a zvyšky

Historický census obsahuje všetky archívne USDT rizikové spot symboly vrátane zaniknutých. Každý deň treba 365 pozorovaných dní a 30-dňový priemerný quote objem ≥10m USD; portfólio používa najviac päť takto dostupných identít CELKOVO. BTC/ETH samostatné vetvy rešpektujú warmup a likviditu, nepotrebujú top5 rank. Ticker reuse má oddelené epochy. Prvé/posledné ceny sú pozorované dátumy, nie predstieraná úplná administratívna certifikácia. Známe notices sú publication-aware. [PIT membership](pit_membership.csv), [data audit](data_audit.json), [acquisition universe](acquisition_universe.json).

F/G/H účtujú Binance spot; D skutočné Binance USD-M trade/mark/funding. Pri chýbajúcom mark sa používa cena toho istého PERP s výslovným PROXY označením a nepriaznivým mark stresom. Chýbajúca cena držaného aktíva sa nevyplní nulovým výnosom do rankingov: zostáva stale valuation príznak; nad 24h reliability zlyhá. Funding je timestamped, notional používa posledný dostupný vlastný mark, nie neskorší close. Historické margin/fee/lot/listing dôkazy nie sú kompletné; žiadny venue-certified výsledok sa nevyhlasuje.

Základné fees 10 bps a slippage 10 bps sú konzervatívne proxy predpoklady; spot funding 0, perp skutočné signed udalosti. Participation 0,1 % posledného publikovaného quote objemu, entry TTL 6 / exit TTL 18 barov. Nevyplnený zvyšok sa nezmení na fill: ostáva množstvo+MTM. Min-order dust sám neinvaliduje celý výsledok. Celé nevyplniteľné materiálne exity sú osobitný reliability problém. Pri konci OOS sa pozície nepredávajú fiktívne.

Hyperliquid vlastná dokumentácia potvrdzuje 10 USD minimum a 4,5 bps základný perp taker; szDecimals a ceny majú vlastné pravidlá. Binance minimum nebolo označené za Hyperliquid pravidlo. [Primárne zdroje](sources.json). Súčasné HL parametre ani Binance ceny nemôžu certifikovať historické HL plnenie; výskum používa výslovne oddelené proxy tracky. Presné historické lot/tick pravidlá nie sú známe: základná fractional precision a samostatný hrubší 1 USD target-quantity stress sú modelové predpoklady. Výsledky nie sú povolenie na živý 100 USD účet.

## DeepSeek oproti deterministickej vetve

Reálne API volania spolu: **{ds['calls']}**, tokeny **{ds['tokens']}**, odhad ceny **${ds['estimated_usd']:.6f}**, konzervatívne rezervované maximum${ds['reserved_upper_usd']:.6f}. Prijaté návrhy{ds['accepted']}, odmietnuté{ds['rejected']}. Podrobné dôvody, schéma, payloady a usage: [designer_events.jsonl](results/designer_events.jsonl). Kľúč sa neukladá. Cena je odhad podľa oficiálneho cenníka, nie faktúra.

Každá rodina a arm má 10 počiatočných kandidátov, 6 Pareto survivors, 4 mutácie v troch ďalších generáciách: 22 budget slots, spolu 176. Spoločné konfigurácie sa počítajú raz a cache sa zdieľa, budget armov sa tým nemení. Jediný vážený fitness súčet neexistuje. Samostatný 184-členný panel je rovnaký pre oba army a nevstupuje do mutácií. Môže preto viesť k identickému finalistovi oboch armov; to nie je dôkaz prínosu AI. [arm_comparison.csv](results/arm_comparison.csv) ukazuje samostatné search výsledky a validation úspešnosť.

V každej z ôsmich vetiev (4 rodiny × 2 návrhári) bolo vyhodnotených 22 kandidátových slotov. **Žiadny zo šiestich konečných survivorov ani jednej vetvy neprešiel development + validation kvalifikáciou. Prínos DeepSeek oproti deterministickým mutáciám sa preto v tomto experimente nepreukázal.** Vyšší izolovaný development CAGR nie je úspech OOS ani dôvod meniť výber.

Prvý technický pokus bol zastavený počas development po 9 API volaniach. F/G payloady sa pri opakovaní museli presne zhodovať. Tri H volania zostávajú pôvodné development-only hypotézy: po oprave validátora bol equal-notional návrh odmietnutý, povolené návrhy znovu validované a chýbajúce nahradené deterministicky. Pri H sú uložené pôvodné API payloady aj nové verification payloady, výslovne označené ako neodoslané API. Ďalšie opravy pred validation/OOS sa týkali publikácie ochranných perp risk signálov, explicitného gross limitu a delay stresu týchto príkazov. Pôvodná evidencia všetkých prerušených pokusov je zachovaná; nové D volania sa zmestili do pôvodného celkového limitu 12. Žiadna oprava ani hypotéza nevychádzala z validation/OOS výsledkov. Opakované technické výpočty nie sú ďalšie kandidátové budget slots.

![Equity](equity.png)

![Opisní lídri panelu, validačne zamietnutí](panel_leaders.png)

![Annual folds](folds.png)

![Risk versus return and target](pareto.png)

## Reprodukcia a audit

Pozri [README.md](README.md) pre úplné offline príkazy bez nového účtovania API a [AUDIT.md](AUDIT.md) pre FILES READ, SOURCE OF TRUTH, presnú príčinu/kontrakt, regression tests, forbidden-old-path kontrolu a git add zoznam. Výsledkové ZIPy obsahujú denne NAV, účtované dolárové náklady, objednávky, fill lineage a epizódy; primárni finalisti a stresy navyše všetky 4h stavy/množstvá. Žiadny merge, deploy, Pi príkaz ani živá objednávka.
'''
    (HERE/'REPORT.md').write_text(txt,encoding='utf-8');print('REPORT GENERATED',len(fr),'finalists',decision['overall'])

if __name__=='__main__':main()
