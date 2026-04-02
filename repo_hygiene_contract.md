\# MRV1 Repo Hygiene Contract



\## Účel

Tento dokument definuje minimálne engineering hygiene pravidlá pre Market Regime v1.

Cieľ je znížiť chaos, zabrániť zbytočnému bordelu v repozitári a pripraviť repo na bezpečný rast.



\---



\## 1. Základné pravidlo

Do Git patria len veci, ktoré majú dlhodobú hodnotu pre:

\- source code

\- konfiguráciu

\- dokumentáciu

\- reprodukovateľnosť

\- minimálne testy

\- source\_of\_truth



Do Git nepatria:

\- lokálne artefakty

\- cache

\- build output

\- node\_modules

\- venv

\- dočasné logy

\- lokálne secrets

\- jednorazový bordel



\---



\## 2. Kategórie obsahu



\### A. Source code

Patrí do Git.



Sem patrí najmä:

\- Python skripty a moduly

\- Node/app source

\- shared utilities

\- infra wrapper skripty

\- CI/deploy config

\- testy



Pravidlo:

\- source code má byť čitateľný, pomenovaný konzistentne a spustiteľný bez krehkých cwd hackov



\---



\### B. Source of truth

Patrí do Git.



Sem patrí najmä:

\- `source\_of\_truth/README.md`

\- `source\_of\_truth/master\_state.md`

\- `source\_of\_truth/chat\_roles.md`

\- `source\_of\_truth/project\_truth.json`

\- `source\_of\_truth/paths\_registry.json`

\- `source\_of\_truth/current\_issues.md`



Pravidlo:

\- source\_of\_truth je autoritatívna vrstva projektu

\- nesmie sa miešať s dočasnými poznámkami alebo debug výstupmi



\---



\### C. Generated outputs

Štandardne nepatria do Git, iba ak majú explicitnú hodnotu ako referenčný export.



Sem patria najmä:

\- CSV výstupy behov

\- dočasné grafy

\- intermediate cache

\- debug exports

\- logy behov



Pravidlo:

\- generated output má byť oddelený od source code

\- len malé a zámerne uchovávané referenčné artefakty môžu byť verzované

\- tmp/debug/cache pod outputs necommitovať



\---



\### D. Local/dev artifacts

Nepatria do Git.



Sem patria:

\- `node\_modules/`

\- `.venv/`, `venv/`

\- `.env`

\- editor cache

\- lokálne scratch súbory

\- experimentálny bordel mimo dohodnutej štruktúry



\---



\## 3. Folder disciplína



\### Odporúčaný význam top-level vrstiev

\- `source\_of\_truth/` = autoritatívny projektový stav

\- `tests/` = minimálne smoke/integrity testy

\- `outputs/` = generated výstupy behov

\- `docs/` alebo root `.md` = dokumentácia a kontrakty

\- app/runtime/source folders = produkčný alebo výskumný kód

\- helper/infra/scripts folders = spúšťacie a servisné skripty



Pravidlá:

\- nemiešať source code s generated output

\- nevytvárať nové top-level priečinky bez dôvodu

\- nové utility skripty pomenúvať tak, aby bolo jasné:

&#x20; - čo robia

&#x20; - či sú jednorazové alebo dlhodobé

&#x20; - či sú research, infra alebo maintenance



\---



\## 4. Naming disciplína



Pravidlá:

\- názvy majú byť deskriptívne, nie generické typu `test2.py`, `new\_final.py`, `helper\_fixed.py`

\- pri script runneroch preferovať konzistentný vzor

\- názov má hovoriť:

&#x20; - doménu

&#x20; - akciu

&#x20; - scope



Príklady dobrého štýlu:

\- `refresh\_app\_exports.py`

\- `validate\_source\_of\_truth\_integrity.py`

\- `research\_os\_autonomous\_loop\_runner\_v1.py`



Zlé príklady:

\- `run.py`

\- `final\_new.py`

\- `tmp\_script.py`



\---



\## 5. Hardcoded disciplína



Treba obmedzovať:

\- hardcoded absolútne cesty

\- magic constants bez vysvetlenia

\- cwd-dependent správanie

\- skryté implicitné input/output contracts



Preferovať:

\- centralizované path/config vrstvy

\- jasné constants/config bloky

\- explicitné input/output contracts



\---



\## 6. Test minimum



Repo minimum má obsahovať aspoň:

\- smoke testy pre kritické entrypointy

\- integrity check pre source\_of\_truth

\- základný test, že kľúčové súbory a cesty existujú

\- základný test, že exports majú očakávané stĺpce tam, kde je contract definovaný



Cieľ:

\- nie perfektné coverage

\- ale minimálna ochrana proti rozbitiu hygiene a infra vrstvy



\---



\## 7. Git boundary rozhodnutie



\### Do Git ÁNO

\- source code

\- config templates

\- docs

\- source\_of\_truth

\- testy

\- malé referenčné textové artefakty s jasným účelom



\### Do Git NIE

\- `node\_modules`

\- venv

\- cache

\- logy

\- temp

\- secrets

\- lokálne databázy

\- náhodné outputs/debug artefakty



\---



\## 8. Change policy



Každá hygiene zmena má byť:

\- low-risk

\- postupná

\- segmentovaná

\- bez zásahu do strategy truth, ak to nie je nevyhnutné



Neprípustné:

\- veľký necielený refactor bez mantinelov

\- premiestnenie veľkého množstva súborov naraz bez validácie

\- miešanie engineering hygiene s product/research rozhodnutiami



\---



\## 9. Aktuálny Phase 1 cieľ

Phase 1 zaviera iba safety rails:

\- root `.gitignore`

\- repo hygiene contract

\- test skeleton



Bez zmeny:

\- strategy logic

\- winner truth

\- research verdictov

\- app wording



\---



\## 10. Enforcement

Pred každým väčším cleanup krokom sa má overiť:

\- či zmena patrí do engineering hygiene segmentu

\- či je low-risk

\- či nemení project truth

\- či nezhorší reproducibility behov

