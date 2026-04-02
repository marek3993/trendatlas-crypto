\# MRV1 Artifact Taxonomy



\## Účel

Tento dokument zavádza canonical artifact taxonomy pre Market Regime v1.



Cieľ:

\- oddeliť historical research chaos od canonical truth vrstvy

\- zabrániť miešaniu raw / summary / compare / manifest / decision / paper

\- zaviesť čisté artifact contracts

\- znížiť truth mismatch risk



\---



\## 1. Základný model



MRV1 má mať 2 paralelné vrstvy:



\### A. Historical / research layer

Účel:

\- zachovať auditnú stopu

\- nemať riskantný masový rename starých artifacts

\- nechať existujúce research outputs žiť



Pravidlo:

\- historical layer nie je automaticky canonical truth

\- historical artifacts nesmú byť zamieňané za official live/product truth bez canonical wrappera



\### B. Canonical / product truth layer

Účel:

\- držať čistú, zrozumiteľnú, stabilnú vrstvu

\- poskytovať oficiálne artifacts pre downstream čítanie

\- zjednotiť názvy, truth status a lineage



Pravidlo:

\- downstream spotrebitelia majú preferovať canonical layer

\- canonical layer je jediný preferovaný zdroj pre official/product-facing truth



\---



\## 2. Historical / research artifact types



\### `raw`

Priamy výstup scriptu alebo runu bez interpretácie.



Príklady:

\- raw csv export

\- raw validation table

\- raw intermediate dataset



Pravidlo:

\- raw artifact nie je decision

\- raw artifact nie je official truth len preto, že existuje



\---



\### `summary`

Zhrnutie jedného runu alebo jednej varianty.



Príklady:

\- leverage summary

\- shortlist summary

\- experiment summary



Pravidlo:

\- summary je interpretovaný výstup jedného scope

\- summary nesmie hrať rolu compare alebo decision artefaktu



\---



\### `compare`

Porovnanie viacerých behov, variantov alebo baseline.



Príklady:

\- vs baseline compare table

\- candidate comparison export

\- multi-run comparison summary



Pravidlo:

\- compare artifact má hovoriť o rozdieloch

\- compare artifact sám osebe ešte nie je official decision



\---



\### `manifest`

Opis artifact setu, run setu, lineage, contractu alebo paths.



Príklady:

\- run manifest

\- artifact manifest

\- export manifest



Pravidlo:

\- manifest neobsahuje product verdict

\- manifest hovorí čo existuje, z čoho vzniklo a ako sa má čítať



\---



\### `decision`

Explicitný verdict alebo freeze rozhodnutie.



Príklady:

\- official baseline freeze

\- leverage truth adoption

\- winner adoption decision



Pravidlo:

\- decision artifact musí byť explicitný

\- decision nesmie byť schovaný v summary, paper alebo compare súbore



\---



\### `paper`

Human-readable interpretačný dokument.



Príklady:

\- methodology note

\- forensic writeup

\- interpretácia výsledkov



Pravidlo:

\- paper môže vysvetľovať

\- paper nesmie byť jediný nosič official truth bez paired decision/manifests



\---



\## 3. Canonical artifact types



\### `canonical\_snapshot`

Aktuálny oficiálny stav domény.



Príklady:

\- current strategy state

\- current universe state

\- current leverage state

\- current product export state



\---



\### `canonical\_manifest`

Canonical contract pre doménu alebo artifact set.



Musí vedieť povedať:

\- čo je artifact

\- aký má typ

\- aký má truth status

\- z čoho vznikol

\- kto ho má čítať



\---



\### `canonical\_export`

Čistý downstream export určený na čítanie app/product/runtime vrstvou.



Príklady:

\- product metrics export

\- app-facing export

\- official benchmark export



\---



\### `canonical\_decision`

Oficiálne rozhodnutie meniace truth.



Príklady:

\- official strategy decision

\- official leverage decision

\- official universe decision



\---



\### `canonical\_reference`

Schválený referenčný artifact, ktorý nie je live official state, ale je povolený ako stabilný referenčný bod.



Príklady:

\- frozen 66G reference

\- frozen BTC benchmark reference



\---



\## 4. Artifact domains



Canonical artifacts majú patriť do malej množiny truth domén:



\- `strategy`

\- `universe`

\- `leverage`

\- `product`

\- `benchmark`

\- `artifacts`

\- `lineage`



Pravidlo:

\- nezavádzať zbytočne veľa truth domén

\- doména má byť stabilná a čitateľná



\---



\## 5. Zakázané miešanie rolí



Tieto stavy sú hygiene problém:



\- summary, ktoré sa tvári ako decision

\- compare súbor, z ktorého sa neoficiálne číta winner truth

\- paper, ktorý je jediným nosičom oficiálneho verdiktu

\- manifest, ktorý potichu mení truth

\- reference artifact, ktorý sa tvári ako current live state

\- raw output, ktorý je omylom použitý ako product export



\---



\## 6. Canonical consumption rule



Downstream konzumenti majú čítať v poradí priority:



1\. canonical decision

2\. canonical snapshot

3\. canonical manifest

4\. canonical export

5\. canonical reference



Historical/research layer má byť:

\- auditná

\- pomocná

\- forenzná

\- nie primary product truth source



\---



\## 7. Artifact minimum metadata



Každý budúci canonical artifact má mať aspoň:



\- `artifact\_name`

\- `artifact\_type`

\- `truth\_domain`

\- `truth\_status`

\- `effective\_date`

\- `producer`

\- `source\_run`

\- `upstream\_artifacts`

\- `consumer\_scope`



\---



\## 8. Phase adoption pravidlo



Historické artifacts sa nemusia celé premenovať.

Namiesto toho:

\- nechaj historical layer žiť

\- nad ňou vytvor canonical layer

\- postupne mapuj historical artifacts do canonical manifests a decisions



To je preferovaný low-risk prístup.



\---



\## 9. Cieľ taxonomy



Po zavedení taxonomy má byť jasné:

\- čo je historical

\- čo je canonical

\- čo je raw

\- čo je summary

\- čo je compare

\- čo je manifest

\- čo je decision

\- čo je paper

\- čo je official truth

\- čo je len reference

