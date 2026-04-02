\# MRV1 Naming Convention



\## Účel

Tento dokument definuje canonical naming convention pre artifacts, canonical outputs a migration layer v MRV1.



Cieľ:

\- znížiť naming chaos

\- oddeliť historical layer od canonical layer

\- zaviesť stabilné artifact suffixes

\- zlepšiť lineage a truth čitateľnosť

\- pripraviť controlled migration bez big-bang refactoru



\---



\## 1. Základný naming model



Pre nové research a output artifacts používať pevný formát:



`{family}\_{profile}\_{artifact}.{ext}`



Kde:

\- `family` = stabilná skupina alebo workflow rodina

\- `profile` = konkrétny variant alebo profil

\- `artifact` = explicitný artifact typ



Príklady:

\- `phase67j\_final\_narrow\_validation\_no\_neo\_main\_paper.csv`

\- `phase66g\_production\_candidate\_live\_production\_soft\_filters\_summary.csv`



Ak je family už sama o sebe dostatočne špecifická a profile by bol len duplicitný, profile sa môže zjednodušiť, ale artifact typ musí zostať explicitný.



\---



\## 2. Canonical artifact suffixes



Povolené artifact suffixes pre canonical a novo zavádzané outputs:



\- `\_paper.csv`

\- `\_summary.csv`

\- `\_compare.csv`

\- `\_manifest.json`

\- `\_decisions.csv`

\- `\_leaderboard.csv`

\- `\_asset\_quality.csv`

\- `\_asset\_usage.csv`

\- `\_failed\_assets.csv`

\- `\_forensic.csv`

\- `\_shortlist.csv`

\- `\_latest\_top10.csv`

\- `\_live\_status.csv`

\- `\_export.csv`

\- `\_validation\_report.json`

\- `\_bundle\_manifest.json`



\---



\## 3. Význam suffixov



\### `paper`

Time series source-of-truth equity/position output.



\### `summary`

Jednoriadkové alebo viacriadkové metric zhrnutie.



\### `compare`

Porovnanie variantov, baseline alebo behov.



\### `manifest`

Lineage, paths, timestamps, inputs, contract metadata.



\### `decisions`

Výberové, rebalance alebo selection logy.



\### `leaderboard`

Ranked výsledky viacerých kandidátov alebo behov.



\### `asset\_quality`

Kvalita assetov podľa definovaného hodnotiaceho rámca.



\### `asset\_usage`

Použitie assetov v selekciách, rotáciách alebo governance.



\### `failed\_assets`

Assety vyradené fail pravidlami alebo validáciou.



\### `forensic`

Diagnostický alebo auditný artifact.



\### `shortlist`

Finálny alebo medzikrokový shortlist.



\### `latest\_top10`

Stabilný top10 snapshot pre danú family/profile vrstvu.



\### `live\_status`

Normalizovaný live/app status export.



\### `export`

Normalizovaný downstream export.



\### `validation\_report`

Machine-readable validačný verdict/report.



\### `bundle\_manifest`

Manifest validačného alebo handoff bundle.



\---



\## 4. Zakázané naming patterns



Nepoužívať:

\- `final`

\- `final2`

\- `real\_final`

\- `fixed`

\- `better`

\- `new`

\- `latest` bez explicitného artifact významu

\- `report` ak reálne ide o `summary`, `forensic`, `decision` alebo `validation\_report`



Zakázané mixy:

\- `top\_compare`

\- `compare\_summary`

\- `final\_compare`

\- `candidate\_compare`

\- `manifest`, `run\_manifest`, `phase\_manifest` bez explicitného rozdielu

\- `latest top10`

\- `latest\_decision\_top10`

\- `top10\_latest`



Namiesto toho:

\- vždy `\*\_latest\_top10.csv`



\---



\## 5. Historical vs canonical layer



\### Historical / research layer

Historické názvy nemusia byť spätne komplet premenované.

Môžu zostať, ale:

\- nesmú byť považované za canonical len preto, že existujú

\- musia byť mapované cez `paths\_registry.json`, keď sú relevantné pre current truth



\### Canonical layer

Canonical artifacts majú používať stabilné, čisté názvy a registry mapping.

Canonical vrstva je preferovaný zdroj pre product/app/downstream čítanie.



\---



\## 6. Canonical folder intent



Canonical pravidlo:

\- strategy veci idú do `outputs/strategy/...`

\- forensic veci idú do `outputs/forensic/...`

\- app/live/export veci idú do `outputs/execution/...`

\- AI/research loop veci idú do `outputs/research\_os/...`

\- paths riadi `source\_of\_truth/paths\_registry.json`



\---



\## 7. Current preferred canonical output groups



\### Strategy

\- `outputs/strategy/core/`

\- `outputs/strategy/overlay/`

\- `outputs/strategy/universe/`

\- `outputs/strategy/governance/`

\- `outputs/strategy/leverage/`



\### Forensic

\- `outputs/forensic/strategy/`

\- `outputs/forensic/universe/`

\- `outputs/forensic/governance/`

\- `outputs/forensic/leverage/`



\### Execution

\- `outputs/execution/app\_exports/`

\- `outputs/execution/freshness/`

\- `outputs/execution/refresh\_pipeline/`



\### Research OS

\- `outputs/research\_os/ideation/`

\- `outputs/research\_os/spec\_generation/`

\- `outputs/research\_os/autonomous\_loop/`

\- `outputs/research\_os/diagnostics/`



\### Validation

\- `outputs/validation/bundles/`

\- `outputs/validation/manifests/`

\- `outputs/validation/reports/`



\---



\## 8. Controlled migration principle



Fáza 0:

\- nič nemaž

\- nič hromadne nepremenúvaj

\- zaveď naming contract

\- zaveď migration state

\- zaveď canonical folders a registry mapping



Fáza 1:

\- write-through canonical

\- nový zápis ide do canonical path

\- podľa potreby aj do legacy alias path



Fáza 2:

\- readeri idú cez registry resolver

\- nie cez hardcoded `outputs/phase...`



Fáza 3:

\- legacy deprecation

\- nové zápisy len canonical

\- legacy len alias alebo controlled fail



\---



\## 9. Source of truth boundary



`paths\_registry.json` rieši:

\- kde čo leží

\- canonical path

\- legacy aliases

\- ownership

\- artifact type

\- read/write resolution intent



`project\_truth.json` rieši:

\- čo je aktuálna truth

\- current winner

\- current baseline

\- current export set

\- migration phase



Tieto dve vrstvy sa nesmú miešať.



\---



\## 10. Cieľ

Po zavedení tejto naming convention má byť jasné:

\- čo je strategy

\- čo je forensic

\- čo je execution

\- čo je research\_os

\- čo je validation

\- čo je canonical

\- čo je legacy alias

\- čo je official downstream path

