\# Registry Workflow



Tento súbor definuje, ako majú segmentované chaty čítať repo, outputs a source-of-truth vrstvu.



\## Cieľ

Chaty nemajú fungovať len z pamäte.

Majú sa orientovať podľa repa a centrálnej evidencie.



\## Povinné poradie čítania

Každý chat má pri execution / analysis / validation workflowe ísť v tomto poradí:



1\. `source\_of\_truth/README.md`

2\. `source\_of\_truth/master\_state.md`

3\. `source\_of\_truth/chat\_roles.md`

4\. `source\_of\_truth/project\_truth.json`

5\. `source\_of\_truth/paths\_registry.json`

6\. `source\_of\_truth/current\_issues.md`

7\. `canonical/script\_registry.json`

8\. `canonical/output\_registry.json`

9\. až potom konkrétne `scripts/`, `outputs/`, `tests/` a ďalšie repo súbory



\## Interpretácia vrstiev



\### 1. Repo

Repo obsahuje:

\- kódy

\- outputs

\- testy

\- manifests

\- pomocné súbory



Repo samo o sebe nie je automaticky official truth.



\### 2. `source\_of\_truth/`

`source\_of\_truth/` je jediný official SSOT.



Platí:

\- keď je konflikt medzi raw outputom a `source\_of\_truth`, official truth je `source\_of\_truth`

\- zmena v `source\_of\_truth` sa nemá robiť ticho ani implicitne

\- nie každý report, output alebo forensic verdict je automaticky official truth



\### 3. `canonical/`

`canonical/` je navigačná vrstva medzi repo kódmi a truth vrstvou.



Používa sa na:

\- rýchle zistenie, ktorý script čo robí

\- aké outputs generuje

\- čo je decision-relevant

\- čo je support artifact

\- čo je active / legacy / deprecated



`canonical/` nie je náhrada za `source\_of\_truth`.



\### 4. `automation/`

`automation/` je execution a patch orchestration vrstva.



Smie:

\- vytvoriť run

\- uložiť run log

\- uložiť report

\- uložiť screenshot manifest

\- vytvoriť pending truth patch

\- uložiť approval record



Nesmie:

\- držať paralelnú truth vrstvu

\- robiť tichý zápis do `source\_of\_truth`



\## Ako má chat čítať kódy

Keď chat potrebuje pochopiť konkrétny script alebo output, má ísť takto:



1\. zistiť v `canonical/script\_registry.json`, či je script active a čo generuje

2\. zistiť v `canonical/output\_registry.json`, či output je decision-relevant alebo support-only

3\. až potom otvoriť konkrétny script a konkrétne outputs

4\. pri odpovedi jasne rozlišovať:

&#x20;  - raw output

&#x20;  - report

&#x20;  - pending truth

&#x20;  - official truth



\## Ako má chat zapisovať poznatky

Keď chat zistí dôležitý poznatok:



\### ak je to len pracovný výsledok

má vzniknúť:

\- report

\- manifest

\- execution note

\- forensic verdict

\- registry update



\### ak to má byť kandidát na official truth

má vzniknúť:

\- pending truth patch



\### ak to má byť official truth

musí prejsť:

\- approval loop

\- samostatný apply krok



\## Čo nesmie byť zamieňané



\### Nie je to isté:

\- raw CSV output

\- report

\- forensic verdict

\- approved patch

\- applied truth

\- official SSOT



\### Presné rozlíšenie:

\- `raw output` = technický výsledok scriptu

\- `report` = zhrnutie alebo auditný výstup

\- `pending truth patch` = návrh na zmenu truth vrstvy

\- `approved patch` = povolený kandidát na apply

\- `applied truth` = až vykonaný zápis do `source\_of\_truth`

\- `official truth` = aktuálny stav v `source\_of\_truth`



\## Zásady pre všetky chaty



\### Chat má:

\- čítať kódy z repo

\- čítať outputs z repo

\- čítať `source\_of\_truth`

\- používať `canonical` registry ako navigáciu

\- rešpektovať svoju rolu podľa `chat\_roles.md`



\### Chat nemá:

\- ignorovať `source\_of\_truth`

\- vymýšľať si current state bez opory v súboroch

\- robiť tichý rewrite `source\_of\_truth`

\- miešať support artifacts s official truth



\## Kedy aktualizovať registry



\### `canonical/script\_registry.json`

aktualizovať keď:

\- pribudne nový script

\- script sa premenuje

\- script sa stane deprecated

\- script začne generovať iné dôležité outputs



\### `canonical/output\_registry.json`

aktualizovať keď:

\- pribudne nový dôležitý output folder alebo file

\- zmení sa decision relevance outputu

\- output prejde do legacy/deprecated režimu



\## Default rozhodovacie pravidlo

Ak si chat nie je istý, či niečo je official truth:

\- má predpokladať, že nie

\- a má to brať len ako artifact / report / candidate input

\- kým to nie je explicitne premietnuté do `source\_of\_truth`



\## Praktický cieľ

Každý nový alebo segmentovaný chat má byť schopný:

\- rýchlo nájsť relevantné kódy

\- pochopiť, ktoré outputs sú dôležité

\- oddeliť reporty od official truth

\- pripraviť podklady pre ďalší rozhodovací krok

\- pokračovať bez chaosu a bez slepej závislosti na pamäti iných chatov

