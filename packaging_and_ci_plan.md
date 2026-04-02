\# MRV1 Packaging and CI Plan



\## Účel

Tento dokument definuje low-risk plán pre packaging disciplínu a CI-ready hygiene.



Nie je to príkaz na veľký refactor.

Je to postupný plán, ako dostať repo do stavu, kde:

\- sa dá bezpečnejšie meniť

\- sa dá lepšie validovať

\- sa dá neskôr zapojiť CI bez chaosu



\---



\## 1. Aktuálny problém



Repo má znaky rastu bez dostatočných mantinelov:

\- scripts a automation vrstva rastú

\- outputs pribúdajú

\- hardcoded správanie pravdepodobne existuje

\- test minimum je slabé

\- dependency hranice nie sú ešte explicitne zavreté



To znamená:

\- vysoké riziko náhodného rozbitia

\- slabšia reproducibility

\- slabšia dôveryhodnosť repa

\- horšia pripravenosť na CI



\---



\## 2. Packaging princíp



MRV1 sa zatiaľ nemá siliť do jedného veľkého balíka.



Treba oddeliť 3 vrstvy:



\### A. Strategy / research script layer

Sem patria:

\- phase scripts

\- validation runners

\- export builders

\- research orchestration scripts



Charakter:

\- často script-oriented

\- nie všetko musí byť package hneď



\---



\### B. Automation / workflow layer

Sem patria:

\- approvals

\- truth patch tooling

\- validation helpers

\- workflow runners

\- JSON/tooling utilities



Charakter:

\- vhodné na vyššiu disciplínu

\- časom kandidát na čistejšiu modulárnu vrstvu



\---



\### C. App / runtime layer

Sem patrí:

\- to, čo ide do user-facing alebo dlhodobo prevádzkovanej vrstvy



Charakter:

\- najväčší tlak na stabilitu

\- najväčší tlak na packaging a deploy disciplínu



\---



\## 3. Low-risk packaging cieľ



Krátkodobý cieľ nie je:

\- prerobiť všetko na package

\- meniť všetky importy

\- zavádzať zložité build systémy



Krátkodobý cieľ je:

\- vedieť, čo je package candidate

\- vedieť, čo ostáva script-only

\- znížiť chaos v spúšťaní a dependency hraniciach



\---



\## 4. CI minimum cieľ



Prvé CI minimum má robiť len lacné a bezpečné kontroly:



\### Povinné minimum

\- Python syntax / import smoke tam, kde je to bezpečné

\- JSON validity checks pre contract súbory

\- source\_of\_truth existence checks

\- repo boundary / forbidden artifact checks



\### Zatiaľ nie

\- ťažké integračné behy

\- dlhé research reruny

\- performance benchmarking

\- winner correctness gates



\---



\## 5. Odporúčaná postupnosť



\### Phase A — Documentation and inventory

\- hygiene docs

\- structure docs

\- naming docs

\- cleanup backlog

\- dependency inventory



\### Phase B — Minimal validation layer

\- truth existence test

\- JSON validity test

\- forbidden artifact smoke check



\### Phase C — Script discipline

\- entrypoint pravidlá

\- hardcoded path audit

\- safe shared path/config conventions



\### Phase D — CI bootstrap

\- prvý lightweight CI workflow

\- spúšťa len rýchle hygiene testy



\### Phase E — Packaging decisions

\- určiť ktoré časti sa oplatí balíkovať

\- ktoré majú zostať script layer



\---



\## 6. Dependency hygiene princíp



Treba explicitne rozdeliť:

\- Python runtime dependencies

\- Python dev/test dependencies

\- Node/app dependencies

\- optional automation tooling



Cieľ:

\- aby bolo jasné, čo je potrebné na ktorý scope

\- aby sa znížilo riziko, že sa všetko mieša dokopy



Zatiaľ bez veľkého zásahu.

Najprv inventory, potom úpravy.



\---



\## 7. CI kandidáti pre prvú vlnu



Prvé kandidáty do CI:



\### 1. Truth files exist

\- `source\_of\_truth/README.md`

\- `source\_of\_truth/master\_state.md`

\- `source\_of\_truth/chat\_roles.md`

\- `source\_of\_truth/project\_truth.json`

\- `source\_of\_truth/paths\_registry.json`

\- `source\_of\_truth/current\_issues.md`



\### 2. JSON valid

\- `project\_truth.json`

\- `paths\_registry.json`

\- ďalšie explicitné contract JSON súbory



\### 3. Forbidden artifact checks

\- `node\_modules` nesmie byť tracked

\- `.venv` nesmie byť tracked

\- zjavný temp/cache bordel nemá byť tracked



\### 4. Basic script smoke

Len na bezpečných skriptoch, kde nehrozí drahý runtime.



\---



\## 8. Čo zatiaľ nepackageovať nasilu



Zatiaľ netlačiť nasilu do package formy:

\- jednorazové research skripty

\- riskantné runners s krehkými importami

\- scripts, ktoré sú ešte silno viazané na lokálnu štruktúru a outputs



Najprv zlepšiť disciplínu, až potom package.



\---



\## 9. Prvé konkrétne deliverables po tomto dokumente



1\. `dependency\_hygiene\_plan.md`

2\. prvý hygiene test script pre truth integrity

3\. druhý hygiene test script pre forbidden tracked artifacts

4\. až potom základný CI workflow návrh



\---



\## 10. Success criteria



Packaging a CI smer je pripravený, keď:

\- repo má jasné boundary pravidlá

\- existuje inventory dôležitých vrstiev

\- existujú aspoň 2–3 rýchle hygiene testy

\- existuje minimálny CI plán

\- nie je potrebný veľký riskantný refactor naraz

