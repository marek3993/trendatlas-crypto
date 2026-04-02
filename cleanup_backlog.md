\# MRV1 Cleanup Backlog



\## Účel

Tento backlog je engineering hygiene pracovný zoznam.

Nie je to strategy backlog, product backlog ani research backlog.



Cieľ:

\- rozdeliť cleanup na malé low-risk kroky

\- nemať chaos

\- nemať veľký refactor naraz

\- vedieť, čo je pripravené, čo je bloknuté a čo je mimo scope



\---



\## Pravidlá backlogu



Každý cleanup task má byť:

\- low-risk

\- reverzibilný alebo ľahko kontrolovateľný

\- bez zásahu do strategy truth, ak to nie je nutné

\- oddelený od research a product rozhodnutí



Každý task má mať:

\- jasný cieľ

\- scope

\- riziko

\- dependency

\- výstup



\---



\## Stavové značky



\- `TODO` = ešte nezačaté

\- `ACTIVE` = práve sa rieši

\- `BLOCKED` = blokované iným segmentom alebo vyšším rizikom

\- `DONE` = uzavreté



\---



\## Phase 1 — Safety rails



\### DONE — Root git hygiene

\- `.gitignore`

\- `repo\_hygiene\_contract.md`

\- `tests/README.md`



Výsledok:

\- repo má základný boundary contract

\- local/dev bordel má ignore mantinel

\- existuje minimálny test skeleton



\---



\### DONE — Structure and naming docs

\- `repo\_structure\_manifest.md`

\- `naming\_discipline.md`



Výsledok:

\- repo má štrukturálny kontrakt

\- nové skripty a súbory majú naming mantinel



\---



\## Phase 2 — Inventory and organization



\### TODO — Top-level repo inventory

Cieľ:

\- spísať všetky aktuálne top-level priečinky

\- ku každému určiť účel

\- označiť priečinky, ktoré sú:

&#x20; - core

&#x20; - automation

&#x20; - generated

&#x20; - temporary

&#x20; - unclear



Riziko:

\- nízke



Výstup:

\- explicitný inventory dokument alebo tabuľka



\---



\### TODO — Script inventory

Cieľ:

\- spraviť zoznam dôležitých scriptov

\- rozdeliť ich na:

&#x20; - production / baseline related

&#x20; - research runners

&#x20; - validation scripts

&#x20; - automation tools

&#x20; - one-off scripts



Riziko:

\- nízke



Výstup:

\- script inventory dokument

\- označenie kandidátov na budúci presun alebo archiváciu



\---



\### TODO — Generated output classification

Cieľ:

\- rozlíšiť:

&#x20; - referenčné outputs

&#x20; - workflow outputs

&#x20; - debug outputs

&#x20; - tmp/cache outputs



Riziko:

\- nízke



Výstup:

\- rozhodnutie čo sa môže verziovať

\- rozhodnutie čo má byť local-only alebo ignore



\---



\## Phase 3 — Execution hygiene



\### TODO — Hardcoded path audit

Cieľ:

\- nájsť absolútne cesty

\- nájsť cwd-dependent správanie

\- rozdeliť findings na:

&#x20; - safe to fix now

&#x20; - risky

&#x20; - needs config layer



Riziko:

\- stredné



Výstup:

\- audit zoznam

\- priorita fixov



\---



\### TODO — Entrypoint convention

Cieľ:

\- zjednotiť spôsob spúšťania hlavných scriptov

\- obmedziť ad-hoc run patterns



Riziko:

\- stredné



Výstup:

\- entrypoint contract

\- zoznam scriptov, ktoré treba neskôr prispôsobiť



\---



\### TODO — Shared config/path layer plan

Cieľ:

\- určiť, kde má žiť centrálna path/config vrstva

\- znížiť hardcode bez veľkého refactoru



Riziko:

\- stredné



Výstup:

\- malý návrh shared config vrstvy



\---



\## Phase 4 — Test minimum



\### TODO — Source of truth integrity test

Cieľ:

\- overiť existenciu kľúčových truth súborov

\- overiť základnú JSON validitu



Riziko:

\- nízke



Výstup:

\- prvý reálny smoke/integrity test script



\---



\### TODO — Repo structure smoke test

Cieľ:

\- chytať zakázané committed artefakty

\- chytať chýbajúce kľúčové priečinky/súbory



Riziko:

\- nízke



Výstup:

\- druhý hygiene test script



\---



\### TODO — Export contract smoke checks

Cieľ:

\- overiť základné stĺpce tam, kde je contract definovaný



Riziko:

\- stredné

\- pozor na presah do research truth



Výstup:

\- len minimálne, contract-based checks



\---



\## Phase 5 — Packaging and CI readiness



\### TODO — Dependency inventory

Cieľ:

\- oddeliť Python deps, Node deps, optional tooling

\- pripraviť pôdu pre requirements / package lock disciplínu



Riziko:

\- stredné



Výstup:

\- dependency inventory dokument



\---



\### TODO — Packaging plan

Cieľ:

\- definovať, čo je app/runtime packageable

\- čo je len script layer

\- čo je automation infra



Riziko:

\- stredné



Výstup:

\- packaging plán bez predčasného refactoru



\---



\### TODO — CI minimum plan

Cieľ:

\- definovať minimum pre budúce CI:

&#x20; - syntax

&#x20; - smoke tests

&#x20; - JSON validation

&#x20; - repo boundary checks



Riziko:

\- nízke



Výstup:

\- CI plan

\- neskôr workflow file



\---



\## Blocked / mimo scope



\### BLOCKED — Strategy methodology doc

Dôvod:

\- to nie je engineering hygiene dokument

\- patrí do iného segmentu



\### BLOCKED — Winner / leverage / research verdict cleanups

Dôvod:

\- nepatrí do hygiene scope



\### BLOCKED — App wording and UI framing

Dôvod:

\- product scope



\---



\## Najbližšie odporúčané kroky



1\. spraviť `packaging\_and\_ci\_plan.md`

2\. spraviť `dependency\_hygiene\_plan.md`

3\. spraviť prvý reálny hygiene test script:

&#x20;  - truth file existence

&#x20;  - JSON validity

4\. až potom riešiť hardcoded path audit



