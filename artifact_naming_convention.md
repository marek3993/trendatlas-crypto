\# MRV1 Artifact Naming Convention



\## Účel

Tento dokument zavádza naming convention pre artifacts v MRV1.



Cieľ:

\- znížiť chaos

\- rozlíšiť research layer od canonical layer

\- zabrániť názvom, ktoré skrývajú skutočnú rolu artefaktu

\- zlepšiť lineage a truth čitateľnosť



\---



\## 1. Základné pravidlo



Z názvu artefaktu musí byť jasné:

\- či je historical alebo canonical

\- aký je artifact type

\- aká je doména alebo phase scope

\- na čo artifact slúži



Zakázané sú nejasné názvy typu:

\- `final`

\- `new`

\- `better`

\- `real\_final`

\- `report`, ak nie je jasné či ide o summary/paper/decision

\- `notes`

\- `misc`



\---



\## 2. Historical / research layer naming



Pattern:



`<phase\_or\_domain>\_<artifact\_type>\_<scope>.<ext>`



Príklady:

\- `phase68f\_summary\_tradable\_basis.csv`

\- `phase67j\_compare\_vs\_phase66g.csv`

\- `phase68e\_manifest\_realistic\_leverage.json`

\- `phase66g\_decision\_production\_freeze.md`

\- `research\_os\_manifest\_generated\_specs.json`



\### Povolené `artifact\_type` v historical vrstve

\- `raw`

\- `summary`

\- `compare`

\- `manifest`

\- `decision`

\- `paper`



\### Pravidlá

\- `phase\_or\_domain` musí hovoriť odkadiaľ artifact pochádza

\- `scope` musí hovoriť o čom artifact je

\- `summary` sa nesmie volať `report`, ak je to reálne summary

\- `decision` musí byť pomenovaný ako decision, nie schovaný v inom type



\---



\## 3. Canonical layer naming



Pattern:



`canonical\_<truth\_domain>\_<artifact\_type>.<ext>`



Ak je naozaj potrebná verzia:



`canonical\_<truth\_domain>\_<artifact\_type>\_v1.<ext>`



Príklady:

\- `canonical\_strategy\_decision.json`

\- `canonical\_strategy\_snapshot.json`

\- `canonical\_strategy\_manifest.json`

\- `canonical\_universe\_decision.json`

\- `canonical\_leverage\_snapshot.json`

\- `canonical\_product\_export.csv`

\- `canonical\_benchmark\_reference.csv`

\- `canonical\_artifacts\_manifest.json`

\- `canonical\_lineage\_manifest.json`



\---



\## 4. Povolené canonical truth domains



Používať len malý stabilný slovník:



\- `strategy`

\- `universe`

\- `leverage`

\- `product`

\- `benchmark`

\- `artifacts`

\- `lineage`



Nezavádzať ad-hoc truth domain názvy bez silného dôvodu.



\---



\## 5. Povolené canonical artifact types



Používať len:



\- `decision`

\- `snapshot`

\- `manifest`

\- `export`

\- `reference`



Pravidlo:

\- canonical layer má byť menšia a čistejšia než historical layer

\- keď artifact nesedí do tohto modelu, treba najprv upraviť contract, nie vymýšľať chaos v názve



\---



\## 6. Mapping pravidlo



Historical názvy môžu byť komplikovanejšie.

Canonical názvy musia byť:

\- krátke

\- stabilné

\- product-readable

\- truth-readable



Príklad:

\- historical: `phase67j\_compare\_vs\_phase66g.csv`

\- canonical: `canonical\_strategy\_reference.csv`



Historical artifact môže byť upstream input pre canonical artifact, ale nesmie byť zaň zamieňaný.



\---



\## 7. JSON / CSV / MD význam



\### `.json`

Použiť pre:

\- manifests

\- decisions

\- snapshots

\- lineage contracts



\### `.csv`

Použiť pre:

\- exports

\- tabulárne reference outputs

\- compare tables



\### `.md`

Použiť pre:

\- explanatory paper

\- human-readable governance docs

\- methodology/explanation text



Pravidlo:

\- decision truth má preferovať JSON contract, nie len markdown vysvetlenie

\- markdown môže decision vysvetliť, ale nemá byť jediný strojový truth carrier



\---



\## 8. Zakázané patterns



Nepoužívať:

\- `\_final`

\- `\_final2`

\- `\_real\_final`

\- `\_fixed`

\- `\_better`

\- `\_new`

\- `\_latest`

\- nejasné `report` bez artifact type významu



Nepoužívať canonical názov pre niečo, čo ešte nie je official alebo reference-approved.



\---



\## 9. Version suffix disciplína



`\_v1`, `\_v2` používať len keď:

\- existuje reálny contract break

\- staršia verzia musí dočasne koexistovať

\- je potrebný bezpečný transition



Nepoužívať verzie len preto, že vznikol chaos.



\---



\## 10. Cieľ naming convention



Po zavedení naming convention má byť z názvu jasné:

\- historická vs canonical vrstva

\- artifact type

\- truth domain alebo phase/domain source

\- intended role artefaktu

