\# MRV1 Truth Status Model



\## Účel

Tento dokument zavádza truth status model pre artifacts a truth-bearing outputs v MRV1.



Cieľ:

\- zabrániť miešaniu exploratory a official truth

\- znížiť mismatch risk

\- zaviesť explicitný status artefaktov

\- zlepšiť forensic auditability



\---



\## 1. Povinný truth status



Každý budúci canonical artifact musí mať explicitný `truth\_status`.



Odporúčaný uzavretý set:



\- `exploratory`

\- `candidate`

\- `reference`

\- `official`

\- `deprecated`

\- `superseded`



\---



\## 2. Význam statusov



\### `exploratory`

Artifact vznikol pri výskume alebo analýze.

Nie je určený ako official truth.



Použitie:

\- experimentálne porovnania

\- pracovné outputs

\- predbežné zistenia



\---



\### `candidate`

Artifact je vážny kandidát na adoption, ale ešte nie je official.



Použitie:

\- pre-approval outputs

\- finalist compare results

\- pending decisions



\---



\### `reference`

Artifact je schválený ako stabilný referenčný bod, ale nie je current official live state.



Použitie:

\- frozen baseline

\- benchmark reference

\- approved historical comparison anchor



\---



\### `official`

Artifact je aktuálny oficiálny truth carrier pre danú doménu.



Použitie:

\- current strategy truth

\- current universe truth

\- current leverage truth

\- current product export truth



\---



\### `deprecated`

Artifact sa už nemá používať na nové čítanie, ale ešte nebol formálne nahradený presným successorom.



Použitie:

\- starý contract

\- zastaraný export

\- starý naming model



\---



\### `superseded`

Artifact bol nahradený novším artifactom a už nie je aktívny truth carrier.



Použitie:

\- starý canonical decision

\- starý canonical snapshot

\- starý export po replace kroku



\---



\## 3. Truth status rules



\### Rule 1

Historical artifacts môžu mať truth status, ale nesmú byť automaticky považované za official.



\### Rule 2

Canonical artifact bez `truth\_status` je nekompletný.



\### Rule 3

Na jednu truth doménu má byť v jednom čase maximálne jeden aktívny `official` snapshot/decision pair, ak contract nehovorí inak.



\### Rule 4

`reference` artifact nesmie byť vydávaný za current live truth.



\### Rule 5

`candidate` artifact nesmie byť čítaný downstream product vrstvou ako official.



\---



\## 4. Povinné metadata pre truth-bearing artifacts



Minimum:

\- `artifact\_name`

\- `truth\_domain`

\- `artifact\_type`

\- `truth\_status`

\- `effective\_date`

\- `producer`

\- `source\_run`

\- `upstream\_artifacts`

\- `supersedes`

\- `consumer\_scope`



\---



\## 5. Truth-bearing artifact families



Najmä tieto artifact types nesú truth riziko:

\- decision

\- snapshot

\- manifest

\- export

\- reference



Najvyššie riziko majú:

\- decision

\- snapshot

\- export



Preto musia mať najvyššiu disciplínu.



\---



\## 6. Mismatch risk model



Najčastejšie mismatch riziká:



\### A. Decision mismatch

Decision artifact tvrdí niečo iné než snapshot.



\### B. Snapshot mismatch

Snapshot tvrdí iný current state než export.



\### C. Reference misuse

Reference artifact je omylom čítaný ako official.



\### D. Compare misuse

Compare output je omylom interpretovaný ako final decision.



\### E. Paper mismatch

Paper text tvrdí iný verdict než machine-readable decision.



\---



\## 7. Enforcement pravidlo



Každý nový canonical truth artifact sa má pýtať:

\- je official, candidate alebo reference?

\- čo presne superseduje?

\- kto ho má čítať?

\- z akého runu vznikol?

\- je to naozaj decision, snapshot alebo export?



Ak toto nie je jasné, artifact contract nie je hotový.



\---



\## 8. Cieľ truth status modelu



Po zavedení modelu má byť jasné:

\- čo je exploratory

\- čo je candidate

\- čo je reference

\- čo je official

\- čo je deprecated

\- čo je superseded



A hlavne:

\- čo smie čítať product/app layer

\- čo je len auditná alebo research vrstva

