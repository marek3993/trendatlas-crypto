\# MRV1 Artifact Lineage Audit Backlog



\## Účel

Tento backlog rozdeľuje lineage audit na malé low-risk kroky.



Cieľ:

\- zistiť ktoré artifacts majú jasný pôvod

\- nájsť slepé miesta v lineage

\- určiť čo treba mapovať do canonical manifests

\- pripraviť guardrails a neskoršie validators



\---



\## Stavové značky



\- `TODO`

\- `ACTIVE`

\- `BLOCKED`

\- `DONE`



\---



\## Audit priority



\### P1 — Canonical JSON artifacts

Cieľ:

\- overiť či každý canonical JSON artifact má minimum lineage fields

\- overiť či naming/type/domain sedí s obsahom



Aktuálny scope:

\- `canonical\_strategy\_decision.json`

\- `canonical\_strategy\_snapshot.json`

\- `canonical\_universe\_decision.json`

\- `canonical\_leverage\_decision.json`

\- `canonical\_66g\_reference.json`

\- `canonical\_benchmark\_reference.json`

\- `canonical\_artifacts\_manifest.json`

\- `canonical\_lineage\_manifest.json`

\- `canonical\_product\_manifest.json`

\- `canonical\_product\_export\_contract.json`



Status:

\- `TODO`



\---



\### P2 — Historical upstream mapping

Cieľ:

\- ku canonical artifacts doplniť presnejšie historical upstream inputs tam, kde to bude neskôr potrebné



Príklady:

\- compare artifacts

\- summary artifacts

\- source\_of\_truth truth carriers

\- baseline and benchmark references



Status:

\- `TODO`



\---



\### P3 — Missing run linkage

Cieľ:

\- zmapovať kde chýba `source\_run\_id`

\- rozdeliť chýbajúce linkage na:

&#x20; - acceptable bootstrap null

&#x20; - needs future fill

&#x20; - risky unknown provenance



Status:

\- `TODO`



\---



\## Audit buckets



\### Bucket A — Bootstrap acceptable null lineage

Sem patria artifacts, kde je dočasne prijateľné:

\- `source\_run\_id = null`

\- producer = manual bootstrap



Podmienka:

\- artifact je governance/bootstrap vrstva

\- nejde o falošnú predstieranú automatizáciu



Status:

\- `ACTIVE`



\---



\### Bucket B — Needs explicit upstream expansion

Sem patria artifacts, kde minimum existuje, ale upstream list je zatiaľ príliš hrubý.



Príklady:

\- strategy decision

\- universe decision

\- leverage decision



Status:

\- `TODO`



\---



\### Bucket C — Risky future mismatch candidates

Sem patria artifacts alebo families, kde lineage nejasnosť môže spôsobiť truth confusion.



Príklady:

\- compare artifacts použité ľuďmi ako verdict source

\- summary artifacts bez paired decision

\- paper writeups bez machine-readable pairu



Status:

\- `TODO`



\---



\## Prvé konkrétne audit úlohy



\### TODO — Audit canonical decisions

Skontrolovať:

\- naming

\- truth\_status

\- lineage minimum

\- upstream plausibility

\- consumer scope



\### TODO — Audit canonical references

Skontrolovať:

\- reference vs official separation

\- explicitné `must\_not\_be\_used\_as`

\- consumer scope



\### TODO — Audit canonical manifests

Skontrolovať:

\- či manifest len opisuje

\- či netečie do hidden decision role

\- či artifact index sedí s realitou



\### TODO — Audit product export contract

Skontrolovať:

\- allowed sources

\- forbidden sources

\- required truth fields

\- downstream read rule



\---



\## Budúce výstupy po tomto backlogu



1\. prvý lineage validator test

2\. prvý truth consistency validator test

3\. prípadne `canonical\_audit\_report.md`

4\. neskôr machine-readable audit summary JSON



\---



\## Pravidlá



\- audit backlog nerobí strategy verdicty

\- audit backlog nerobí product wording

\- audit backlog nerobí research selection

\- audit backlog rieši len artifact pôvod, contract a confusion risk

