# Phase 2 — odovzdanie 29. 9. 2026

**Verdikt: BLOCKED_WITHOUT_STATE_CHANGE pre historický search a forward turnaj.**
Existujúci kontrakt zakazuje ďalší cyklus pred1.1.2027 a pred novým kompletným
ročným oknom. Nový engine J–N, veľký search ani turnaj preto neboli spustené.
Nejde o PHASE2_NO_VALID_NOMINEES: kandidáti zatiaľ neboli vyhodnotení.
Nejde o PHASE2_FORWARD_STARTED: zber dát nie je paper portfólio.

Dokončené sú forenzná diagnostika, oddelený návrhový kontrakt s admission zábranou,
nasadený verejný dátový zber a oprava SEALED status handlingu. „WITHOUT_STATE_CHANGE“
označuje nemennosť vedeckého cyklu a produkcie; neskrýva výslovne povolené zmeny
research orchestration ani vytvorenie novej zberovej databázy.

## 1. Čo ukázal prvý cyklus

Zostáva **SEALED / REJECT**,7203 evaluácií,72/72 zamietnutých výsledkov.
Žiadny historický výsledok nebol znovu optimalizovaný ani povýšený na víťaza.
Forenzný nástroj číta SQLite iba `mode=ro&immutable=1` zo samostatnej obnovenej
kópie132-súborového archívu. Pred analýzou overuje všetky prenosové hashe;
po nej opäť overuje hashe oboch databáz. Neimportuje evaluator.

### F: vysoký CAGR neznamenal kontrolované riziko

Pevná diagnostická referencia: F/4517/deterministic/A. CAGR44.78094%,
MDD36.35545%, Sharpe1.0610, Calmar1.2318. Celý výsledok pochádza z BTC.
Priemerná expozícia bola82.33%; počas rozhodujúcich prepadov takmer100%.
Intrabar účet dosiahol maximum173.93999USD dňa14.3.2024 a minimum voči tomuto
vrcholu110.70333USD dňa5.8.2024. Dátumy sú denné obálky uloženého4h účtu,
nie vymyslené presné časy intrabar maxima/minima.

|Celá uzavretá epizóda BTC, UTC|Zisk USD|Logaritmický príspevok|
|---|---:|---:|
|1.1.2024 04:00 →31.3.2024 08:00|65.41518|0.503288|
|30.9.2024 04:00 →29.12.2024 08:00|69.38267|0.385239|
|1.5.2025 04:00 →30.7.2025 08:00|45.65525|0.216141|

Spolu180.45310USD; ostatné epizódy spolu−70.73168USD. Koncový účet209.72142USD
z pôvodných100USD. Odstránenie týchto troch celých epizód dáva CAGR−16.63192%,
nezávisle prepočítané zo zachovaných logaritmických príspevkov. Je to citlivosť
atribúcie, nie obchodovateľná alternatíva.

Rok2024 mal zamrznuté BTC momentum365, týždenné vstupy a trojdňové potvrdenie;
2025 používal mesačné vstupy podľa SMA200. Výsledky kontinuálneho účtu sú
+115.90208% a−3.01814% anualizovane. Trhový režim aj pravidlo sa zmenili súčasne,
preto nemožno celú zmenu pripísať jednému faktoru. Zisky z dlhých2024 trendov
prevážili veľký medzičasový pokles;2025 boli slabšie a prerušované výstupy/vstupy.
Epizóda30.12.2024–10.3.2025 stratila27.79253USD;1.8.–18.10.2025 stratila18.28906USD;
krátky návrat1.–4.11.2025 ďalších6.86824USD. Najhorší deň3.3.2025 bol−8.53865%
pri plnej expozícii. Pomalý potvrdený trend-loss výstup tak toleroval významnú
stratu, kým sa signál obrátil. Bez nového kontrafaktuálneho replaya nevyčíslujeme
oddelený kauzálny podiel „zlého vstupu“ a „neskorého výstupu“.

Hlavné podložené mechanizmy: koncentrácia na BTC, vysoká expozícia bez volatility
targetingu a oneskorená reakcia pomalého trendu. Cross-asset korelácia ani rotácia
medzi aktívami nemohli byť príčinou tejto BTC-only referencie. Novembrový krátky
obchod je konkrétny whipsaw; nie všeobecné tvrdenie o mnohých rotáciách.
Funding bol0, pretože ide o spotový proxy track. Celkové náklady5.87724USD a
2×cost CAGR42.48443% ukazujú, že náklady nevysvetľujú primárne zlyhanie rizika.
Už pôvodne zamrznutá ablácii bez90-dňového capu dala44.99%CAGR/33.58%MDD;
nezachránila kvalifikáciu a nevytvorila novú nomináciu.

Uložené režimové atribúcie sú **oddelené ročne resetované diagnostické knihy**.
Nesčítavame ich s kontinuálnym účtom. V2024 vykázali kladné príspevky aj v časti
označenej BTC_nonpositive podľa externého režimového pravidla; to nie je dôkaz,
že taký filter možno spätne aplikovať na už zarobené denné výnosy.

### D: menší drawdown za cenu nízkej účasti a slabého spreadového výnosu

Referencia D/4517/deterministic/B: rovnaký beta-neutral breakout120/top5/weekly
v oboch rokoch, cieľ gross1.0. CAGR7.11830%, MDD22.77488%, Sharpe.4485,
Calmar.3126.286/731 dní bolo CASH, prvá expozícia až15.7.2024; priemerný
gross45.387%, net−.197%. Pravidlo potrebuje súčasnú long aj short stranu;
ak jedna chýba, celý cieľ je CASH. To mechanicky znižuje účasť na smerovom raste.

BTC epizódy prispeli+25.27297USD, DOGE+16.16229USD, XRP+8.95546USD,
ale ETH−33.79558USD. Najmä ETH short4.–28.11.2024 stratil20.85197USD.
Účet skončil114.75411USD; ročné CAGR12.96887% a1.55593%.
Funding nebol hlavnou brzdou: kredity4.21425USD prevýšili debety3.84864USD.
Poplatky+slippage3.52227USD, celkové čisté náklady3.15666USD.
Najvyšší skutočný gross1.24387 prekročil cieľ1.0; cieľ nebol tvrdý MTM cap.
Zvyšková DOGE pozícia3.38250USD ostala započítaná. Top3 removal dáva−12.46643%
a pôvodný adverse mark/funding/fill stress−2.75%CAGR. To zostáva REJECT.

Korelácie jednotlivých obchodov a nezávislý kauzálny rozklad drawdownu nie sú
identifikovateľné iba z uložených súhrnných kníh. Neboli doplnené domnienkou ani
novou optimalizáciou. Kompletné epizódy, najhoršie dni, aktíva, režimy, roky a
pôvodné stressy sú v `evidence/forensics.json`.

## 2. DeepSeek, neaktívne parametre a duplicity

Starý ledger:96 volaní,177 prijatých AI návrhov,207 náhrad v rovnakom rozpočte.
Známe odpovede:483589 tokenov, odhad0.18380472USD; s rezervou troch neznámych
volaní0.20398032USD. Ide o pôvodný auditovaný odhad, nie faktúru ani nový výdavok.
155 odmietnutí bolo kvôli neaktívnym génom,19 kvôli duplicitám; zostávajúce chyby
boli enumy, tri chybné obálky a tri sieťové zlyhania. F nepotrebuje satellite/
weighting/top_k/recipe/gross mutácie; G používa satellite/satellite_k;
H top_k/weighting; D podľa recipe používa gross a prípadne top_k/weighting.
Nový návrh odstraňuje neaktívne polia zo schémy ešte pred API.

Pri177 prijatých návrhoch sme porovnali uložený vývojový výsledok dieťaťa s
jeho skutočným rodičom v tom istom run, bez OOS vstupov. Na troch metrikách
validation CAGR/MDD/Calmar sa32 zlepšilo bez zhoršenia ostatných,81 zhoršilo,
52 malo tradeoff a12 bolo rovnakých. Rozdelenie zlepšenie/zhoršenie:
F6/21, G3/16, H15/32, D8/12. Toto nie je úplný pôvodný Pareto vektor ani
randomizovaný odhad účinku AI; konkrétne delty/ID sú v JSON.

Popisné historické mediány AI armu oproti deterministickému boli lepšie v G
(CAGR19.11% vs9.15%, MDD39.34% vs45.67%), horšie v F/H a mierne horšie v D.
Nula kvalifikovaných výsledkov v oboch ramenách. Nemožno z toho tvrdiť
nezávisle potvrdený AI prínos.1126 canonical candidate ID nemá duplicitné
efektívne génové objekty v našej statickej projekcii; to nevylučuje rovnaké
správanie na konkrétnom úseku.72 nominovaných schedule slotov predstavuje
len46 unikátnych schedule objektov:26 slotov nie je nová hypotéza.

## 3. Nový kontrakt a výsledky

[DESIGN_AUDIT.md](DESIGN_AUDIT.md) obsahuje presné J–N hypotézy, parametre,
rozpočet, dátumy foldov, purge/embargo, statistické brány, stressy, prospective
plán a odhady zdrojov. [research_contract.json](research_contract.json) má SHA256
`a1bbd70687cac4ae6a198eadccc4787396f2c35029da2ceac19914e569a3e8e1`.
Je oddelený od nezmeneného zberového [contract.json](contract.json), ktorého hash
je `28e7fb1d8357cdc855e3fe2adb7b49ada451974878dd162efbf04447af9ac586`.
Stratégie používajú exploratory outer roky 2023/2026, inner dáta najneskôr do
konca 2023 a plný 365-dňový PIT warmup pred tréningom. Žiadny nový strategický
výsledok neexistuje; metodická korekcia dátumov nebola vykonaná podľa výkonu.

|Phase2 položka|Skutočný stav|
|---|---|
|Strategické evaluácie / API / tokeny / USD|0 /0 /0 /0|
|Deterministic vs DeepSeek experiment|NOT_RUN|
|Development výsledky J–N|NOT_RUN_REFIT_BLOCKED|
|Frozen forward kandidáti|Prázdny zoznam; nejde o potvrdených víťazov|
|Forward tracker / paper výnosy|NOT_STARTED; žiadny spätný zápis|
|Benchmark1/2 search workerov|NOT_RUN; starý lock nie je multi-worker lease|
|Long/short, certifikovaný venue backtest|NOT_RUN; neúplná mark/funding/margin história|

Známe nevyriešené realizačné body: celý nový stratégiový engine, event-overlap
purging pri neohraničenom držaní, intrabar stop/fill ablácii, úplný coverage
manifest, statistická pipeline a oddelený forward ledger. Sú výslovne blokované,
nie schované za štítkom „implementované“. Dátum2027 je najskoršia možnosť,
nie automatický termín spustenia ani záruka potrebnej histórie.

## 4. Verejné venue dáta a medzery

Zber štartoval **29.9.2026 17:41:35 UTC**. Každých15min číta iba verejné
Hyperliquid info endpointy. Prvá aktivácia:234 native-perp metadata/context
záznamov,10 balíkov4999 hodinových sviečok,10 L2 snapshotov a10 strán funding
histórie. BTC hodinový úsek5.3.2026 10:00–29.9.2026 16:00 UTC nemá vo vnútri
vyzdvihnutého úseku chýbajúce hodiny. To nedokazuje kompletnú ročnú históriu.
Funding stránkuje po400 hodinách; prvá stránka je iba marec, zvyšok sa dopĺňa
v ďalších aktiváciách. Historické stiahnutie nikdy nie je prospective predikcia.

Mark/oracle/OI/current funding a objem sú dostupné od aktuálneho pozorovania;
nezamieňame oracle za samostatnú historickú indexovú cenu. Full-universe OHLCV,
historické fee/lot verzie, presné listing časy, margin/liquidation história a
reálne všetky intrabar fills ostávajú medzerami.15min L2 a1h sviečka samy osebe
negarantujú realizovateľnosť stopu alebo fillu. Pevný zberový basket10 aktív nie
je PIT obchodné univerzum. Proxy výsledky by museli zostať explicitne oddelené.

VPS download troch dokumentačných stránok skončil HTTPError; v databáze sú
GAP/null, nie nuly. Oficiálne stránky boli dostupné cez webový nástroj a ich
aktuálny stručný facts snapshot je v `evidence/venue-rules-observed.json`:
základná perp taker sadzba4.5bps/maker1.5bps, s oddelenou precision schémou.
To neurčuje fee tier konkrétneho účtu ani historické poplatky.
[Oficiálne poplatky](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees),
[tick/lot pravidlá](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size).

## 5. VPS, checkpointy a izolácia

- Release `c782aa56ff082c4985957fc09a38c2c03c42f716` pod `/opt/trendatlas-phase2/releases/`.
- Samostatná SQLite `/var/lib/trendatlas-phase2/venue.sqlite`, manifest a read-only status export `status.json`.
- `trendatlas-phase2-collector.timer` enabled/active; oneshot collector skončil success a bude opakovaný timerom.
- Prvý run25.63s elapsed,1.173s CPU,25.1MiB peak RAM,1.54MB state. Nejde o benchmark stratégie.
- Append-only SQLite triggers, FULL synchronous transakcie po každej odpovedi, request/receive časy, payload SHA256 a reťaz row hashes.34/34 prvých riadkov a integrity_check overené.
- Druhá automatická aktivácia potvrdila pokračovanie: spolu68 riadkov,62 OK verejných odpovedí a6 dokumentačných GAP;68/68 hashov PASS, integrity ok, stav1.64MB. Nezmenené staré dáta boli overené aj po nej.
- DynamicUser,256MiB/20%CPU/no swap, nízka I/O priorita, vlastný writable root, bez LoadCredential.
- Reálny sandbox probe: UID62582, vlastný status čitateľný; produkcia, frozen research, LeadPilot, docker socket, credential adresáre a home/root nečitateľné aj nezapisovateľné; credential environment neprítomný.

Dispatcher po kontrole frozen hashov vracia ExecCondition1 pre SEALED. Systemd
to označuje `Result=exec-condition`, **nie failed**; `is-failed` vracia inactive.
Pôvodný worker ostáva inactive/success,7203 evaluácií. Corrupt/FAILED/UNKNOWN
nie sú maskované ako úspech. Nebol zmenený dispatcher timer ani engine.

Pred/po nasadení: všetkých133 starých state súborov a všetky frozen engine
súbory zhodné SHA256. Obe databázy, manifesty, nominees, lineage a API ledger
ostali nezmenené. LeadPilot compose hash zhodný; API/frontend/DB healthy a
proxy beží. Produkčná stratégia, účet, pozície, objednávky, planner, Pi timer
a dashboard authority neboli čítané ako výskumné vstupy ani menené. Na Pi
sa táto úloha nepripájala. Nevykonal sa merge, produkčný deploy ani full refresh.

## FILES READ

`AGENTS.md`; povinné `source_of_truth/README.md`, `master_state.md`, `chat_roles.md`,
`project_truth.json`, `export_contract.json`, `paths_registry.json`, `current_issues.md`;
`canonical/script_registry.json`, `output_registry.json`, `registry_workflow.md`;
`source_of_truth/pi_codex_runtime_workflow.md`. Pôvodný workspace je starší a má
nesúvisiace necommitnuté zmeny; bol ponechaný nedotknutý. Po vytvorení izolovaného
worktree na presnom finálnom commite boli prečítané aj zmeny jeho novšej SSOT vrstvy.

Ďalej `causal_evolution/{REPORT,AUDIT,README}.md`, oba frozen kontrakty,
`protocol.py`, `continuation.py`, `proposal_schema.py`, `designer.py`, `vendor/signals.py`;
`causal_delivery_20260928/README.md`, restore/verify tooling, archive index,
celý overený snapshot, comparison/rules/stresses/folds/episodes, finalists,
candidate genes, development tables, DeepSeek ledger a lineage;
`causal_migration/{README.md,runtime.py,deploy.py,test_runtime.py,test_maintenance.py}`;
`causal_resume/runtime.py`; read-only VPS systemd, hashes a container health.

## SOURCE OF TRUTH

Produkcia: výhradne existujúca SSOT/Production Core/Pi authority. Nemenená.
Starý výskum: frozen engine53b6a533…, jeho kontrakty a overený terminálny SQLite.
Phase2 návrh: `research_contract.json` a pôvodné refit obmedzenia; collector:
nezmenený nasadený `contract.json`. Venue observations
sú výskumné surové dáta s lineage, nie account truth alebo venue certifikácia.

**Exact root cause:** vedecký search dnes blokuje frozen refit dátum a chýbajúce
nové ročné okno; status log noise spôsoboval výstup255 z `ready` pre SEALED.
**Exact contract impact:** žiadna zmena starého/produkčného kontraktu. Nový
oddelený prípravný kontrakt; v orchestration iba úspešný skip po existujúcej
validácii nemennosti.

## Testy, zmeny a Git

14/14 nových regresných testov PASS: refit/date/data zábrany, rozpočet/foldy,
SEALED/failed/corrupt/checkpoint admission, zakázané account/order requesty,
redirecty, closed-hour hranica, meta alignment, missing!=0, append-only/hash chain,
nemenná väzba manifestu a sieťové GAP bez falošného výnosu.
`python -m unittest research.phase2_forward.test_phase2 -v`;
`python -m research.phase2_forward.admission` → BLOCKED_WITHOUT_STATE_CHANGE.
`forensics.py --snapshot <overený backup> --out <nový súbor>` →132 hashov PASS,
oba vstupné DB nezmenené. Deployment dry-run PASS; systemd-analyze verify PASS
s nesúvisiacimi upozorneniami systémového xfs CPUAccounting. Real collector,
SQLite integrity/hash chain a sandbox probe PASS. `git diff --check` PASS.

**Forbidden old path checked:** diff voči7d8eead2 nemá zmeny `source_of_truth/`,
`outputs/`, `data/`, production/execution/app, `causal_evolution/` ani
`causal_delivery_20260928/`. Nový kód neimportuje starý evaluator, order SDK,
wallet snapshot ani model/paper equity. Staré údaje sú len read-only forensic.

Presné zmenené súbory a `git add` zoznam: [GIT_ADD.txt](GIT_ADD.txt).
Canonical registre dopĺňajú iba navigáciu na nové neautoritatívne research nástroje.
Branch: `codex/causal-evolution-phase2-forward-20260929`.
Prvý commit: `c782aa56ff082c4985957fc09a38c2c03c42f716` —
`research: gate phase two refit and prepare isolated venue collection`.
Odovzdávací commit a výsledok push sú uvedené v záverečnej odpovedi;
ich vlastný hash nemožno vložiť do toho istého commitu.

Pokračovanie znamená najprv doplniť chýbajúcu implementáciu a validačné dôkazy,
potom znovu posúdiť refit/coverage admission. Žiadny automatický historický
reštart alebo zníženie kvalifikačných kritérií sa týmto nenaplánovalo.
