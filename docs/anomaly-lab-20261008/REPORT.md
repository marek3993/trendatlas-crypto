# TrendAtlas Anomaly Discovery Lab — nasadenie a výsledky 2026-10-08

Implementácia je nasadená na existujúcom VPS. Všetkých 14 vopred zmrazených
vývojových období sa dokončilo automaticky cez systemd; posledné o 19:34:32 UTC.
Report sa následne automaticky aktualizoval o 19:34:39 UTC. Finálny stav je
`EXHAUSTED`: plánovaný rozpočet sa vyčerpal, oba timery zostávajú povolené a
ExecCondition preskakuje ďalšiu drahú prácu. Nepotrebuje notebook ani otvorený Codex.

Výsledky: 66 normalizovaných hypotéz, 924 dokončených tréningových vyhodnotení,
504 nominálnych/stresových/kontrolných portfóliových kníh, 154 zmrazených výberov,
154 odovzdaní hypotéz a 1 428 trvalo evidovaných pokusov. DeepSeek vykonal
14 volaní s 42 953 provider-native tokenmi. Nejde o údaj o fakturovanej cene.

Všetky reportované asociácie zostali `INSUFFICIENT_EVIDENCE`; žiadna z 11 rodín
neprešla všetkými ekonomickými podmienkami. Žiadny potvrdený obchodný kandidát
nevznikol. Tieto výsledky nesmú meniť produkčnú stratégiu alebo účet.

## FILES READ

Povinné súbory boli čítané v predpísanom poradí, najprv v pôvodnom pracovnom
adresári, potom bol skontrolovaný novší stav čistej Phase2 vetvy:

1. `AGENTS.md` a vložené zadanie používateľa.
2. `source_of_truth/README.md`
3. `source_of_truth/master_state.md`
4. `source_of_truth/chat_roles.md`
5. `source_of_truth/project_truth.json`
6. `source_of_truth/export_contract.json`
7. `source_of_truth/paths_registry.json`
8. `source_of_truth/current_issues.md`
9. `canonical/script_registry.json`
10. `canonical/output_registry.json`
11. `canonical/registry_workflow.md`
12. `source_of_truth/pi_codex_runtime_workflow.md`

Ďalšie prečítané kontrakty a implementácia:

- `source_of_truth/phase2_v2_contract.json`
- `source_of_truth/phase2_v2_recovery_contract.json`
- `source_of_truth/phase2_development_contract.json`
- `source_of_truth/phase2_broker_policy.json`
- `C:/Users/benda/Desktop/market_regime_v1/source_of_truth/research_objectives_contract.json`
  — existujúci lokálny výskumný kontrakt; nebol skopírovaný ani upravený.
- `research/phase2_v2/README.md`, `contract.py`, `engine.py`, `market.py`,
  `runtime.py`, `inputs.py`, `freeze_inputs.py`, `collect_inputs.py`, `broker.py`,
  `compact.py`, `deploy.py`, `deploy_continuation.py`.
- `research/phase2_continuous/README.md`, `research/phase2_continuous/broker.py`.
- `tests/test_phase2_v2.py`, `tests/test_phase2_v2_continuation.py`.
- `docs/phase2-v2-20261005/REPORT.md`,
  `docs/phase2-v2-recovery-20261006/REPORT.md` a relevantné checkpointy.
- Nové Lab kontrakty, všetky moduly v `research/anomaly_lab/`, reportovací
  consumer, jeho deploy skript a obe nové testovacie sady.
- Pri záverečnej kontrole testy source-of-truth/registrov uvedené nižšie.

Na VPS sa čítali skutočné systemd jednotky, aktuálne runtime statusy, SQLite
počty/metadáta, zmrazený vstupný manifest a zdrojové hashe. Starý report nebol
použitý ako dôkaz súčasného behu. Trading secrets neboli čítané ani vypísané.

## SOURCE OF TRUTH

- Časový rozsah určuje autorizovaný `phase2_v2_contract.json`:
  development **2018-05-05 až 2026-09-25**, 2026-09-26 vylúčený,
  prospective **2026-09-27 až 2027-09-26 LOCKED**, forward 2027 SEALED.
- Nový samostatný experiment určuje `source_of_truth/anomaly_lab_contract.json`.
  Klasifikácia B/C/D, explicitné používateľské implement/test/deploy oprávnenie,
  `orders_allowed=false`, `production_writes_allowed=false`, `promotion_allowed=false`.
- Opravu významu reportov určuje samostatný
  `source_of_truth/anomaly_lab_reporting_contract.json`, klasifikácia B.
  Nesmie meniť zmrazený experiment ani evaluator.
- Lab reporty a hypotézy sú vývojové výskumné artefakty, nie oficiálna obchodná
  pravda, stav peňaženky, skutočné PnL alebo nezávislý historický holdout.

## Exact root cause

Chýbal samostatný systém, ktorý by nad existujúcim engine meral frekvenciu
globálne zoskupených udalostí, oddelil následný pohyb od ekonomiky, evidoval
celoživotné pokusy a automaticky odovzdával deklaratívne hypotézy. Pôvodný
pracovný adresár obsahoval nesúvisiace rozpracované zmeny a jeho staršia správa
o aktívnej continuous v1 evolúcii nebola aktuálna.

Živý VPS stav potvrdil, že v2 po recovery už dokončila 14 origins a 1 854
vyhodnotení. Pôvodná vybraná kontinuálna kniha zostáva `UNDEFINED_INVALID` pre
chýbajúcu realizovateľnú cenu pôvodnej LUNA 2022-05-13. Štyri platné prefixové
foldy a desať terminal/not-evaluable receipts sa nezamieňajú za platný celý výsledok.

Pri kontrole prvých Lab výsledkov sa navyše ukázalo, že bootstrap pri nulových
udalostiach môže vrátiť zavádzajúce `[0,0]`. Oprava bola urobená samostatným
read-only consumerom: pri menej než 20 nezávislých udalostiach report zobrazuje
`null` a `INSUFFICIENT_EVIDENCE`. Pôvodné experimentálne intervaly a výsledky sa
neprepisovali. Consumer tiež nezobrazuje neznámu cenu ako nulu a nepoužíva
portfóliový súhrn, ktorého počet období nesedí s konzistentným SQLite snapshotom.

## Exact contract impact

Pred implementáciou boli zmrazené rodiny, tri prahy, horizonty 7/14 dní,
expozícia 0.25, publication buffer, clustering, train/validation/test hranice,
náklady, susedia parametrov, null model, multiplicita, výber a rozpočty.
Zmena pridáva iba samostatný výskumný runtime, broker, výstupy a reportovanie.
Existujúci evaluator, frozen input bundle, Phase2 kontrakty, selekcie a výsledky
sa nemenia. Nepridáva sa trading allowlist ani oprávnenie obchodovať.

Použitý je existujúci `research.phase2_v2.engine.evaluate` cez jeho už existujúce
rozhranie `PRODUCTION` pre offline target map. Názov rozhrania neznamená
produkčnú autoritu. Neexistuje druhý backtest evaluator. Broker používa existujúci
Phase2 DeepSeek transport, cache, retry, rezervácie a účtovanie v oddelenom procese.

## Výpočty a praktické hranice výsledkov

Udalosti sa spájajú tranzitívne cez horizont naprieč všetkými aktívami. Sto dní
jedného trendu ani desať súčasne zasiahnutých mincí nepredstavuje sto/desať
nezávislých dôkazov. Chýbajúce oprávnené dni nepridávajú denominator a prerušujú
cluster. Príklad prvého obdobia: momentum malo 891 asset-day triggerov, ale iba
2 globálne udalosti; kompresia volatility 211 triggerov a 6 udalostí.

Ukladajú sa oprávnené asset/calendar dni, podiel triggerov, ročné rozdelenia,
medzery a ich rozptyl, trvanie, reprezentatívne aktíva/režimy a pokrytie.
Pravdepodobnosť priaznivého pohybu, kvantily výnosov, MFE/MAE a historické
matched controls sú oddelené od portfóliového PnL. Rozdelenie podľa aktíva
označuje reprezentanta globálneho clusteru, nie nezávislé per-coin dôkazy.

Pred každým testovacím obdobím sa používa iba predchádzajúcich 365 dní,
dve chronologické vnútorné časti a 14-dňový purge. AI dostáva kompaktné
predchádzajúce agregáty a dôvody zlyhania, najviac 6 500 wire bytes a 1 500
output tokens. Deklaratívna schema odmieta neznáme polia a ľubovoľný kód.
Rovnaká normalizovaná hypotéza pod iným názvom sa deduplikuje.

Každá rodina prenáša skutočnú simulovanú cash/quantity/episode knihu cez všetky
obdobia. CAGR geometricky počíta celý kalendár 2020-01-01 až 2026-09-25,
vrátane CASH, strát a nákladov. Nepriemeruje krátke annualizované foldy.
Kontroly zahŕňajú BTC, historický model a CASH, 2x náklady, oneskorené vstupy,
susedné parametre, koncentráciu, odstránenie najlepšieho dňa a troch najlepších
celých uzavretých obchodov. Chýbajúca cena alebo chybná realizovaná sviečka
zneplatňuje knihu; nevyrába sa likvidácia alebo nový CASH začiatok.

Nezávislé quantity × open-gap + close-move mínus znovu zostavené náklady
prešlo pre všetkých 154 nominálnych anomaly kníh. Maximálna odchýlka NAV je
`1.7053025658242404e-13`, maximálna odchýlka nákladov `2.220446049250313e-16`.

Aj najvyšší nominálny vývojový CAGR nie je potvrdenie: take-profit context
dosiahol 21.98 %, ale MDD 41.25 %, nevyhovujúcu koncentráciu/susedov a pri
oneskorenom vstupe CAGR -0.57 %. BTC kontrola s expozíciou 0.25 mala 13.12 %,
historický model 11.19 %. Ide výlučne o daný simulovaný spot proxy experiment.
Všetky anomaly rodiny majú neúspešné ekonomické gates.

Vstupný bundle má deklarované spot quote-volume aj volume-times-close proxy;
funding, OI, likvidácie a order book sú `UNAVAILABLE`, nikdy nula. Identity
segmenty, ktoré súčasný engine nedokáže spoľahlivo vyriešiť, sú karantenizované.
Point-in-time universe, úplnosť trhu, presný historický čas publikácie a venue
certifikácia zostávajú nepotvrdené. Používa sa jeden ďalší dokončený denný bar
pred next-open fill; nie je to dôkaz skutočného historického publication timestampu.

## Multiplicita a neistota

Každý rezervovaný pokus pred výsledkom dostane trvalé `t`; nové obdobie alebo
cycle ID ho nemôže resetovať. Alpha spending je `0.05/[t(t+1)]`. Súčet ostáva
pod 0.05. Používa sa spoločný sign randomization cez 30-dňové kalendárne bloky,
s explicitným null predpokladom podmienene nezávislých symetrických block signs.
Zachováva spoločnú závislosť aktív a sériovú závislosť v bloku. Union bound
vyžaduje platné podmienené p-values; pre opakovane skúmanú finančnú históriu
a moderný LLM nie je tvrdená všeobecná FWER alebo nezávislá prediktívna záruka.

Primárny zdroj: [Sture Holm (1979), A Simple Sequentially Rejective Multiple
Test Procedure](https://www.ime.usp.br/~abe/lista/pdf4R8xPVzCnX.pdf), argument
union bound. Implementované je vyššie opísané lifetime spending rozšírenie,
nie Holm step-down. Syntetická kalibrácia pod deklarovaným no-edge null:
120 behov × 20 závislých hypotéz, 3 false-discovery runs, empirická miera 2.5 %,
Wilson 95 % interval [0.85 %, 7.09 %]. Je to kalibrácia konkrétneho null,
nie dôkaz platnosti predpokladov na trhových dátach.

Minimum je 20 udalostí/matched pairs a 8 obsadených 30-dňových blokov.
Jednotlivé polročné outer development foldy nemajú dosť kalendárneho rozsahu
na túto block podmienku; ich asociácie zostávajú popisné a nedostatočné.
Predchádzajúce tréningové okno je dlhšie. Limity a štatistická rozlišovacia
schopnosť sa po pozretí výsledkov neznižovali. Finálny report žiadnu hypotézu
neoznačuje za potvrdeného obchodného kandidáta.

## Odovzdanie Phase2

Samostatný append-only outbox obsahuje 154 presných deklaratívnych hypotéz,
rodičov, cutoff a predchádzajúce validačné dôkazy. Obsahuje aj platné návrhy
existujúcich Phase2 J–N genes inšpirované mechanizmom. Gene návrh sa nevydáva
za matematicky ekvivalentný každej anomaly podmienke.

Read-only `handoff.ingest` overuje content hash, schema, cutoff pred budúcim
origin a nulovú trading autoritu. Na VPS prijal 4 unikátne gene návrhy pre
origin 2020-07-01 v skorom checkpointe a 5 pre neskorší cutoff v záverečnej
kontrole. Výsledky sú uložené ako návrhy pre ďalší Phase2 experiment. Už
dokončený zmrazený v2 cyklus ich nekonzumuje a nebol znovu otvorený.

## Nasadenie a automatické pokračovanie

- VPS: existujúci `57.129.127.49`, Python
  `/opt/trendatlas-research/venvs/causal-v1/bin/python`.
- Pôvodný frozen base: `/opt/trendatlas-research/phase2-v2/releases/91237299dee6880e`.
- Lab release: `/opt/trendatlas-research/anomaly-lab/releases/c23fc478faf29b8a`.
- Package SHA256: `c23fc478faf29b8a4ac43a5ebd004989b621850b41f330c2cb6458d8ca2caaa7`.
- Input manifest SHA256: `5fa5e1178fadc74a3f3febde216f87d501d55728137fb952e8cec8768bd0114f`.
- Reportovací release: `/opt/trendatlas-research/anomaly-lab/reporting/86e74b86b06680ba`.
- Stav: `/var/lib/trendatlas-anomaly-lab`; logy: `/var/log/trendatlas-anomaly-lab`.
- Jednotky: `trendatlas-anomaly-lab.service/.timer`,
  `trendatlas-anomaly-broker.service/.timer`; reportovací ExecStartPost iba na Lab.

Worker má samostatného používateľa, `PrivateNetwork=true`, žiadny credential,
write iba do vlastného stavu/logov, zakázaný prístup k produkcii, pôvodnému v2
stavu a collector archívu. Broker vidí iba vlastný mailbox a existujúci research
DeepSeek credential cez LoadCredential; nevidí Lab knihy ani vstupnú históriu.
Jeden worker, CPUQuota 60 %, MemoryMax 3 GiB, 180 s plánovanej práce/tick,
420 s service timeout; nameraný peak približne 1.3–1.4 GiB.

Checkpointy A→B→C→D dokazujú postup 1→2→4→14 origins pri opakovaných
automatických aktiváciách po odpojení jednotlivých SSH session. Finálny
reportovací receipt je v `runtime-final.json`. Posledné neskoršie tick-y
preskakujú cez exec-condition a neotvárajú nový API rozpočet.

## Regression test added/updated

`tests/test_anomaly_lab.py`: 20 nových testov pre clustering 100 dní/10 mincí,
chýbajúce dáta a lineage, prefix/future perturbation, publication buffer,
timestamp guard, nezávislé účtovanie/náklady, kontinuitu equity, chybné ceny,
lifetime multiplicitu a synthetic no-edge, block uncertainty, nemennosť,
broker bounds/cache/uncertain retry, bezpečný handoff a systemd/idle izoláciu.

`tests/test_anomaly_lab_reporting.py`: 3 regresie pre zavádzajúce nulové
intervaly, neznáme billing/stale súhrny a nemožnosť zmeniť experiment či autoritu.
Existujúce Phase2 testy ani evaluator neboli upravené.

## Forbidden old path checked

Neboli vykonané produkčné refresh/publish/submit/order príkazy. Žiadny
produkčný service nebol reštartovaný. Pi, LeadPilot, účet, obchodné secrets,
authority snapshoty, frontend a `outputs/*`/`data/*` zostali bez úprav.
Pre Lab nebol vytvorený konkurenčný production scheduler. Collector a jeho
zamknuté dáta sa nepoužili. Úpravy boli vykonané v samostatnom worktree;
nesúvisiace rozpracované zmeny pôvodného adresára boli zachované.

VPS read-only hashe tabuliek pôvodného v2 `meta`, `candidates`, `evaluations`,
`members`, `stages`, `selections`, `test_books`, `terminal_test_failures`,
`events` sú rovnaké pred nasadením aj po všetkých 14 Lab obdobiach.
Pôvodný Lab hash udalosti 293 zostal rovnaký; finálna hash chain je PASS a
deployed code/input binding súhlasí. Runtime modul ani hlavný kontrakt sa po
zmrazení nemenil; oprava reportu má oddelený kontrakt/release.

## Validation commands/results

```text
python -B -m research.anomaly_lab.contract
PASS: platný kontrakt, orders_allowed=false, sealed_access=false

python -B -m unittest tests.test_anomaly_lab tests.test_anomaly_lab_reporting tests.test_phase2_v2 tests.test_phase2_v2_continuation -q
PASS: 43 lokálnych testov

python -m compileall -q research/anomaly_lab
PASS

Native VPS preflight: tests.test_anomaly_lab + frozen tests.test_phase2_v2
PASS: 33 testov (20 nových + 13 v skutočne nasadenom pôvodnom frozen base)

Native VPS reporting preflight: tests.test_anomaly_lab_reporting
PASS: 3 testy

systemd-analyze verify /etc/systemd/system/trendatlas-anomaly-lab.service /etc/systemd/system/trendatlas-anomaly-lab.timer /etc/systemd/system/trendatlas-anomaly-broker.service /etc/systemd/system/trendatlas-anomaly-broker.timer
PASS pre Lab; nesúvisiace distro upozornenia na xfs CPUAccounting

python -B -m research.anomaly_lab.audit --root /var/lib/trendatlas-anomaly-lab
PASS: 14 origins, hash_chain=PASS, nemennosť pôvodného v2 a source binding

git diff --check
PASS; iba upozornenia Git autocrlf
```

Aj celý nemockovaný syntetický smoke vykonal 44 počiatočných a potom 66
tréningových výpočtov, broker mailbox/reservation/cache, zmrazenie, 36 kníh a
1 dokončený origin. Skutočný VPS broker následne preukázal 14 natívnych API volaní.
Lokálny balík bol porovnaný po jednotlivých súboroch s nasadeným zipom.

Kontroly registrov:

```text
python -B -m unittest tests.test_source_of_truth_json_valid tests.test_source_of_truth_presence tests.test_script_registry_required_fields tests.test_script_registry_paths_exist tests.test_output_registry_required_fields tests.test_output_registry_official_truth_flags tests.test_output_registry_source_of_truth_consistency tests.test_output_registry_allowed_values -q
23 testov: 21 PASS, 2 FAIL rovnako aj na nezmenenom baseline 82bfae8a...
```

Existujúce zlyhania sú iba `test_decision_relevance_values_are_allowed` a
`test_layer_values_are_allowed`: staré registry hodnoty nesedia so staršími
enum testami. Zoznam zlyhaní je identický na pôvodnej Phase2 vetve aj novej vetve.
Obe nové output položky používajú platné hodnoty a nepridávajú nové zlyhania.
Staré output položky sú nezmenené. Presný dôkaz je `registry-validation.json`.

## Exact files changed / exact git add list

`GIT_ADD.txt` v tomto adresári je úplný zoznam jednotlivých súborov tejto zmeny,
vrátane reportu a dôkazov. Používa sa presne tento zoznam, bez `git add .` alebo
pridania nesúvisiacich zmien. Produkčné kódové/kontraktové súbory nie sú v zozname.

```powershell
$stageLabCode = @'
from pathlib import Path
import subprocess
files = Path('docs/anomaly-lab-20261008/GIT_ADD.txt').read_text().splitlines()
subprocess.run(['git', 'add', '--', *files], check=True)
'@
$stageLabCode | python -B -
git diff --cached --check
git commit -m 'Deploy isolated TrendAtlas anomaly discovery lab with causal research audits'
```

## Commit message / commit hash

Message: `Deploy isolated TrendAtlas anomaly discovery lab with causal research audits`.
Vetva: `codex/anomaly-discovery-lab-20261008`.
Presný hash commitu je uvedený v záverečnej odpovedi a dá sa reprodukovať cez
`git log -1 --format=%H -- docs/anomaly-lab-20261008/REPORT.md`.

## Uložené dôkazy

- `checkpoint-A.json`, `checkpoint-B.json`, `checkpoint-C.json`, `checkpoint-D.json`.
- `runtime-final.json`: nezávislé účtovanie a automatický posledný report.
- `final-discovery-report.json`: kompletný report po všetkých 14 obdobiach.
- `synthetic-null-calibration.json`: no-edge kalibrácia.
- `registry-validation.json`: nezmenené existujúce registry zlyhania.
- `GIT_ADD.txt`: presný zoznam súborov pre commit.
