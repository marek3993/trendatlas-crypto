import Link from "next/link";
import copy from "@/content/clean5050-copy.json";
import {loadCleanPublic} from "@/lib/clean-public";
export async function CleanPerformance({language="sk"}:{language?:"sk"|"en"}) {
 const t=copy[language],data=await loadCleanPublic();
 const number=(v:number|null|undefined,digits=1)=>typeof v==="number"&&Number.isFinite(v)?new Intl.NumberFormat(language,{maximumFractionDigits:digits,minimumFractionDigits:digits}).format(v):"—";
 const pct=(v:number|null|undefined)=>`${number(v)} %`;
 const m=data?.metrics;
 const cards=[[t.cagr,pct(m?.since_2021.cagr_pct),t.cagrHelp],[t.drawdown,pct(m?.since_2021.max_drawdown_pct),t.drawdownHelp],[t.sharpe,number(m?.since_2021.sharpe,2),t.sharpeHelp],[t.last12,pct(m?.last_12_months.total_return_pct),`${t.drawdown}: ${pct(m?.last_12_months.max_drawdown_pct)} · BTC: ${pct(m?.btc_last_12_months_pct)}`]];
 const series=data?.series??[];const logValues=series.flatMap(r=>[Math.log10(r.clean),Math.log10(r.btc)]);
 const min=Math.min(0,...logValues),max=Math.max(1,...logValues),width=1000,height=340;
 const y=(v:number)=>height-30-(Math.log10(v)-min)/(max-min)*(height-55);
 const curve=(key:"clean"|"btc")=>series.map((r,i)=>`${i?"L":"M"}${(60+i/Math.max(1,series.length-1)*(width-80)).toFixed(2)},${y(r[key]).toFixed(2)}`).join(" ");
 return <section className="clean-page">
  <nav aria-label="Language"><Link href="/?lang=sk">Slovenčina</Link> · <Link href="/?lang=en">English</Link> <Link href="/dashboard" className="clean-account-link">{t.login} →</Link></nav>
  <header><p className="clean-kicker">CLEAN 50/50</p><h1>{t.title}</h1><p className="clean-intro">{t.intro}</p></header>
  <h2>{t.performance}</h2>{m?<p>{t.dataThrough} {m.window.end}</p>:<p role="status">{t.unavailable}</p>}
  <div className="clean-grid">{cards.map(([title,value,help])=><article key={title}><h3>{title}</h3><strong>{value}</strong><p>{help}</p></article>)}</div>
  <p className="clean-note">{t.note}</p>
  {data?<><aside><b>{t.model}: </b>{Object.entries(data.signal.ciel_vahy).map(([asset,w])=>`${asset} ${pct(w*100)}`).join(" · ")}<p>{t.holding} {data.signal.drzat_pocas_dna_utc}</p>{data.stale?<p role="status">{t.stale}</p>:null}</aside>
   <figure><figcaption>{t.chart}</figcaption><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t.chart}>
    {Array.from({length:Math.ceil(max)-Math.floor(min)+1},(_,i)=>Math.floor(min)+i).map(power=><g key={power}><line x1="60" x2="980" y1={y(10**power)} y2={y(10**power)} stroke="#dce4e7"/><text x="5" y={y(10**power)+4} fill="currentColor" fontSize="13">{number(10**power,1)}×</text></g>)}
    <path d={curve("btc")} fill="none" stroke="#e6a23c" strokeWidth="2"/><path d={curve("clean")} fill="none" stroke="#007e70" strokeWidth="2.5"/>
    {series.filter((r,i)=>i===0||r.date.endsWith("01-01")).map(r=><text key={r.date} x={60+series.indexOf(r)/Math.max(1,series.length-1)*920} y="337" fontSize="13" fill="currentColor">{r.date.slice(0,4)}</text>)}
   </svg><p><span style={{color:"#007e70"}}>● Clean 50/50</span> · <span style={{color:"#b57616"}}>● {t.btc}</span></p></figure>
   <p>{t.assumptions}</p><p>{t.fundingProxy}: {m?.since_2021.funding_proxy_days}. {t.unpriced}: {m?.since_2021.unpriced_execution_proxy_days}.</p>
   <h2>{t.annual}</h2><table><thead><tr><th>{t.year}</th><th>Clean 50/50</th><th>{t.btc}</th></tr></thead><tbody>{m?.annual.map(r=><tr key={r.year}><td>{r.year}{r.partial_year?` (${t.partial})`:""}</td><td>{pct(r.return_pct)}</td><td>{pct(r.btc_return_pct)}</td></tr>)}</tbody></table>
  </>:null}
  <h2>{t.how}</h2><ol>{t.steps.map(s=><li key={s}>{s}</li>)}</ol>
  <h2>{t.expect}</h2><p>{t.cash}: {pct(m?.cash_days_pct)}. {t.cashHelp}</p><p>{t.weak}</p><p>{t.params}</p>
  <h2>{t.live}</h2><p>{t.liveHelp}</p><Link href="/dashboard">{t.login} →</Link>
 </section>;
}
