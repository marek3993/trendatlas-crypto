# TrendAtlas discovery → evolution: nasadenie a dôkazy

VPS samostatne dokončil osem následníckych batchov. Každý batch bol zmrazený pred discovery aj hodnotením. Výsledok discovery vytvoril research inbox, inbox bol skutočne prevzatý do kandidáta, nezmenený Phase2 engine vykonal backtesty a feedback vstúpil do zmrazenia ďalšieho batchu. Toto je výskum na už videných dátach, bez potvrdeného obchodného kandidáta.

```text
DISCOVERY_ACTIVE=IDLE_NO_NEW_WORK
EVOLUTION_ACTIVE=IDLE_NO_NEW_WORK
CURRENT_CYCLES=none; successor batches 1–8 CLOSED; original SEALED/frozen cycles unchanged
STATISTICAL_DESIGN_FEASIBLE=YES_CONDITIONAL; 39 full blocks, minimum 30 nonzero; temporal null unverified
UNIQUE_NEW_HYPOTHESES=16
CANDIDATES_ACTUALLY_EVALUATED=16
LAST_PROGRESS_UTC=2026-10-09T05:33:03.706371Z
NEXT_AUTOMATIC_ACTION=idle health check; no repeated hypotheses/backtests or paid API calls
REMAINING_BLOCKERS=frozen 16-entry pool exhausted; executable LUNA exit and independent statistical evidence unavailable
```

## Presná príčina a audit starého dizajnu

Pôvodný Lab má pevný plán 66 pravidiel × 14 originov. Po jeho dokončení scheduler preskakuje drahú prácu; nemá pravidlo následníckeho experimentu. Handoff bol export návrhu do budúceho ingressu, nie dôkaz prevzatia do dokončeného/sealed Phase2 cyklu. Takýto cyklus sa nemôže znovu otvoriť. Zapnutý timer preto neznamenal nové výskumné výsledky.

Starý `block_test` delí **absolútny calendar_index** 30-timi, nie dĺžku lokálneho okna. Audit presných hraníc v [legacy-calendar-alignment.json](legacy-calendar-alignment.json) preukazuje:

- 13 zo 14 testovacích okien má najviac 7 buniek, posledné má iba 4. Požiadavka 8 obsadených blokov je v nich nemožná.
- Výnimka 2024-07-01 až 2024-12-31 začína na offsete 29. Dve čiastočné hraničné bunky dávajú **8** buniek; osem obsadených blokov je teoreticky možné, skutočný maximálny počet bol 4. Preto samotné `ceil(184/30)` nie je správny všeobecný dôkaz nemožnosti.
- Aj pri dokonale priaznivých znamienkach vo všetkých 8 bunkách je dolná hranica exact p = 1/256 = 0.00390625, výrazne nad pridelenou lifetime alpha. **Žiadne staré testovacie okno nemohlo splniť celý štatistický PASS.**
- Staré train okná občas mali 8–11 obsadených blokov. Zo 1 078 volaní štatistickej funkcie bolo iba 79 p-hodnôt nenulových/ne-null; všetkých 79 malo rozlíšenie horšie než pridelená alpha. Monte Carlo vetva má navyše floor 1/4096. Staré výpočty ani prahy sa nemenia.
- **1 428** starých backtestových pokusov, **1 078** volaní inferencie a **79** informatívnych p-hodnôt sú odlišné počty. Konzervatívny starý alpha dlh 1 428 zostáva zachovaný; nové backtestové výpočty už nie sú prezentované ako samostatné štatistické testy.

[legacy-design-audit.json](legacy-design-audit.json) dokladá aj tranzitívny most: momentum s horizon 7/14 spája 1 715 triggerov do jedného **344-dňového** train clusteru. Pri testoch boli tiež clustre takmer cez celý polrok. Pôvodné označenie „independent_events“ nie je dôkaz nezávislosti.

## SOURCE OF TRUTH a presný kontraktový dopad

Klasifikácia **B/C/D**. Najprv vznikol a prešiel validátorom `source_of_truth/discovery_evolution_contract_v2.json`, až potom jeho konzumenti. Staré kontrakty, engine, frozen výsledky a prahy sú nezmenené.

Nový experiment `discovery_evolution_v2_20261009` určuje train 2020-01-01 až 2021-12-17, 14-dňový purge a test 2022-01-01 až 2026-09-25. Development cutoff a sealed interval 2026-09-27 až 2027-09-26 zostávajú zachované. Všetka história je už videný development.

Udalosť je kauzálny false→true onset aktíva po dvoch oprávnených baroch. Onsety iných aktív v pevnom intervale od prvého onsetu do `first+horizon` sa združia; tento interval sa ďalšími triggermi nepredlžuje. Sú to **jednotky výskytu**, nie nezávislé štatistické vzorky. Inferencia agreguje aktíva do spoločného portfólia a až potom do spoločných kalendárnych blokov.

Primárny endpoint je znamienko 30-dňovej sumy rozdielov costed portfolio log-return oproti BTC_HALF. Medzi blokmi je 14 dní. Exact jednostranný binomial sign test vylučuje numerické ties; vyžaduje minimálne 30 nonzero blokov. Pred prvým backtestom kandidáta sa rezervuje jedna alpha pozícia, aj pri invalid/insufficient výsledku. Backtesty, kontrola a stress výpočty majú oddelené počítadlá. [Definícia sign testu: NIST](https://www.itl.nist.gov/div898/software/dataplot/refman1/auxillar/signtest.htm).

Zmrazený [statistical-design.json](statistical-design.json) obsahuje výpočet pred výsledkami: 1 729 dní, 39 celých blokov; posledná plánovaná alpha na indexe 1 444 = 2.3962656595960855e-08; floor pri 30 blokoch = 9.313225746154785e-10, pri 39 = 1.8189894035458565e-12. Pri plnom pokrytí treba aspoň **36/39** kladných blokov. Power pri skutočnej pravdepodobnosti kladného bloku 0.8 je len **3.32 %**, pri 0.9 **44.37 %**, pri 0.95 **87.09 %**. Slabé efekty majú nízku rozlišovaciu schopnosť; požiadavky neboli znížené na výrobu PASS.

Vnútrobloková a súčasná závislosť aktív môže byť ľubovoľná. Časová nezávislosť férových znamienok medzi blokmi je **podmienený, neoverený null**. Samotný 14-dňový gap nezabezpečuje nezávislosť finančných režimov. Žiadna historická p-hodnota neudeľuje produkčnú autoritu alebo potvrdenie kandidáta. Všetkých 16 aktuálnych p-hodnôt bolo ≥ 0.5.

## Outbox, deduplikácia a následníci

Starý outbox: **154 odovzdaní, 62 unikátnych hypotéz, 92 opakovaných odovzdaní, 5 unikátnych návrhov génov**. Všetkých päť už existovalo vo výskumnej histórii. Deduplikácia číta 39 996 legacy v1 a 515 v2 registrácií; union obsahuje **40 172** normalizovaných génov. J/L/M/N priestory sú vyčerpané. V K bolo skúšaných 20 996 z 54 880 génov.

Pred novými výsledkami bol zmrazený pool 16 globálne nových K génov, odvodených od mechanizmov prior-cutoff outbox návrhov a 16 rozdielnych hypotéz `bounded_onset_v2`. Je to explicitný mechanizmom inšpirovaný most do **existujúceho** autorizovaného K schema, nie tvrdenie ekvivalencie s M/L/N/J pravidlom. Root receipt, pôvodná hypotéza, cutoff, discovery hash a normalizovaný gene ID sú uložené v lineage. Staré gény sa nepočítajú ako nový pokrok; verzia udalosti skutočne mení spôsob merania, ale neposkytuje nové nezávislé dáta.

Každý batch má dva nepoužité členy poolu a vlastný zmrazený hash. Po dvoch feedbackoch sa uzavrie a ďalšia automatická aktivácia zmrazí následníka. Poradie používa iba predchádzajúci **train** MDD/invalid receipt a train sparse episodes; test ani stress skóre sa do poradia nepoužíva. Hashy predchádzajúceho feedbacku sú priamo vo frozen následníkovi. Jedna aktivácia hodnotí jeden kandidát; error receipt jedného kandidáta neblokuje ostatných.

Výsledné počty sú **16 unikátnych discovery hypotéz, 16 prijatých génov, 16 reálne hodnotených kandidátov, 65 výpočtov** (4 na kandidáta + jedna spoločná kontrola), **16 primárnych p-hodnôt**. Alpha index je 1 444. Nové API volania = **0**, celoživotne ostáva 14 volaní / 42 953 tokenov, s nezmenenými capmi 14 / 112 000 / 0.20 USD.

Experiment má vopred stanovený cap 16 kandidátov / 8 batchov. Po jeho dokončení hlási `IDLE_NO_NEW_WORK` a neopakuje hodnotenia. **Širší K priestor nie je vyčerpaný:** ešte 33 868 génov ostáva mimo tohto zmrazeného poolu. Rozšírenie poolu by vyžadovalo nový vopred zmrazený kontrakt/budget a obsahovo nové hypotézy; aktuálny proces ho potichu nerozširuje. Nejde o tvrdenie nepretržitej 24/7 evolúcie.

## LUNA a pravidlá dát

[luna-source-audit.json](luna-source-audit.json) dokladá [oficiálny Binance USDT minute archive](https://data.binance.vision/data/spot/daily/klines/LUNAUSDT/1m/LUNAUSDT-1m-2022-05-13.zip). SHA256 `b3e67cd58c4da5348234ef983bf52795fdf8dedb1bfd45485cea4c90dd5c48c4` súhlasí s publikovaným checksumom; 40 riadkov pokrýva 00:00–00:39 UTC. [Binance oznámenie](https://www.binance.com/en-TR/support/announcement/detail/514e0ba636e843bda47d5d740b7dadf4) uvádza halt 00:40 UTC. Oznámenie je dodatočne aktualizovaná stránka, nie nemenný dôkaz okamžitej publikácie.

Zmrazený spot daily zdroj má pre May13 agregovaný candle, ale jeho časový interval presahuje halt identity segmentu. Nedá sa preto použiť ako plne oprávnený denný bar pôvodnej identity. Minútové pozorovania samotné nedokazujú realizovateľný fill o 00:29 pre danú veľkosť, latency/depth/slippage ani post-halt valuáciu. Pôvodný daily engine intraday výstup nepredstavuje. **Pôvodný výsledok ostáva UNDEFINED_INVALID**, bez spájania LUNA identít, fiktívnej ceny alebo bezstratového CASH.

Nový experiment vopred karantenizuje všetky nevyriešené `@` identity segmenty ako deklarovanú universe restriction, nie certifikovanú PIT úplnosť. Eligibility vyžaduje 61 súvislých validných OHLCV barov. Chýbajúci held price alebo chybný držaný candle invaliduje celý kandidát; jeho terminal receipt ponechá ostatné kandidáty spracovateľné. Ani tento experiment netvrdí oprávnený vykonateľný LUNA výstup.

## Runtime dôkazy a obnova

Read-only preflight je [predeployment-readonly.json](predeployment-readonly.json). Nasadenie vytvorilo len nové `trendatlas-discovery-evolution.service/.timer`, používateľa `trendatlas-evolution`, release, `/var/lib/trendatlas-discovery-evolution` a vlastné logy. Worker má PrivateNetwork, len AF_UNIX, žiadne LoadCredential, 60 % CPU, 3 GiB pamäte, 180 s timeout a zápis len do vlastného state/log adresára. Predecessor state, production, Pi, LeadPilot, Docker a credential adresáre sú InaccessiblePaths.

Prvý nový release `3e303e4a499a98ab` narazil pred prvým batchom na native read-only array pri in-place maske. Nevznikli žiadne výsledky ani rezervácie. Opravený release **`9123165b53ae37e4`** používa samostatnú dataclass kópiu masky. Starý release, bootstrap aj checkpoint ostali zachované. Append-only `pre_result_runtime_repair_frozen` uchováva starú väzbu a zmrazuje novú implementáciu; endpointy/pool/dáta sa nemenili. Takáto oprava je odmietnutá po prvom frozen batchi.

Skutočný SIGKILL 2026-10-09 05:08:32 UTC prerušil rezervovaný backtest **attempt 1 / key `efb4e3746744bfd487e72436197f877d192a218e8cabc533aa432b573c614f3a`**. Systemd automaticky obnovil prácu. [runtime-04-final-proof.json](runtime-04-final-proof.json) preukazuje dokončenie **toho istého attempt ID**, presne jednu rezerváciu kľúča a zachovaný pre-kill hash reťazca. Alpha rezervácia sa nezdvojila.

Automatický batch 1 bol zmrazený 05:08:31 UTC, batch 2 **05:12:34 UTC** už s dvoma predchádzajúcimi feedback hashmi; ďalšie batche vznikali až do batchu 8 o 05:31:20 UTC. Posledný progres je 05:33:03 UTC. Celá slučka prebehla na systemd bez lokálneho notebookového procesu alebo ručného spustenia jednotlivých hodnotení. Dôkazy obsahujú konkrétne discovery/inbox/candidate/feedback/close eventy a časy.

[runtime-02-resumed.json](runtime-02-resumed.json) a [runtime-03-automatic-progress.json](runtime-03-automatic-progress.json) ukazujú progres medzi aktiváciami. [runtime-05-idle-check.json](runtime-05-idle-check.json) preukazuje pri neskoršej aktivácii nemenné počítadlá, hash aj last progress. Hash chain PASS; všetkých deväť pôvodných v2 table hashes a pôvodný Lab final hash zostali identické, engine byte-for-byte nezmenený, nulový prienik nových génov s historickým unionom.

## FILES READ

V povinnom poradí: `source_of_truth/README.md`, `master_state.md`, `chat_roles.md`, `project_truth.json`, `export_contract.json`, `paths_registry.json`, `current_issues.md`; `canonical/script_registry.json`, `output_registry.json`, `registry_workflow.md`; scheduler authority dodatok `source_of_truth/pi_codex_runtime_workflow.md`. Ďalej pôvodné Phase2 development/v2/recovery a Lab/reporting kontrakty; `research/phase2_v2/{market,engine,inputs,contract,runtime,broker}.py`; `research/anomaly_lab/{contract,rules,statistics,discovery,runtime,handoff,audit,deploy}.py`; relevantné existujúce testy a read-only VPS frozen state/input manifests. Nový kontrakt, všetky nové moduly/testy a uvedené dôkazové JSON. Oprávnené verejné Binance/NIST zdroje sú linkované vyššie.

## Regresie a validácia

`tests/test_discovery_evolution.py` pridáva 14 zmysluplných regresií: presné hraničné bloky a power; nemožné/oslabené okná a seal/API/debt reset; exact p-resolution; no-edge spoločné blokové znamienka; bounded episode bez tranzitívneho mosta; prior-only/global dedup a idle; skutočný nezmenený K engine; crash/reuse rezervácií; celá inbox/backtest/feedback/successor slučka a immutable idle; izolácia LUNA chyby kandidáta; odmietnutie zmenenej frozen väzby; systemd authority isolation; native read-only maska; iba pre-result append-refreeze.

- `python -B -m research.discovery_evolution.contract` — PASS pred implementáciou/nasadením.
- `python -B -m unittest tests.test_discovery_evolution tests.test_anomaly_lab tests.test_anomaly_lab_reporting tests.test_phase2_v2 tests.test_phase2_v2_continuation -q` — 57 tests, PASS.
- VPS bez broker credential: 14 tests, PASS; pôvodná native suite aj finálny hraničný calendar test. `systemd-analyze verify` — PASS; nesúvisiace distribučné xfs CPUAccounting warningy.
- Skutočné native backtesty, SIGKILL recovery, osem automatických batchov, následné idle, predecessor hash equality — PASS podľa uložených dôkazov.
- `git diff --check`; explicitný scoped add; staged diff/source-byte kontrola; remote branch hash po push — výsledok v Git potvrdení tohto reportu.

Forbidden old path checked: bez editácie/znovuotvorenia `/var/lib/trendatlas-anomaly-lab`, legacy/v2 ledgerov a sealed cyklu; bez zmeny `research/phase2_v2`, `research/anomaly_lab`, starých kontraktov, `outputs/*`, `data/*`, produkcie, účtu, objednávok, dashboardu, LeadPilot alebo Pi. Runtime nového workera má uvedené staré state/authority adresáre zakázané.

## Presné zmenené súbory a git add list

`git add --` s presne týmto zoznamom (žiadne generované outputs/data):

```text
canonical/output_registry.json
canonical/script_registry.json
source_of_truth/README.md
source_of_truth/master_state.md
source_of_truth/current_issues.md
source_of_truth/paths_registry.json
source_of_truth/discovery_evolution_contract_v2.json
research/discovery_evolution/__init__.py
research/discovery_evolution/contract.py
research/discovery_evolution/statistics.py
research/discovery_evolution/discovery.py
research/discovery_evolution/pool.py
research/discovery_evolution/runtime.py
research/discovery_evolution/entry.py
research/discovery_evolution/deploy.py
tests/test_discovery_evolution.py
docs/discovery-evolution-20261008/REPORT.md
docs/discovery-evolution-20261008/statistical-design.json
docs/discovery-evolution-20261008/luna-source-audit.json
docs/discovery-evolution-20261008/predeployment-readonly.json
docs/discovery-evolution-20261008/legacy-design-audit.json
docs/discovery-evolution-20261008/legacy-calendar-alignment.json
docs/discovery-evolution-20261008/runtime-01-interruption.json
docs/discovery-evolution-20261008/runtime-02-resumed.json
docs/discovery-evolution-20261008/runtime-03-automatic-progress.json
docs/discovery-evolution-20261008/runtime-04-final-proof.json
docs/discovery-evolution-20261008/runtime-05-idle-check.json
```

Commit message: `Complete isolated discovery evolution successor loop with frozen statistics and recovery`.
Commit hash: identifikátor obsahujúceho commitu sa uvedie v záverečnom výstupe a overí cez `git ls-remote origin refs/heads/codex/anomaly-discovery-lab-20261008` (nevkladá sa self-referential hash do commitu).
