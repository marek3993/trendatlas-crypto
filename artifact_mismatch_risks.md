\# MRV1 Artifact Mismatch Risks



\## Účel

Tento dokument mapuje hlavné artifact mismatch riziká v MRV1.



Cieľ:

\- explicitne pomenovať najnebezpečnejšie confusion patterns

\- znížiť risk, že app, product alebo ďalší chat číta nesprávnu pravdu

\- pripraviť guard scripts a forensic audit backlog



\---



\## Risk model



Artifact mismatch vzniká, keď:

\- názov artefaktu naznačuje inú rolu než skutočne má

\- downstream vrstva číta historical artifact ako canonical truth

\- textový dokument tvrdí niečo iné než machine-readable contract

\- compare alebo summary nahradí explicitný decision layer



\---



\## Hlavné riziká



\### 1. Summary → decision mismatch

Príčina:

\- summary artifact vyzerá ako konečný verdict



Dôsledok:

\- downstream číta summary ako official truth



Prevencia:

\- summary nikdy nesmie byť jediný truth carrier

\- official truth má byť v canonical decision/snapshot



Riziko:

\- vysoké



\---



\### 2. Compare → winner mismatch

Príčina:

\- compare output sa interpretuje ako final adoption



Dôsledok:

\- winner truth sa číta z compare tabuľky namiesto decision artefaktu



Prevencia:

\- compare len porovnáva

\- decision explicitne rozhoduje



Riziko:

\- vysoké



\---



\### 3. Paper → machine truth mismatch

Príčina:

\- markdown alebo paper writeup tvrdí iný stav než machine-readable JSON



Dôsledok:

\- ľudia čítajú jedno, systém druhé



Prevencia:

\- paper musí byť paired s canonical decision/manifests

\- machine-readable truth je nadradený carrier



Riziko:

\- vysoké



\---



\### 4. Reference → official live state mismatch

Príčina:

\- reference artifact sa tvári ako current official truth



Dôsledok:

\- 66G reference alebo benchmark reference sa môže pliesť s live state



Prevencia:

\- truth\_status = reference

\- explicitné `is\_current\_live\_truth = false`, kde to dáva zmysel

\- oddelený reference folder



Riziko:

\- vysoké



\---



\### 5. Leverage experiment → live leverage mismatch

Príčina:

\- experimentálne leverage outputs sa čítajú ako live deployment truth



Dôsledok:

\- product alebo ďalší chat môže tvrdiť nesprávny live režim



Prevencia:

\- leverage decision držať explicitne canonical

\- experimenty označiť ako candidate/reference/exploratory



Riziko:

\- vysoké



\---



\### 6. Manifest → decision leakage

Príčina:

\- manifest začína niesť skrytý verdict namiesto čistej opisnej role



Dôsledok:

\- nie je jasné, či súbor opisuje alebo rozhoduje



Prevencia:

\- manifest len popisuje

\- decision rozhoduje



Riziko:

\- stredné až vysoké



\---



\### 7. Raw → export mismatch

Príčina:

\- raw alebo intermediate output je čítaný ako downstream export



Dôsledok:

\- app alebo reporting číta nečisté alebo nevalidované dáta



Prevencia:

\- canonical exports oddeliť od raw layer

\- export naviazať na manifest/decision



Riziko:

\- vysoké



\---



\### 8. Historical path → canonical truth mismatch

Príčina:

\- starý phase path je používaný priamo ako current product truth source



Dôsledok:

\- project truth sa stáva závislý na historickom chaose



Prevencia:

\- downstream čítanie presmerovať na canonical layer

\- historical artifacts ponechať ako upstream/audit layer



Riziko:

\- vysoké



\---



\## Najrizikovejšie domény



\### Strategy

\- baseline truth

\- universe truth

\- product direction

\- leverage truth



\### Benchmark

\- reference vs official confusion



\### Automation truth patches

\- risk, že workflow artifacts a approvals začnú byť čítané ako truth layer bez canonical contractu



\---



\## Risk priority



\### P1

\- summary vs decision

\- compare vs winner

\- reference vs official

\- leverage experiment vs live leverage truth



\### P2

\- paper vs machine truth

\- raw vs export

\- historical path vs canonical truth



\### P3

\- manifest leakage

\- naming ambiguity bez priameho downstream dopadu



\---



\## Najbližšie guard ciele



1\. canonical strategy snapshot

2\. canonical 66G reference contract

3\. canonical leverage decision contract

4\. neskôr mismatch validator:

&#x20;  - decision vs snapshot

&#x20;  - reference vs official

&#x20;  - export vs manifest



\---



\## Záver



MRV1 nepotrebuje hneď premenovať celú históriu.

Potrebuje:

\- čistú canonical vrstvu

\- explicitné truth statusy

\- explicitné lineage

\- explicitné decision carriers

\- guard rails proti artifact confusion

