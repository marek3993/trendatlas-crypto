\# Artifact Status Rules



\## 1. Účel

Tento dokument určuje, aký status môže mať artefakt v projekte Market Regime v1 a čo z toho prakticky vyplýva.



Cieľ:

\- znížiť truth mismatch

\- zjednodušiť audit

\- oddeliť current truth od reference a raw outputov

\- zabrániť tomu, aby sa generated artifacts tvárili ako official stav



\---



\## 2. Základný princíp

Nie každý dôležitý súbor je official truth.



Artefakt môže byť:

\- official

\- reference

\- generated

\- support\_only

\- deprecated

\- retired



Status musí hovoriť:

\- ako sa artefakt smie čítať

\- či sa smie použiť ako current truth

\- či je určený pre product/app/master čítanie

\- či je len audit/runtime pomocný



\---



\## 3. Status: official



\### Definícia

Artefakt reprezentuje aktuálny oficiálny stav projektu.



\### Typické miesto

\- `source\_of\_truth/`

\- výnimočne canonical artifact explicitne určený ako official decision/export carrier



\### Pravidlá

\- smie byť čítaný ako current truth

\- smie byť použitý pre downstream product/app/master interpretáciu

\- musí mať jasný lineage a ownership

\- nesmie byť v konflikte so `source\_of\_truth`



\### Praktický význam

Keď chce niekto vedieť „ako to teraz naozaj je“, má skončiť tu.



\---



\## 4. Status: reference



\### Definícia

Artefakt je referenčný anchor, benchmark, pinned baseline alebo historical comparison point.



\### Typické miesto

\- `canonical/references/`



\### Pravidlá

\- smie byť čítaný ako porovnávací bod

\- nesmie sa tváriť ako current live truth

\- smie byť app/product-readable len ako reference context

\- musí mať explicitne napísané:

&#x20; - na čo sa smie použiť

&#x20; - na čo sa nesmie použiť



\### Praktický význam

Pomáha porovnávať, ale nerozhoduje o tom, čo je teraz pravda.



\---



\## 5. Status: generated



\### Definícia

Artefakt vznikol automaticky zo scriptu, runu, agenta alebo pipeline.



\### Typické miesto

\- `outputs/`

\- `research\_os/experiment\_specs/generated/`

\- `research\_os/runs/`

\- runtime output folders



\### Pravidlá

\- môže byť decision-relevant

\- nie je official truth

\- defaultne sa nemá interpretovať ako current state

\- commitovať sa má len ak je to výslovne potrebné



\### Praktický význam

Je to výsledok behu, nie finálna pravda.



\---



\## 6. Status: support\_only



\### Definícia

Artefakt existuje len ako pomocný workflow alebo audit support.



\### Typické miesto

\- `automation/reports/`

\- `automation/screenshots/`

\- `automation/tasks/`

\- logy

\- queue files

\- approval records

\- run manifests, ak sú iba orchestration support



\### Pravidlá

\- nesmie byť source pre current truth

\- nemá byť default read path pre MASTER / app / product

\- drží audit trail alebo orchestration informácie



\### Praktický význam

Pomáha procesu, ale nehovorí „čo je pravda“.



\---



\## 7. Status: deprecated



\### Definícia

Artefakt je starý, superseded alebo už nemá byť používaný ako bežný read path.



\### Typické miesto

\- historické canonical files

\- staré export contracts

\- staré manifests

\- staré reports



\### Pravidlá

\- môže zostať v repo kvôli histórii

\- nemá byť defaultne čítaný

\- nový consumer má ísť na novší artifact

\- ak existuje náhrada, má byť explicitne uvedená cez `supersedes` alebo equivalent rule



\### Praktický význam

Zachované kvôli histórii, nie kvôli aktuálnemu používaniu.



\---



\## 8. Status: retired



\### Definícia

Artefakt alebo celá línia je úmyselne uzavretá a nemá sa ďalej používať bez nového explicitného rozhodnutia.



\### Typické miesto

\- retired strategy line records

\- retired mutation families

\- retired automation paths

\- retired research branches



\### Pravidlá

\- nesmie sa znova aktivovať potichu

\- reopen len cez nové explicitné rozhodnutie

\- reason retired má byť zapísaný



\### Praktický význam

Nie „staré a zaprášené“, ale „vedome vypnuté“.



\---



\## 9. Povolené interpretácie podľa statusu



\### official

Povolené:

\- current truth read

\- downstream app/product read

\- MASTER summary read



\### reference

Povolené:

\- benchmark read

\- comparison read

\- context read



Zakázané:

\- current live truth read



\### generated

Povolené:

\- audit read

\- experiment evaluation

\- decision support



Zakázané:

\- direct official truth read bez promotion/apply flow



\### support\_only

Povolené:

\- workflow audit

\- debugging

\- orchestration trail



Zakázané:

\- business truth read

\- product-facing truth read



\### deprecated

Povolené:

\- historical lookup

\- migration support



Zakázané:

\- default read path



\### retired

Povolené:

\- historical reference

\- audit explanation



Zakázané:

\- active use bez reopen decision



\---



\## 10. Status vs commitovanie



\### Official

Commitovať áno, opatrne, samostatne.



\### Reference

Commitovať áno, keď je súčasťou canonical layer alebo pinned benchmark contractu.



\### Generated

Commitovať len selektívne a len keď je to dohodnutý artifact.



\### Support\_only

Defaultne necommitovať len preto, že vznikol.



\### Deprecated

Necommitovať ako nový default path.

Len ak ide o migration/cleanup krok.



\### Retired

Commitovať áno, ak dokumentuje explicitný retire decision alebo retire contract.



\---



\## 11. Status vs directory contract



\### source\_of\_truth

Default status:

\- official



\### canonical/decisions

Default status:

\- official alebo explicit decision carrier



\### canonical/references

Default status:

\- reference



\### canonical/manifests

Default status:

\- official contract support alebo reference support podľa obsahu



\### canonical/exports

Default status:

\- official downstream contract support



\### outputs

Default status:

\- generated



\### automation

Default status:

\- support\_only



\### research\_os generated/runs/promotion\_queue

Default status:

\- generated alebo support\_only



\---



\## 12. Status escalation rule



Generated artefakt sa nestáva official tým, že:

\- je pekný

\- je dôležitý

\- je schválený v hlave

\- existuje approval record

\- existuje report



Generated artefakt sa stáva official až keď:

1\. existuje explicitné rozhodnutie

2\. je vykonaný truth promotion/apply flow

3\. zmena je zapísaná do `source\_of\_truth/`



\---



\## 13. Status downgrade rule



Ak current official artefakt prestane byť platný:

\- nesmie zostať ticho “official”

\- musí byť buď:

&#x20; - superseded

&#x20; - deprecated

&#x20; - retired



\---



\## 14. Practical reading rule



Keď čítaš repo:

1\. najprv hľadaj official

2\. potom decision

3\. potom reference

4\. až potom generated/support artifacts



Ak čítaš generated artifact ako keby bol official, čítaš repo zle.



\---



\## 15. Short default map



\- `source\_of\_truth/\*` = official

\- `canonical/decisions/\*` = official decision carrier

\- `canonical/references/\*` = reference

\- `canonical/manifests/\*` = contract/index support

\- `canonical/exports/\*` = official export support

\- `outputs/\*` = generated

\- `automation/\*` = support\_only

\- `research\_os/runs/\*` = generated

\- `research\_os/promotion\_queue/\*` = support\_only alebo generated support

