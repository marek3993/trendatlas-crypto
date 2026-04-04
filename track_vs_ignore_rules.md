\# Track vs Ignore Rules



\## 1. Účel

Tento dokument určuje, čo sa má v projekte Market Regime v1 štandardne trackovať v gite a čo sa má defaultne považovať za generated/runtime/support-only vrstvu.



Cieľ:

\- znížiť chaos v repozitári

\- znížiť miešanie truth a runtime outputov

\- zlepšiť commit hygiene

\- zlepšiť audit čitateľnosť



\---



\## 2. Základné pravidlo

Trackovať sa majú:

\- source files

\- contracts

\- schemas

\- templates

\- canonical layer

\- official truth

\- test guardrails

\- dôležité pinned reference artifacts



Defaultne sa nemajú trackovať len preto, že vznikli:

\- runtime logs

\- queue churn

\- screenshots

\- transient reports

\- repeated generated run artifacts

\- temporary summaries

\- diagnostics

\- support-only orchestration files



\---



\## 3. Vždy trackovať



\### 3.1 Official truth

\- všetko v `source\_of\_truth/`



\### 3.2 Canonical layer

\- `canonical/decisions/`

\- `canonical/references/`

\- `canonical/manifests/`

\- `canonical/exports/`

\- registry workflow docs

\- canonical contracts



\### 3.3 Source code

\- `scripts/`

\- `app.py`

\- stabilné helpers

\- execution control files, ak sú source code a nie runtime output



\### 3.4 Tests

\- `tests/`

\- guardrail manifests

\- repo hygiene tests

\- contract tests



\### 3.5 Contracts / schemas / templates

\- `automation/schemas/`

\- `automation/templates/`

\- stable config contracts

\- documented policy files



\### 3.6 Documentation

\- repo contracts

\- naming docs

\- status docs

\- commit hygiene docs

\- artifact taxonomy docs



\---



\## 4. Trackovať selektívne



\### 4.1 Reports

Trackovať len keď:

\- sú explicitne dohodnuté ako audit artifact

\- sú pinned workflow artifact

\- majú dlhodobú hodnotu pre repo čitateľnosť



Inak nie.



\### 4.2 Generated manifests

Trackovať len keď:

\- sú súčasť workflow contractu

\- majú stabilný consumer meaning

\- nie sú len runtime noise



\### 4.3 Reference outputs

Trackovať len keď:

\- ide o pinned reference

\- je to canonical support/reference artifact

\- má to historickú hodnotu, ktorú chceme vedome zachovať



\---



\## 5. Defaultne netrackovať



\### 5.1 Runtime outputs

\- `outputs/...` keď ide o transient generated files

\- latest snapshots

\- latest runtime summaries

\- generated app refresh folders

\- repeated refresh outputs



\### 5.2 Research runs

\- `research\_os/runs/`

\- `research\_os/promotion\_queue/`

\- `research\_os/experiment\_specs/generated/\*.spec\_ready.json`

\- runtime ideation/autonomous loop logs

\- repeated generated experiment outputs



\### 5.3 Automation support artifacts

\- `automation/screenshots/`

\- `automation/tasks/queue/`

\- `automation/tasks/completed/`

\- `automation/reports/` ak ide len o transient workflow output

\- repeated approval/support records, ak nie sú explicitne potrebné



\### 5.4 Logs

\- `.log`

\- `.jsonl`

\- transient diagnostics

\- trace files

\- queue churn

\- repeated dispatcher artifacts



\---



\## 6. Špeciálne pravidlá podľa vrstvy



\### 6.1 outputs/

Default:

\- generated

\- netrackovať automaticky



Výnimka:

\- pinned audit artifact

\- stable product/export support artifact

\- explicitne schválený historical artifact



\### 6.2 automation/

Trackovať:

\- tool scripts

\- schemas

\- templates

\- stable config files



Netrackovať defaultne:

\- screenshots

\- queue churn

\- transient reports

\- transient run artifacts



\### 6.3 research\_os/

Trackovať:

\- policies

\- source scripts

\- stable registries

\- explicitné contracts



Netrackovať defaultne:

\- generated specs

\- promotion queue spam

\- run folders

\- transient generated reports



\### 6.4 data/

Trackovať len ak je to vedomá súčasť repo data contractu.

Ak ide o refresh churn, necommitovať to len preto, že downloader prebehol.



\---



\## 7. Generated artifact decision rule

Generated artifact sa smie commitnúť len ak platí aspoň jedno:

1\. je to official truth support artifact

2\. je to canonical reference/support artifact

3\. je to explicitný audit artifact

4\. je to stabilný workflow contract artifact

5\. segment owner výslovne rozhodol, že má ísť do histórie



Ak neplatí nič z toho:

\- necommitovať



\---



\## 8. Latest-file rule

Súbory typu:

\- `latest\_\*`

\- current snapshots

\- current status dumps

\- latest manifests



sú defaultne podozrivé ako runtime churn.



Necommitovať ich automaticky.

Commit len ak:

\- sú súčasťou stabilného product/export contractu

\- alebo ich segment explicitne chce držať vo verziách



\---



\## 9. Phase/research outputs rule

Phase-style research outputs:

\- sú užitočné pre research

\- nie sú automaticky pekná repo história

\- nemajú sa commitovať len preto, že vznikli



Ak sa majú zachovať:

\- musí byť jasné prečo

\- musí byť jasné či sú report / reference / audit / generated-only



\---



\## 10. Commit hygiene väzba

Ak je dirty state mixed:

\- najprv oddeliť source/contracts od runtime outputs

\- commitnúť len clean scope

\- generated outputs defaultne nechať mimo



Pravidlo:

\- keď si nie si istý, necommituj generated artifact



\---



\## 11. Quick default map



\### Track

\- `source\_of\_truth/\*`

\- `canonical/\*`

\- `scripts/\*`

\- `tests/\*`

\- `automation/schemas/\*`

\- `automation/templates/\*`

\- stable config files

\- repo docs



\### Usually stay out

\- `outputs/\*\*/\*`

\- `research\_os/runs/\*\*/\*`

\- `research\_os/promotion\_queue/\*\*/\*`

\- `research\_os/experiment\_specs/generated/\*.spec\_ready.json`

\- `automation/screenshots/\*\*/\*`

\- `automation/tasks/queue/\*\*/\*`

\- `automation/tasks/completed/\*\*/\*`

\- transient workflow reports

\- latest runtime snapshots



\---



\## 12. Stop rule

Ak generated/runtime/support-only files tvoria väčšinu `git status`, repo nie je pripravené na slepý commit.



Najprv:

1\. určiť scope

2\. oddeliť track od ignore

3\. commitnúť len to, čo má dlhodobý význam

