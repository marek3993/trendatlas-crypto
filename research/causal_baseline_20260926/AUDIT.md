# Forenzný audit kauzálneho baseline

## SOURCE OF TRUTH a rozsah

Klasifikácia **B — dátový kontrakt; D — stratégia a účtovanie výnosu**. Pi workflow triedy C bol prečítaný ako obmedzenie read-only zberu; runtime sa neopravoval. Zdrojový kontrakt `source_of_truth/causal_model_performance_contract.json` bol pripravený a overený pred implementáciou konzumenta. Má výslovný stav `candidate_for_review_not_promoted`; nemení schválenú stratégiu v `project_truth.json` ani aktuálny export kontrakt.

Oficiálna pravda zostáva existujúca vrstva `source_of_truth/` na základnom commite. Tento report, archivované technické výstupy a kandidátske výsledky nie sú samy o sebe povolením nasadiť novú pravdu. Práca vznikla v izolovanom worktree na vetve `codex/causal-baseline-reconstruction-20260926`; pôvodný rozpracovaný checkout zostal zachovaný.

## FILES READ

Presné mená a hashe povinných dokumentov a všetkých 23 súborov predchádzajúceho research commitu sú v `FILES_READ.json`. Dodržaný bol AGENTS/read order: README, master_state, chat_roles, project_truth, export_contract, paths_registry, current_issues, script_registry, output_registry, registry_workflow a Pi runtime workflow. Prečítané boli aj všetky členy oboch pôvodných research ZIP balíkov a ich manifesty; tento audit ich nemení.

Kľúčové skontrolované/importované runtime zdroje v novom archíve:

- `phase60_selective_restore_robustness.py` a `src/market_regime_v1/{features,scoring,macro}.py`;
- `scripts/phase63_btc_participation_overlay.py`, `phase66e_probation_governance.py`, `phase66g_production_candidate_live.py`, `phase68g_portfolio_exposure_leverage_validation.py`, `approved_strategy_net_export_helper.py`;
- adaptéry `phase68g_66g_1p25x_candidate_adapter.py`, `phase68g_btc_persistence_10d_early_risk_075_adapter.py`, `phase68g_etf_flow_impulse_early_risk_cooldown_15_adapter.py`, `current_emittable_universe.py`;
- pomocné skripty BTC persistence, ETF probe, ETF cooldown sensitivity a rebuilt candidate;
- tri execution entrypointy boli zachytené/overené ako dôkaz; neboli spustené;
- aktuálny produkčný snapshot/timeseries/manifest, durable papers, trend history/status, universe decisions, ETF panel, freshness, authority/publish manifesty a historické production run manifesty;
- raw denné OHLCV všetkých 12 symbolov, 4h OHLCV, funding a macro CSV. Kompletný zoznam zachytených a byte-verified súborov obsahuje `input_bundle.manifest.json`.

## Presný beh a hranica reprodukcie

Publikovaný commit je `6fccbc388c1db75f6b46113fac15b7d3232e4123`. Snapshot pre closed day **2026-09-25** bol vytvorený **2026-09-26 10:17:06 UTC**. Jeho provenance označuje runtime kód **`5ee031cef7de9c385056cec22f6511391d3e4f4f`**. Všetkých **50 zachytených Python súborov** sa byte-for-byte zhoduje s týmto commitom; nejde o predpoklad, že runtime bežal na publikovanom commite.

Zodpovedajúci produkčný beh je **`prod_20260926T101542Z_354970`**, 10:15:42–10:17:29 UTC. Model target v tomto historickom manifeste je AVAX 1,25×. Zachytené kroky:

| Udalosť 2026-09-26 | UTC |
|---|---|
| build modelu | 10:16:19–10:16:21 |
| dokončená validácia modelu | 10:16:22 |
| intent | 10:16:24–10:16:25 |
| gate, reconcile a preflight | 10:16:25–10:16:26 |
| executor | 10:16:26–10:16:42 |
| publish krok | 10:16:47–10:17:29 |
| authority run | `20260926_101707` |

Časy dokazujú poradie v danom archivovanom behu; nejde o tvrdenie o presnom čase každého fillu. Publikovací validačný manifest je `outputs/execution/tmp/publish_existing_validation/20260926_101707/app_refresh_pipeline_manifest.json`. Zberač vykonal iba SFTP list/lstat/stat/open(rb). Existujúci manifest opisuje skoršiu produkčnú exekúciu; žiadnu exekúciu nespustil tento audit.

Všetkých **13 deklarovaných priamych vstupných záznamov** snapshotu má zhodný originálny SHA256; BTC súbor je deklarovaný pod dvoma rolami. **Chýbajúce deklarované vstupy: žiadne.** Pôvodný adapter reprodukuje 3 066 riadkov a presne všetky snapshot metrics. Jediná numerická tolerancia navyše je rolling volatility blízko nuly: maximálna odchýlka `6.586e-9`, limit `1e-8`; ostatné numerické stĺpce majú atol `1e-9`, rtol `1e-12`.

Raw Phase60 replay sa zhoduje so všetkými spoločnými stĺpcami uloženého paperu. Opätovne vypočítaná governance má rovnaký weekly chosen asset na každom dni, rovnaký režim a identické strategy returns. Opravených je 157 posunutých position labels. Publikovací manifest však neobsahuje historické hashe **všetkých upstream raw súborov**. Preto presné obnovenie publikovaného durable exportu a numerickú zhodu upstream replay odlišujeme od nemožného tvrdenia, že máme kompletný historický point-in-time dátový archív.

## Presná príčina

1. **Kandidát prepísal ekonomické aktívum.** `phase68g_portfolio_exposure_leverage_validation.py:109` uprednostní `chosen_asset`. V `build_portfolio_exposure_frame` okolo riadku 259 ním prepíše `portfolio_held_asset`, ale preberie pôvodný `base_ret`. Weekly kandidát je pritom vyplnený aj vtedy, keď sa kandidátsky trigger nevykonal. Výnos pôvodnej vetvy zostane, zmení sa iba názov. DOGE/TRX nie je zamenená pozícia stĺpcov raw dát.
2. **BASE stratí ekonomickú identitu.** Normalizátory nechajú route label BASE namiesto konkrétneho symbolu. Navyše `phase63_btc_participation_overlay.py:739–746` posunie `signal_position`, hoci BASE vetva používa už načasovaný core return toho istého riadku. Pozícia je pri prepnutí dvojito posunutá. Oprava viaže BASE na Phase60 holding rovnakého ekonomického intervalu.
3. **Filter D spätne riadi return D.** Statický adapter okolo riadkov 773–788 aplikuje trend permission/stress odvodený z D na `authorized_return_gross` D. ETF helper `dev_only_phase68g_etf_flow_impulse_cooldown_sensitivity.py:250–256` po rozhodnutí z close D priradí buď 0,5× BTC return D, alebo nulu. Persistence layer má podobné same-row 0,75× priradenie. Rozhodnutia možno zachovať ako target output, tieto návratové stĺpce nemožno použiť ako vykonaný PnL.
4. **Net bol prenášaný ako gross.** Phase60 `strategy_ret` už zahŕňa náklady. Downstream `base_return`/`base_ret` ho prenáša pod gross výpočtom a aplikuje ďalšie náklady. Nový gross sa vždy počíta z cien konkrétneho aktíva; explicitné nové náklady sa odpočítajú raz.

## Presný contract impact a exekučná konvencia

Nový čistý modul `scripts/production/causal_performance.py` neimportuje runtime I/O, exchange, authority ani account adaptéry. Prijíma explicitné signály a ceny. Legacy helpery sa v izolovanom replay používajú na rekonštrukciu rozhodnutí a na pôvodnú reprodukciu; ich same-day return/equity stĺpce nevstupujú do nového PnL.

- Target z uzavretého D je dostupný až po konci D. Dostupnosť je uvedená pri každom signále, vrátane dôvodu a zdroja.
- 3 041 dní: predpoklad D+1 12:00 UTC; 24 dní: zachovaný čas validácie pôvodného modelu; posledný deň: publikovaný snapshot 10:17:06 UTC. Kontrafaktuálny nový model tým nepredstiera existenciu historických vlastných buildov.
- Vstup je na prvom dennom spotovom open dostupnom po tomto čase. Predchádzajúca pozícia dostane celý predchádzajúci interval. D close nikdy spätne nevynuluje jej stratu.
- Posledný close je iba terminal valuation mark na dennej hranici; nikdy sa nepoužije na nový fill. Posledný target zostáva bez realizovaného intervalu.
- Každá cena je identifikovaná symbolom, timestampom, CSV súborom, 1-based riadkom vrátane hlavičky a stĺpcom. Duplicity, neznáme aktívum, chýbajúci aktívny price/availability a neúplný interval vyvolajú chybu. BASE je zakázané ekonomické aktívum.
- Gross = vykonaná expozícia na začiatku intervalu × (end/start − 1). Jednotky sú pevné medzi skutočnými zmenami asset/target exposure; denný drift expozície nevytvára bezplatný rebalance.
- Fee 4,5 bp a slippage 10 bp sa účtujú na obrat skutočnej zmeny vrátane oboch strán rotácie. Bez zmeny nie sú transition náklady. Borrow zostáva 12 % p.a. na notional nad 1×. Funding proxy je dodatočný kladný náklad 3 bp/deň z celej expozície. Nie je to namerané funding ani zaručená horná hranica; borrow navyše nie je tvrdenie o mechanike Hyperliquid financovania.
- V uložených dátach nie je kompletná historická Hyperliquid mark/funding séria. Binance 4h dáta končia 2026-03-21, funding pokrýva iba päť Binance symbolov. Preto sa nemieša čiastočná intradenná história s neskorším denným režimom; baseline používa jednu úplnú dennú konvenciu. Macro file končí 2026-03-08 a neobsahuje release vintages. Tieto obmedzenia sú súčasťou kandidáta.
- `model_index` = cumprod(1 + causal net return). Real-account graf prijíma iba explicitný exchange-native account ledger. Model equity ani staré polia `actual_held_asset/current_asset/effective_market_exposure` sa nepoužívajú ako informácia o peňaženke.

Pôvodný selector drop list LTC/SOL sa nezmenil. Platí na candidate vetvu; BASE môže pochádzať z LTC/SOL. Oprava tento existujúci rozdiel odhaľuje, nezavádza nový allowlist, approval gate ani execution gate. Nesúlad s publikovaným emittable-universe kontraktom sa musí posúdiť pred prípadným budúcim nasadením; tento commit runtime nemení.

## Starý a opravený výsledok

Obdobie 2018-05-05 až 2026-09-25, 3 066 denných intervalov. Spoločné porovnávacie definície: 365,25 dní/rok, sample std pre Sharpe, RMS záporných returns cez všetky dni pre Sortino, nulová risk-free sadzba a initial equity 1 pre drawdown.

| Metrika | Pôvodný rad, spoločná definícia | Kauzálny kandidát |
|---|---:|---:|
| CAGR | 182,0261 % | **31,4471 %** |
| Celkový výnos | 602 239,9336 % | **892,7171 %** |
| Max drawdown | −12,9306 % | **−40,6292 %** |
| Sharpe | 2,1987 | **0,7511** |
| Sortino | 8,3578 | **1,5890** |
| Calmar | 14,0771 | **0,7740** |
| Fee, súčet denných p. b. | 11,5200 | 13,8916 |
| Slippage, súčet denných p. b. | 15,7000 | 30,8702 |
| Borrow, súčet denných p. b. | 2,4476 | 2,7802 |
| Funding, súčet denných p. b. | 0 | 20,8196 |

Publikovaný snapshot uvádza CAGR 182,1216 % a Sortino 3,6271 podľa starších metrík. Tieto hodnoty sú zachované v `comparison.json`; neprezentujeme zmenu definície Sortino ako zmenu stratégie. Náklady v tabuľke sú súčtom podielov dennej equity, nie dolárovou sumou ani jednoduchým odpočtom od zloženého celkového výnosu.

`daily_comparison.csv` obsahuje každý deň. `removed_returns.csv` obsahuje 646 kladných znížení net výnosu; 289 dní má po oprave vyšší výnos. Podpísaná denná dekompozícia je presná: pôvodný gross → cena ekonomického aktíva pri pôvodnej same-day expozícii → nový vykonaný gross → rozdiel explicitných nákladov. Prostredný člen je iba diagnostika. Timing člen zahŕňa zmenu držby, drift expozície aj open konvenciu. Nejde o jedinečnú príčinnú alokáciu ani aditívny total return. Oprava nesprávneho názvu nemusí odstrániť legitímny výnos.

## Tri konkrétne dni a aktuálny cieľ

**2024-12-03:** published DOGE 1× pripísal +96,1086 %. Raw DOGE close/close bolo približne −4,2985 %; +96,1086 % je TRX. Phase60 drží TRX, Phase63/66 majú BASE vetvu TRX a weekly candidate DOGE. Nový model tiež včas drží TRX: signal data day 2024-12-01, dostupnosť 2024-12-02 12:00 UTC, vstup 2024-12-03 open. Gross +96,1068 %, net **+95,7482 %**. Oprava premenovala zdroj správne a zúčtovala ceny/náklady; tento zisk sa nesmie svojvoľne vymazať.

**2025-01-07:** starý model prepol na CASH na základe close filtra a ponechal iba −0,1225 % náklad. Nový model počas dňa stále drží BTC z rozhodnutia 2025-01-05 dostupného 2025-01-06 12:00 UTC. Driftovaná expozícia je 0,510089×, gross −2,6349 %, net **−2,6502 %**. Dnešné CASH rozhodnutie nemôže odstrániť už vzniknutú stratu.

**2026-09-24:** published AVAX 1,25× má gross +20,4358 %, net +20,3796 %. Jeho podklad je v skutočnosti LTC +16,3486 % × 1,25. V kauzálnom intervale model drží BTC 0,5× z rozhodnutia 2026-09-22, dostupného 2026-09-23 00:11 UTC. Gross +0,007488 %, net **−0,080012 %**; čistý rozdiel je **20,4596 p. b.** Nový signál nezíska pohyb pred svojím vstupom a AVAX nedostane pohyb LTC.

**Posledný deň:** weekly candidate **AVAX zostáva rovnaký**, ekonomická BASE vetva a opravený target sú **LTC 1,25×**. Target z 2026-09-25 je dostupný 2026-09-26 10:17:06 UTC a prvý denný proxy vstup by bol 2026-09-27 00:00 UTC. Táto cena v archíve nie je, preto sa fill ani jeho PnL nevymýšľa. Výpočet netvrdí, že skutočný účet drží LTC. Aktuálna AVAX pozícia sa nemenila.

## Regresie a validation commands/results

`test_causal.py`: **19 testov PASS**. Pokrýva všetkých 10 požadovaných regresií vrátane skutočného zachyteného close/ETF helpera, symbolových joins pre všetkých 12 mincí, missing/duplicate keys, fixných jednotiek a driftu, source row integrity, neplatných aktívnych ledger rows, privacy/integrity ZIP, ignorovania starých return stĺpcov a presného denného rozkladu. Dva úplné clean raw replays finálneho kódu majú bitovo zhodné dátové výsledky. Súbory zapisujú jednotné LF konce riadkov a kontrolné hashe boli overené aj voči skutočným Git index blobom, aby zostali platné po novom checkoute.

```text
python research/causal_baseline_20260926/run.py
python research/causal_baseline_20260926/run.py --out research/causal_baseline_20260926/scratch/determinism
python -m unittest discover -s research/causal_baseline_20260926 -p test_causal.py -v
python -m unittest discover -s tests -p test_source_of_truth_json_valid.py -v
python -m unittest discover -s tests -p test_dashboard_public_contract_materializer.py -v
python research/causal_baseline_20260926/render_chart.py
git diff --cached --check
```

Existujúce SSOT testy **6 PASS**, existujúce dashboard contract testy **11 PASS**. Graf bol vykreslený a vizuálne skontrolovaný; nemá účet ani interné názvy stratégií v používateľskom zobrazení. Source hashes, výsledky a prostredie sú v `reproduction_manifest.json`.

## Forbidden old path checked

Nový ledger neprijíma `base_ret`, `probe_strategy_return_gross`, staré `return_net` ani model equity ako účtovný vstup. Poison test dokazuje, že ani ich pridané falošné hodnoty nezmenia výsledok. BASE je odmietnuté, ceny sa nejoinujú pozíciou stĺpca, chart sa nerebasuje na starú equity a model/account vstupy sa nemiešajú. Staré helpery sú zachované ako byte-pinned dôkaz a generator targetov; ich chybná PnL cesta zostáva iba v reprodukcii pôvodného výsledku. Existujúci živý runtime ostáva v tejto review vetve nezapojený do kandidáta.

Žiadne root `outputs/*` alebo `data/*` neboli upravené ani zahrnuté do commitu. Žiadny refresh, service, publish, reconciliácia, timer zásah, order API, merge či deploy sa na Pi nevykonal. Zberač neukladá prihlasovacie heslo, privátny kľúč ani adresu účtu. Archivované run manifesty obsahujú iba potrebné modelové údaje a časy; account/order payloady sú odstránené s rozlíšením originálneho a uloženého hashu.

Samostatný budúci problém je kolízia otvorených reduce-only ochranných objednávok s normálnou rotáciou. V tejto oprave sa planner ani ochranné objednávky nemenili.

## Súbory, git add, commit

Presný zoznam všetkých pridaných súborov je `GIT_ADD.txt`, vrátane kontraktu, čistého modulu, zberača, reprodukcie, testov, reportov a research výsledkov. Žiadne existujúce runtime súbory sa neprepisujú.

```powershell
git add --pathspec-from-file=research/causal_baseline_20260926/GIT_ADD.txt
git commit -m "fix: reconstruct causal model baseline with pinned Pi evidence"
git push -u origin codex/causal-baseline-reconstruction-20260926
```

Commit message: `fix: reconstruct causal model baseline with pinned Pi evidence`.

Commit hash identifikuje commit obsahujúci tento report a je uvedený vo finálnom odovzdaní; lokálne `git log -1 --format=%H -- research/causal_baseline_20260926/AUDIT.md`.
