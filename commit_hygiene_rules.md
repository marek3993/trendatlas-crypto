\# Commit Hygiene Rules



\## 1. Účel

Tento dokument určuje, ako sa majú deliť commity v projekte Market Regime v1, aby sa nemiešali segmenty, truth vrstva a generated artifacts.



\---



\## 2. Základné pravidlo

Jeden commit = jedna téma + jeden jasný dôvod.



Commit nesmie naraz miešať:

\- engineering hygiene

\- AI LAB research mutation/policy zmeny

\- DATA refresh / downloader zmeny

\- APP UI / wording zmeny

\- forensic audit výsledky

\- truth apply zmeny

\- generated runtime outputs



\---



\## 3. Povolené commit typy



\### 3.1 Hygiene commit

Obsahuje len:

\- contracts

\- naming docs

\- taxonomy docs

\- guardrail tests

\- repo discipline docs

\- low-risk structural cleanup



Príklady:

\- `repo\_artifact\_contract.md`

\- `tests/...`

\- canonical contract docs

\- harmless schema/template hygiene



\### 3.2 Truth commit

Obsahuje len:

\- explicitné zmeny v `source\_of\_truth/`

\- prípadne minimálny support file priamo potrebný k apply flow



Pravidlo:

\- truth commit nesmie byť zamiešaný s random outputs alebo research logs



\### 3.3 Canonical commit

Obsahuje len:

\- `canonical/decisions/`

\- `canonical/references/`

\- `canonical/manifests/`

\- `canonical/exports/`

\- prípadné guardrails priamo k nim



\### 3.4 AI LAB commit

Obsahuje len:

\- AI LAB policies

\- ideation/spec generator scripts

\- explicitne schválené research\_os control changes



Runtime outputs a runs sa defaultne necommitujú len preto, že vznikli.



\### 3.5 DATA / execution commit

Obsahuje len:

\- downloader

\- refresh

\- execution plumbing

\- deterministic input/output mapping

\- manifests a contracts priamo patriace do DATA/execution scope



\### 3.6 APP commit

Obsahuje len:

\- `app.py`

\- dashboard/UI

\- app export mapping

\- wording/text/layout



\---



\## 4. Čo sa nesmie miešať



\### Zakázané kombinácie v jednom commite

\- `source\_of\_truth/` + `outputs/...`

\- hygiene tests + AI LAB runtime outputs

\- APP UI + DATA downloader changes

\- forensic CSV audit + research ideation policy changes

\- automation screenshots/logs + official truth change

\- generated research\_os runs + canonical decision files



\---



\## 5. Generated artifacts pravidlá



\### 5.1 Default pravidlo

Generated artifacts sa necommitujú automaticky.



Sem patria najmä:

\- logy

\- queue files

\- screenshots

\- run folders

\- temporary manifests

\- repeated promotion decisions

\- transient summaries

\- runtime-only diagnostics



\### 5.2 Kedy sa generated artifact smie commitnúť

Len ak:

\- je to explicitne dohodnutý audit artifact

\- je to required workflow contract

\- je to pinned canonical/export/reference support artifact

\- alebo to príslušný segment výslovne chce ako artefakt histórie



\---



\## 6. Truth safety pravidlá



\### 6.1 Official truth

Official truth je len v `source\_of\_truth/`.



\### 6.2 Approved patch nie je truth

\- pending patch != approved patch

\- approved patch != applied truth

\- applied truth je až po reálnom zápise do `source\_of\_truth/`



\### 6.3 Commit message disciplína

Commit message má hovoriť:

\- čo sa zmenilo

\- v akej vrstve

\- bez marketingových viet

\- bez lživého scope



Príklady:

\- `Add repo artifact contract`

\- `Add automation apply path and file hygiene tests`

\- `Fix script registry required field guardrail`



\---



\## 7. Praktické split pravidlá



\### Ak je dirty state mixed:

1\. najprv rozdeliť podľa segmentu

2\. odložiť generated outputs bokom

3\. commitnúť len smallest clean scope

4\. až potom riešiť ďalší segment



\### Ak nie je čistý commit scope:

\- necommitovať

\- najprv rozseknúť scope



\---



\## 8. Minimum pred commitom

Pred každým commitom má byť jasné:

\- čo je scope

\- prečo to patrí do jedného commitu

\- čo musí zostať mimo

\- či sa nemení official truth

\- či sa nemiešajú generated outputs s contracts/truth vrstvou



\---



\## 9. Readability pravidlo

Profesionálny človek má vedieť z posledných commitov pochopiť:

\- čo bol hygiene krok

\- čo bol truth krok

\- čo bol AI LAB krok

\- čo bol DATA/execution krok

\- čo bol APP krok



Ak to z histórie nevidno, commit split je zlý.



\---



\## 10. Default stop rule

Ak je pochybnosť:

\- necommitovať mixed state

\- najprv určiť scope

\- generated outputs brať defaultne ako “stay out”

