\# MRV1 Lineage Contract



\## Účel

Tento dokument zavádza minimálny lineage contract pre MRV1 artifacts.



Cieľ:

\- vedieť spätne povedať z čoho artifact vznikol

\- znížiť truth mismatch risk

\- zlepšiť forensic audit

\- pripraviť canonical layer na čisté manifests a decisions



\---



\## 1. Základný princíp



Artifact bez lineage je len súbor.

Canonical truth artifact musí mať minimálne čitateľné lineage metadata.



Lineage musí vedieť odpovedať:

\- kto artifact vyrobil

\- kedy vznikol

\- z akých upstream inputs vznikol

\- z akého runu vznikol

\- čo nahrádza

\- kto ho má čítať



\---



\## 2. Minimum lineage fields



Každý budúci canonical JSON artifact má mať aspoň:



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



\---



\## 3. Field význam



\### `artifact\_name`

Stabilný canonical názov artefaktu.



\### `artifact\_type`

Jedno z:

\- `decision`

\- `snapshot`

\- `manifest`

\- `export`

\- `reference`



\### `truth\_domain`

Jedno z:

\- `strategy`

\- `universe`

\- `leverage`

\- `product`

\- `benchmark`

\- `artifacts`

\- `lineage`



\### `truth\_status`

Jedno z:

\- `exploratory`

\- `candidate`

\- `reference`

\- `official`

\- `deprecated`

\- `superseded`



\### `generated\_at`

Timestamp vytvorenia artefaktu.



\### `effective\_date`

Dátum od ktorého artifact platí ako truth carrier alebo reference point.



\### `producer\_script`

Presný script alebo process, ktorý artifact vygeneroval.



\### `source\_run\_id`

Presný run identifier, ak existuje.



\### `upstream\_artifacts`

Zoznam upstream artifacts použitých na vznik.



\### `supersedes`

Artifact alebo artifacts, ktoré tento artifact nahrádza.



\### `consumer\_scope`

Kto artifact smie čítať.



Odporúčané hodnoty:

\- `research\_only`

\- `canonical\_only`

\- `product\_readable`

\- `app\_readable`

\- `audit\_only`



\---



\## 4. Pravidlá lineage disciplíny



\### Rule 1

Canonical decision bez `source\_run\_id` alebo explicitného dôvodu jeho absencie je slabý truth carrier.



\### Rule 2

Canonical export bez upstream artifacts je auditne slabý.



\### Rule 3

Artifact, ktorý superseduje starší truth carrier, má to uviesť explicitne.



\### Rule 4

Historical artifacts nemusia spätne dostať plný lineage retrofit naraz.

Stačí ich mapovať postupne cez canonical manifests.



\### Rule 5

Paper alebo markdown text nemá byť jediný lineage carrier, ak existuje machine-readable canonical artifact.



\---



\## 5. Minimal JSON shape example



```json

{

&#x20; "artifact\_name": "canonical\_strategy\_decision",

&#x20; "artifact\_type": "decision",

&#x20; "truth\_domain": "strategy",

&#x20; "truth\_status": "official",

&#x20; "generated\_at": "2026-04-02T16:30:00Z",

&#x20; "effective\_date": "2026-04-02",

&#x20; "producer\_script": "automation/tools/create\_pending\_truth\_patch.py",

&#x20; "source\_run\_id": "run\_20260402\_144918\_workflow\_run\_first\_safe\_run",

&#x20; "upstream\_artifacts": \[

&#x20;   "phase67j\_compare\_vs\_phase66g.csv",

&#x20;   "canonical\_benchmark\_reference.csv"

&#x20; ],

&#x20; "supersedes": \[

&#x20;   "canonical\_strategy\_decision\_v1"

&#x20; ],

&#x20; "consumer\_scope": \[

&#x20;   "canonical\_only",

&#x20;   "product\_readable",

&#x20;   "app\_readable"

&#x20; ]

}

