# Priebežný TrendAtlas discovery/evolution výskum

## Presná príčina

Commit `6fad5320192adb90adaf271b5c2dfce6e29896dd` správne implementoval konečný experiment: `pool_max=16`, `cycles_max=8`, `new_api_calls_allowed=0`. Po ôsmich batchoch preto nemal oprávnenú ďalšiu prácu. Zapnutý timer kontroloval stav, ale neobjavoval nové hypotézy. [Read-only preflight](preflight.json) potvrdil 16 dokončených kandidátov, 65 backtestových výpočtov, 16 p-hodnôt a alpha index 1444. V širšom K priestore zostávalo 33 868 nepoužitých konfigurácií.

Nový scheduler nemá celoživotný limit počtu batchov ani veľkosti poolu. Každý batch má štyri globálne nové konfigurácie; pred jeho výpočtami sa zmrazí samostatný plán. Prevádzkové limity sa obnovujú, vedecká a výberová história zostáva trvalá.

## SOURCE OF TRUTH a kontraktový dopad

Klasifikácia **B/C/D**. Najskôr vznikol a prešiel validátorom `source_of_truth/continuous_research_contract_v1.json`, až potom implementácia. Nemení produkčnú stratégiu, exporty, účet, objednávky ani pôvodné frozen kontrakty.

- Train: 2020-01-01 až 2020-12-17. Validation: 2021-01-01 až 2021-12-17. Diagnostika: 2022-01-01 až 2026-09-25. Medzi oknami je aspoň 14 dní. Sealed 2026-09-27 až 2027-09-26 sa nečíta.
- Každý batch zmrazí konkrétne gény, pravidlá, pôvod, rodičovské feedback hashe, okná, frekvenčnú metódu, alpha indexy a výpočet rozlíšenia/power pred výsledkami.
- Gene identity a configuration-hypothesis identity sú globálne a nezávislé od slovného opisu, rodiča či verzie. Na začiatku sa importovalo 40 188 historických gene IDs. Samotná zmena parametrov sa označuje ako nová konfigurácia. Všetkých 66 primitívnych pravidiel už bolo videných; počet potvrdených trhových objavov ostáva nula.
- Jedna automatická aktivácia spracuje jedného kandidáta. Prevádzkový limit 128 nových kandidátov za deň chráni CPU/disk; po polnoci Europe/Paris sa obnoví. Rozpracovaný kandidát môže dokončiť checkpoint. Lifetime alpha rezervácie, deduplikácia, počty a evidencia kontaminácie sa nikdy neresetujú.
- Nový spoločný API účet má 24 transportných pokusov/deň, 6 500 input a 1 500 output tokenov/request, 0,25 USD/deň a 5 USD/mesiac. Každý transport vrátane retry rezervuje plnú konzervatívnu maximálnu cenu. Neistý prerušený transport sa znova neposiela. Starých 14 volaní / 42 953 tokenov zostáva v pôvodnom uzavretom účte.
- Pri API limite alebo nedostupnom overení ceny sa pokračuje pripravenými AI alebo jednoznačne označenými lokálnymi konfiguráciami. Pri dennom CPU limite je stav WAIT; pri skutočne vyčerpanom celom oprávnenom priestore IDLE_NO_AUTHORIZED_NOVEL_WORK.

## AI spätná väzba a komunikačná oprava

Platený broker dostáva najviac dvoch rodičov, povolené train/validation metriky, frekvenciu do 2021-12-17, agregované počty a najviac dva príklady odmietnutých génov. Celé histórie, diagnostické výsledky ani rastúce zoznamy hashov sa do API neposielajú. Parent ranking používa len train/validation. DeepSeek návrh musí prejsť presnou deklaratívnou schémou a globálnou deduplikáciou; raw odpoveď sa zachová. Deterministickí susedia majú LOCAL pôvod, nikdy AI_AUTHORED.

Prvé dve reálne odpovede DeepSeek Flash neobsahovali povinné `evaluation`; druhá pridala nepovolený top-level `type`. Obe ostávajú odmietnuté a započítané do rozpočtu. Prvá tiež obsahovala príliš dlhé zdôvodnenia. Nevznikol z nich prijatý AI kandidát.

Samostatný `continuous_research_protocol_v2.json` následne vopred zmrazil len formát budúcich požiadaviek: presný JSON príklad a explicitné limity polí. [Oficiálna dokumentácia JSON mode](https://api-docs.deepseek.com/guides/json_mode/) odporúča príklad požadovaného formátu. Pôvodný strict parser, vedecké plány a engine zostali byte-identické. Dva pôvodné request IDs stále používajú pôvodný wire builder. Do oboch ledgerov pribudol len nemenný hash nového protokolu; počítadlá a rezervácie sa zachovali. [Protocol manifest](protocol-deployment.json) eviduje zmenu pri piatich dokončených kandidátoch a dvoch API pokusoch.

Prvý pokus o inštaláciu protokolu narazil na chýbajúci adresár `scripts/` v minimálnom release. Zastavil sa pred zmenou ledgerov a pred použitím protokolu. Oprava vytvárania rodičovských adresárov má regresiu; neúspešný release ostal zachovaný. Aktívny obsahovo adresovaný release je `/opt/trendatlas-research/continuous/releases/200a81ce82b6b0c7`.

[Oficiálny cenník](https://api-docs.deepseek.com/quick_start/pricing/) sa overuje pred platenou prácou a najviac hodinu sa cacheuje. Používa sa vyššia peak sadzba; zachováva sa hash získaného cenníka. Pozorovaná plná rezervácia je 0,00375 USD/request. Rozpočtové zostatky vyjadrujú konzervatívne rezervácie, nie skutočnú faktúru. Maximálny vstup sa konzervatívne ohraničuje počtom ASCII wire bytes plus 256 framing tokenov a následne sa kontroluje provider usage.

## Štatistická poctivosť a LUNA

[Predchádzajúci presný audit](../discovery-evolution-20261008/REPORT.md) zostáva platný: 13 starých testovacích okien nemá osem absolútnych 30-dňových buniek; výnimka 2024 H2 ich môže mať osem kvôli čiastočným hraniciam, ale ani jej najlepšie exact p=1/256 nedosiahne pridelenú alpha. Tranzitívny clustering spájal udalosti do 344-dňového clusteru. Staré výsledky ani prahy sa nemenili.

Nový výskum zachováva bounded-onset epizódy s pevným koncom a spoločné portfóliové kalendárne bloky. Epizódy sa netvária ako nezávislé pozorovania. Testovacie okno má 1 729 dní, 39 plných 30-dňových blokov oddelených 14 dňami. Minimum je 30 nonzero blokov. Pri batchi 1, alpha indexe 1448, je alpha 2,383049464e-08, najmenšie p pri 39 blokoch 1,818989404e-12 a kritická hranica 36/39 pozitívnych blokov. Power pri pravdepodobnosti pozitívneho bloku 0,8 je 3,32 %, pri 0,9 44,37 %, pri 0,95 87,09 %. Rozlíšenie sa prepočíta pri každom novom batchi; lifetime alpha sa nesmie resetovať.

Časová nezávislosť znamienok nie je dokázaná. Opakovaná selection na validation a prezeranie diagnostických testov sú development kontaminácia. P-hodnoty sú podmienené diagnostiky a **nikdy nepotvrdzujú obchodného kandidáta**. Každý kandidát rezervuje jeden vedecký pokus, aj pri neplatnom výsledku; jeho päť backtestov a spoločná kontrola sa počítajú osobitne.

Pôvodný LUNA výsledok ostáva UNDEFINED_INVALID. Predchádzajúci checksum-verified minútový archív nedokázal realizovateľný exit pôvodného daily modelu. Nový experiment preberá vopred deklarovanú karanténu nevyriešených identít a 61 súvislých validných barov; nevymýšľa cenu, fill ani bezstratový CASH. Chyba jedného kandidáta neblokuje ostatných. Úplnosť point-in-time universe stále nie je certifikovaná.

## Izolácia, automatické pokračovanie a obnova

Vytvorené sú iba research worker/broker služby a timery, vlastní používatelia, release a `/var/lib/trendatlas-continuous-research` plus `/var/lib/trendatlas-continuous-mailbox`. Worker má PrivateNetwork, AF_UNIX, žiadne credentials, CPU 60 %, memory 3 GiB, timeout 240 s a restart-on-failure. Broker má jediný systemd credential pre DeepSeek, bez prístupu k research dátam a starým stavom. Oba majú zakázané produkčné, Pi, LeadPilot, Docker a credential-store cesty; zápisy sú obmedzené na vlastné research adresáre. Pôvodné services a frozen experimenty sa nemenili.

Skutočný SIGKILL 19:04:30.254670 UTC prerušil training attempt **17**, key `517caabfc762c5120b31a930a78af11c10d05a88d0321142aaa8334af3045132`, scientific reservation **4**, lifetime alpha **1448**. Systemd sám obnovil proces a ten istý pokus sa dokončil 19:05:39.362942 UTC. [Záznam prerušenia](interruption.json) a [následný úplný audit](runtime-first.json) zachovávajú PID, pôvodný event hash, rezerváciu aj hotový backtest. Nevznikol druhý vedecký ani backtestový pokus pre tento kľúč.

Prvý batch sa uzavrel po štyroch feedbackoch; druhý vznikol automaticky s ich hashmi. Všetky hodnotenia spúšťa systemd na VPS. Lokálny notebook slúžil na read-only audit a jednorazovú autorizovanú inštaláciu/interrupt test, nie na spúšťanie jednotlivých kandidátov.

Natívne sa odhalila aj samostatná prevádzková chyba zdieľaného API ledgeru: SQLite vytvorilo hlavný súbor ako 0640. Read-only worker pod iným UID potom vytváral 0640 WAL/SHM súbory, do ktorých broker nemohol zapisovať. Súbežný audit mohol predĺžiť ich životnosť. Nešlo o nový API transport: zlyhanie nastalo už pri rezervácii. `continuous_research_observer_contract_v1.json` a `fix_continuous_research_storage.py` nastavili iba nový spoločný API ledger a existujúce sidecary na 0660 v pôvodnej skupine; broker túto vlastnosť udržiava cez ExecStartPre. Pozorovací proces používa tú istú skupinu a umask 0007 pred mode=ro pripojeniami. [Oprava oprávnení](storage-repair.json) nemení SQL dáta, vlastníkov, staré cesty ani budget. [Native regresia](observer-regression.txt) pod dvoma skutočnými research používateľmi reprodukovala pôvodné zlyhanie a následne preukázala súbežný zápis s opravenými oprávneniami. [Prevádzková kontrola](operations-proof.json) obsahuje skutočné jednotky, režimy súborov a log po oprave.

## Regresie a validácia

- `python -B -m research.continuous_research.contract`: PASS pred implementáciou/nasadením.
- Pôvodná relevantná sada: `python -B -m unittest tests.test_continuous_research tests.test_discovery_evolution tests.test_anomaly_lab tests.test_anomaly_lab_reporting tests.test_phase2_v2 tests.test_phase2_v2_continuation -q`: **75 PASS**.
- Nový runtime má 18 regresií; natívne na VPS **18 PASS**. Pokrývajú pokračovanie cez deviaty batch/36 kandidátov, globálnu deduplikáciu, obsahové hranice AI, súbežných 40 rezervácií s limitom 24, denné/mesačné obnovenie bez resetu, retry, uncertain transport, idempotentný admission, crash/resume, izoláciu chyby LUNA, úplné vyčerpanie, tarify, nezmenený engine a systemd izoláciu.
- Komunikačný protokol má päť regresií; lokálne aj natívne **5 PASS**. Overujú zachovanie pôvodného wire, nový príklad/token bound, naďalej odmietnutú chybnú native shape, presnú AI recepciu/backtest, frozen binding a tvorbu chýbajúcich adresárov balíka.
- Kombinovaná aktuálna sada `python -B -m unittest tests.test_continuous_research tests.test_continuous_research_protocol -q`: **23 PASS**, 31,955 s. Native cross-user observer/storage test: **1 PASS**, 0,200 s; na Windows sa táto systémová regresia nepredstiera.
- `systemd-analyze verify`: PASS pre nové research units; vypísal iba nesúvisiace existujúce xfs CPUAccounting warnings.
- `.gitattributes` zachováva presné bajty nových frozen research zdrojov pri Windows Git checkoutoch. SHA256 staged Git blobov súhlasí so všetkými 15 code/protocol hashmi nasadených manifestov. Pôvodné moduly a kontrakty sa nemenili.

## FILES READ

V povinnom poradí: `source_of_truth/README.md`, `master_state.md`, `chat_roles.md`, `project_truth.json`, `export_contract.json`, `paths_registry.json`, `current_issues.md`; `canonical/script_registry.json`, `output_registry.json`, `registry_workflow.md`; potom `source_of_truth/pi_codex_runtime_workflow.md`. Ďalej Phase2 development/v2, anomaly Lab a discovery/evolution kontrakty; relevantné `research/phase2_v2`, `research/anomaly_lab`, `research/discovery_evolution` moduly a testy; nový kontrakt, všetky nové moduly/testy; read-only VPS ledgery, manifests, service stav a provider receipts; vyššie uvedené oficiálne DeepSeek zdroje.

## Forbidden old path checked

Žiadna zmena produkčného kódu/kontraktu/exportu, účtu, live order, LeadPilot, Pi ani frontendu. Žiadny full refresh, žiadne manuálne authority snapshots a žiadny commit `outputs/*` alebo `data/*`. Staré Lab, finite successor a Phase2 tabuľky/hashy sa kontrolujú proti preflightu. Pôvodná neplatná LUNA kniha, starý exhausted API budget a sealed cyklus sa neotvárajú.

## Záverečný runtime dôkaz

Audit v [runtime-final.json](runtime-final.json) bol otvorený 2026-10-09T19:30:59.654660+00:00 UTC; obsahuje 20 unikátnych dokončených kandidátov, z toho 2 AI_AUTHORED, 101 hotových backtestových výpočtov a 20 p-hodnôt. Vzniklo 6 batchov, 5 bolo uzavretých a aktívny bol batch [6]. To je pozorovaný pokrok medzi nezávislými systemd invocation IDs, nie odhad zo zapnutých timerov.

Reálny provider request `78621cb9-0b8b-457f-8733-81ae1c2a2d95` vrátil 1 610 input / 506 output tokenov. Jeho dve prijaté konfigurácie majú gene IDs `426750cc7e4ec7a0a9d7edd8dc2e6ca9c5ab3b37b28f13e68c21227788cb1b36` a `6bda3e379a9e7f5bc3cdea3edc9310f23dd889fdae112179419fecf1ae1134d7`. Každá prešla frozen batch 4 → discovery receipt → inbox → candidate → päť natívnych backtestov → feedback. Batch 5 bol automaticky zmrazený 19:25:22.673092 UTC a obsahuje oba ich feedback hashe. AI výsledky vstúpili do rankingového poolu; ďalšia kompaktná API požiadavka vybrala iných lepších/nedávnych rodičov. Netvrdíme, že API dostáva všetky výsledky.

Zachovaná je jedna nová skutočná frekvenčná kalkulácia; zhodné už zmrazené frekvencie sa používajú z cache. Šesť platených pokusov obsahuje tri odmietnuté obálky, dva prijaté AI návrhy a štyri samostatné duplicate-gene odmietnutia. Duplicity sa nepočítajú ako nové kandidáty ani nový objav. API volanie po oprave shared WAL úspešne dokončil samotný timer; [validation.json](validation.json) a `broker.results` nesú jeho dôkaz.

Stav pri tomto audite: DISCOVERY_COMPUTING=false, EVOLUTION_COMPUTING=false; worker mal overený živý PID vo fáze PREPARING_MARKET. Dovtedy dokončené výpočty a nasledujúce aktivácie sú explicitne v `automatic_activations`. Aktívny batch sa po štyroch feedbackoch automaticky uzavrie, pripraví bounded AI požiadavku a ďalšia aktivácia zmrazí nasledovníka.

API pokusy: 6, zostáva 18/deň; konzervatívny zostatok 0.22750 USD/deň a 4.97750 USD/mesiac. Lifetime alpha index: 1464. Žiadny kandidát nemá obchodné potvrdenie. Prevádzkové blokery v overenom okamihu: žiadne. Obmedzenia vedeckého tvrdenia: časová nezávislosť, videný development, PIT úplnosť a pôvodný LUNA exit zostávajú nevyriešené.

Aj nový protokol môže dostať neplatnú odpoveď: šiesta mala critique dlhú 647 znakov pri zmrazenom maxime 600. Bola odmietnutá bez spätnej úpravy alebo presunutia jej génov do lokálneho pôvodu. Prevádzka ďalej spracúva oprávnené lokálne úlohy.

## Presné zmenené súbory a git add

Úplný explicitný zoznam je [git-add.txt](git-add.txt). Obsahuje iba nové research moduly, tri nové research kontrakty, ich testy, tri izolované deployment/audit nástroje, výskumné registry/poznámky a tento dôkazový balík. Žiadny pôvodný engine, frozen kontrakt, produkčný súbor, `outputs/*` ani `data/*` nie je v indexe.

```powershell
$paths = Get-Content docs/continuous-research-20261009/git-add.txt
git add -- $paths
git diff --cached --check
```

Commit message: `feat(research): continue discovery with shared AI budgets and frozen batches`

Commit hash: identifikátor commitu obsahujúceho tento report je uvedený v záverečnej odpovedi; lokálne ho presne vráti `git log -1 --format=%H -- docs/continuous-research-20261009/REPORT.md`.
