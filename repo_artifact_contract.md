\# Repo Artifact Contract



\## 1. Účel

Tento dokument zmrazuje základné engineering hygiene pravidlá pre artefakty v projekte Market Regime v1.



Cieľ:

\- znížiť truth mismatch

\- znížiť chaos v názvoch a priečinkoch

\- zjednodušiť forensic audit

\- oddeliť official truth od raw outputov

\- zaviesť stabilnú canonical vrstvu nad research názvami



\---



\## 2. Truth hierarchy



\### 2.1 Official truth

Jedina official truth vrstva je:

\- `source\_of\_truth/`



Sem patrí:

\- `master\_state.md`

\- `project\_truth.json`

\- `paths\_registry.json`

\- `current\_issues.md`

\- ďalšie explicitné source\_of\_truth súbory



Pravidlo:

\- ak sa mení official stav projektu, zmena sa musí prejaviť tu

\- raw output, report, automation artifact ani canonical registry nie sú samé o sebe official truth



\### 2.2 Canonical layer

Canonical vrstva je:

\- `canonical/`



Úloha canonical vrstvy:

\- navigácia

\- indexy

\- lineage

\- consumer-facing aliasy

\- contracts

\- decision/reference mapovanie



Canonical nie je SSOT.

Canonical nesmie potichu prepisovať truth.



\### 2.3 Raw/generated layer

Raw/generated vrstva sú najmä:

\- `outputs/`

\- `research\_os/experiment\_specs/generated/`

\- `research\_os/runs/`

\- `research\_os/promotion\_queue/`

\- automation logs, reports, screenshots, task specs



Tieto artefakty môžu byť decision-relevant.

Nie sú však automaticky official truth.



\---



\## 3. Artifact taxonomy



Každý artefakt má mať práve jednu hlavnú rolu.



\### 3.1 truth

Official stav projektu.

Miesto:

\- `source\_of\_truth/`



\### 3.2 decision

Explicitné schválené rozhodnutie alebo boundary.

Miesto:

\- `canonical/decisions/`



\### 3.3 reference

Referenčný benchmark, pinned baseline, historical anchor.

Miesto:

\- `canonical/references/`



\### 3.4 manifest

Index, contract, lineage mapovanie, dependency mapping.

Miesto:

\- `canonical/manifests/`



\### 3.5 export

Downstream contract pre app/consumer/export vrstvu.

Miesto:

\- `canonical/exports/`



\### 3.6 report

Human-readable alebo audit-readable report.

Miesto:

\- `outputs/...` alebo `automation/reports/...`



\### 3.7 generated\_artifact

Raw output skriptu, agenta alebo runu.

Miesto:

\- `outputs/...`

\- `research\_os/...generated...`

\- `research\_os/runs/...`



\### 3.8 support\_artifact

Pomocný artefakt:

\- log

\- screenshot

\- task spec

\- patch record

\- queue record

\- temp helper file



Miesto:

\- `automation/...`



\---



\## 4. Naming discipline



\### 4.1 Research IDs

Research názvy môžu zostať phase-style:

\- `phase68i\_dynamic\_ladder\_candidate`

\- `phase67j\_no\_neo\_main`



Research ID hovorí:

\- odkiaľ niečo prišlo

\- v akej research vetve vzniklo



\### 4.2 Canonical IDs

Canonical názvy majú hovoriť:

\- na čo artefakt slúži

\- nie ako vznikol



Formát:

\- `canonical\_<domain>\_<role>`



Príklady:

\- `canonical\_strategy\_snapshot`

\- `canonical\_product\_manifest`

\- `canonical\_benchmark\_reference`

\- `canonical\_product\_export\_contract`



\### 4.3 Reports

Formát:

\- `<domain>\_<purpose>\_report.<ext>`



Príklady:

\- `execution\_source\_contract\_report.json`

\- `materialize\_execution\_app\_exports\_report.json`



\### 4.4 Manifests

Formát:

\- `<domain>\_<purpose>\_manifest.<ext>`

\- alebo canonical manifest formát:

\- `canonical\_<scope>\_manifest.json`



\### 4.5 Generated research artifacts

Formát:

\- nechaj research naming

\- ale drž ich mimo canonical truth vrstvy



\---



\## 5. Directory contract



\### 5.1 source\_of\_truth

Obsah:

\- jediná official truth vrstva



\### 5.2 canonical/decisions

Obsah:

\- official boundaries

\- approved decision carriers



\### 5.3 canonical/references

Obsah:

\- reference-only artefakty

\- pinned baselines

\- benchmark references



\### 5.4 canonical/manifests

Obsah:

\- lineage

\- dependency mapy

\- canonical indexes

\- contracts



\### 5.5 canonical/exports

Obsah:

\- consumer/export contracts



\### 5.6 outputs

Obsah:

\- raw outputs

\- papers

\- summaries

\- compare files

\- generated reports



Pravidlo:

\- outputs nesmú byť vydávané za truth bez explicitného truth promotion flow



\### 5.7 automation

Obsah:

\- orchestration

\- reports

\- tasks

\- schemas

\- templates

\- approvals

\- patch records

\- apply workflow



Pravidlo:

\- automation nie je paralelná truth vrstva



\### 5.8 scripts

Obsah:

\- producer scripts

\- runtime entrypoints

\- helpers



\### 5.9 tests

Obsah:

\- guardrails

\- repo discipline

\- contract checks



\---



\## 6. Official / reference / generated / deprecated rules



\### official

\- source\_of\_truth alebo explicitne official canonical carrier

\- musí byť čitateľné ako current project truth



\### reference

\- smie sa čítať ako anchor / benchmark

\- nesmie sa tváriť ako current live truth



\### generated

\- raw output skriptu alebo runu

\- môže byť decision-relevant

\- nie je official bez explicitného promotion/apply flow



\### deprecated / superseded

\- historicky zachované

\- nesmú byť default read path pre product/app/master



\---



\## 7. Metric lineage contract



Každý canonical artifact má mať minimálne:

\- `artifact\_name`

\- `artifact\_type`

\- `truth\_domain`

\- `truth\_status`

\- `generated\_at`

\- `effective\_date`

\- `producer\_script`

\- `source\_run\_id`

\- `upstream\_artifacts`

\- `supersedes`

\- `consumer\_scope`



Každý decision-relevant report/export/summary má vedieť povedať:

\- z ktorého scriptu vznikol

\- z ktorého runu vznikol

\- na ktoré upstream artefakty sa viaže

\- či je official / reference / generated



Pravidlo:

\- metrika bez lineage je slabý audit artifact



\---



\## 8. Commit hygiene rules



\### 8.1 Jeden commit = jedna téma

Nemiešať do jedného commitu:

\- hygiene

\- app

\- AI LAB

\- DATA

\- execution

\- research outputs



\### 8.2 Generated outputs

Generated outputs commitovať len keď:

\- majú audit hodnotu

\- sú súčasťou dohodnutého artifact contractu

\- alebo to explicitne chce príslušný segment



Inak ich necommitovať len preto, že vznikli.



\### 8.3 Truth changes

Truth zmena musí smerovať do:

\- `source\_of\_truth/`



Nie len do:

\- outputs

\- reports

\- approvals

\- generated specs

\- automation logov



\### 8.4 Canonical changes

Canonical zmena má meniť:

\- navigáciu

\- contracts

\- alias vrstvu

\- lineage

\- nie sama official truth



\---



\## 9. Track vs do-not-track



\### Trackovať

\- official truth files

\- canonical decisions/references/manifests/exports

\- scripts

\- test guardrails

\- schemas

\- templates

\- stabilné contracts

\- dôležité audit manifests, ak sú súčasťou workflow contractu



\### Typicky necommitovať automaticky

\- run logs

\- queue churn

\- screenshots

\- transient reports

\- temporary generated summaries

\- runtime-only diagnostics

\- repeated generated promotion artifacts

\- transient research\_os runs



\---



\## 10. Low-risk refactor discipline



Pravidlá:

\- žiadny broad rewrite

\- nemenit strategy truth bez explicitného truth tasku

\- meniť po malých batchoch

\- najprv contracts, potom registries, potom tests, potom až presuny

\- pri každom kroku zachovať čitateľnosť a audit trail



\---



\## 11. Practical reading rule



Pri každom serióznom tasku:

1\. čítaj `source\_of\_truth/`

2\. potom `canonical/`

3\. až potom konkrétne `scripts/`, `outputs/`, `automation/`, `research\_os/`



Pravidlo:

\- nikdy nevyvodzovať official current state len z raw outputov

