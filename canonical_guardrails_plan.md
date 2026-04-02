\# MRV1 Canonical Guardrails Plan



\## Účel

Tento dokument definuje guardrails plán pre canonical layer.



Cieľ:

\- znížiť truth mismatch risk

\- zabrániť čítaniu historical chaosu ako official truth

\- pripraviť minimálne validačné pravidlá bez veľkého refactoru



\---



\## 1. Základný princíp



Canonical layer musí byť:

\- explicitná

\- malá

\- auditovateľná

\- strojovo čitateľná

\- nadradená historical outputs pri downstream čítaní



Historical layer:

\- ostáva zachovaná

\- slúži ako auditná a research vrstva

\- nesmie byť implicitný product truth source



\---



\## 2. Guardrail kategórie



\### A. Truth guardrails

Kontrolujú:

\- či official decision existuje

\- či official snapshot sedí s decision

\- či reference artifacts nie sú označené ako official



\### B. Lineage guardrails

Kontrolujú:

\- či canonical artifacts majú minimálne lineage fields

\- či upstream artifacts dávajú zmysel

\- či decision/snapshot/export nevznikli bez čitateľného pôvodu



\### C. Consumption guardrails

Kontrolujú:

\- či downstream source nemieri priamo na historical compare/summary/raw outputs

\- či canonical export contract neumožňuje zakázané source typy



\### D. Naming guardrails

Kontrolujú:

\- či canonical názvy dodržiavajú canonical naming convention

\- či historical artifacts nie sú omylom označené canonical prefixom



\---



\## 3. Prvá vlna guardrails



\### Guardrail 1 — Decision/snapshot consistency

Overiť:

\- `canonical\_strategy\_decision.json`

\- `canonical\_strategy\_snapshot.json`



Pravidlo:

\- strategy baseline

\- universe winner

\- product direction

\- live leverage truth



musia byť konzistentné medzi decision a snapshot vrstvou.



\---



\### Guardrail 2 — Reference vs official separation

Overiť:

\- `canonical\_66g\_reference.json`

\- `canonical\_benchmark\_reference.json`



Pravidlo:

\- reference artifacts nesmú mať `truth\_status = official`

\- reference artifacts nesmú tvrdiť, že sú current live state



\---



\### Guardrail 3 — Lineage minimum completeness

Overiť na všetkých canonical JSON artifacts:

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



\### Guardrail 4 — Canonical naming enforcement

Overiť:

\- canonical files začínajú `canonical\_`

\- patria do správneho canonical folderu

\- type/domain v názve zodpovedá obsahu



\---



\### Guardrail 5 — Product export source discipline

Overiť:

\- canonical product export contract nepovolí direct read z historical compare/summary/raw outputs



\---



\## 4. Druhá vlna guardrails



\### A. Universe decision separation

Kontrola:

\- universe truth nie je zamenená s baseline reference truth



\### B. Leverage deployment separation

Kontrola:

\- leverage experiment artifacts nie sú interpretované ako live leverage truth



\### C. Paper vs machine truth checks

Kontrola:

\- paper text nemá byť jediný nosič official truth



\---



\## 5. Low-risk implementačný princíp



Guardrails sa majú robiť takto:

1\. najprv plan

2\. potom 1–2 malé validačné skripty

3\. potom rozšírenie pravidiel

4\. bez zásahu do strategy logic



Nie:

\- big bang validator všetkého naraz

\- refactor historical vrstvy bez mantinelov



\---



\## 6. Najbližšie implementačné deliverables



\### TODO

\- `tests/test\_canonical\_lineage\_minimum.py`

\- `tests/test\_canonical\_truth\_consistency.py`

\- `tests/test\_canonical\_reference\_separation.py`



\---



\## 7. Success criteria



Canonical guardrails vrstva je použiteľná, keď:

\- official canonical JSON artifacts prejdú minimum checks

\- reference artifacts sa nepletú s official truth

\- decision a snapshot vrstvy sú konzistentné

\- downstream layer má jasné read rules

