\# MRV1 Repo Structure Manifest



\## Účel

Tento dokument definuje odporúčanú top-level štruktúru repa pre Market Regime v1.

Je to engineering hygiene manifest, nie product ani strategy dokument.



Cieľ:

\- znížiť chaos

\- oddeliť source code od generated output

\- zlepšiť orientáciu v repo

\- pripraviť repo na low-risk cleanup po fázach



\---



\## 1. Základný princíp



Každý top-level priečinok musí mať jasný účel.



Repo nesmie dlhodobo fungovať ako zmes:

\- source code

\- outputs

\- jednorazových scriptov

\- debug artefaktov

\- lokálnych experimentov



Ak niečo nemá jasný účel, nemá to byť top-level priečinok.



\---



\## 2. Odporúčané top-level vrstvy



\### `source\_of\_truth/`

Autoritatívny stav projektu.



Sem patria:

\- project truth

\- master state

\- chat roles

\- paths registry

\- current issues

\- ďalšie dlhodobo autoritatívne textové a JSON kontrakty



Pravidlo:

\- žiadne dočasné poznámky

\- žiadne debug výstupy

\- žiadne generated reporty



\---



\### `scripts/`

Spustiteľné skripty a runners.



Sem patria:

\- jednorazové aj dlhodobejšie Python entrypointy

\- orchestration wrappers

\- validation runners

\- maintenance skripty, ak ešte nemajú lepší domov



Pravidlo:

\- každý script má mať jasný názov

\- každý script má mať jasný input/output scope

\- scripts nemajú byť odkladisko náhodného bordelu



\---



\### `automation/`

Automatizačná infra vrstva.



Sem patria:

\- approvals

\- truth patch workflow

\- automation tools

\- automation run logs

\- automation reports



Pravidlo:

\- automation kód oddeliť od strategy scriptov

\- runtime logy a reporty držať v konzistentnej podštruktúre

\- nenechať automation priečinok prerásť do všeobecného koša



\---



\### `outputs/`

Generated outputs behov a validácií.



Sem patria:

\- CSV exporty

\- summary výstupy

\- generated reports

\- charts

\- intermediate výstupy, ak sú súčasťou workflow



Pravidlo:

\- outputs nie sú source code

\- outputs nemajú obsahovať utility skripty

\- tmp/debug/cache vrstvy pod outputs necommitovať, ak nemajú trvalú hodnotu



\---



\### `tests/`

Minimálne smoke, integrity a neskôr unit/integration testy.



Sem patria:

\- source\_of\_truth integrity testy

\- repo structure smoke checks

\- export contract checks

\- script import/run smoke checks



Pravidlo:

\- testy majú najprv chrániť hygiene a reproducibility

\- nie je cieľ začať akademickým coverage divadlom



\---



\### `docs/` alebo root `.md` kontrakty

Dokumentácia a engineering kontrakty.



Sem patria:

\- repo hygiene pravidlá

\- structure manifest

\- naming pravidlá

\- packaging/deploy plán

\- test plán



Pravidlo:

\- dlhšie engineering dokumenty majú ísť postupne do `docs/`, ak ich pribudne viac

\- kým je ich málo, root markdown súbory sú akceptovateľné



\---



\### App/runtime/source priečinky

Produkčný alebo výskumný kód.



Presné názvy závisia od existujúcej reality repa.

Dôležité je pravidlo, nie konkrétny názov.



Pravidlo:

\- runtime/source kód nemá byť miešaný s outputs

\- helper utility nemajú byť schované medzi generated artefaktmi

\- research kód a infra kód majú byť čo najjasnejšie oddelené



\---



\## 3. Zakázané dlhodobé vzory



Tieto vzory sa majú postupne odstrániť:



\- top-level priečinky bez jasného účelu

\- skripty pomenované neinformatívne

\- utility skripty rozhádzané naprieč outputs

\- generated artefakty vedľa source code

\- dočasné fix skripty bez scope a bez životného cyklu

\- lokálne scratch súbory commitované do main repa



\---



\## 4. Rozhodovanie pri novom súbore



Pred pridaním nového súboru sa má rozhodnúť:



1\. Je to source code?

2\. Je to generated output?

3\. Je to automation infra?

4\. Je to test?

5\. Je to autoritatívny truth dokument?

6\. Je to len lokálny/dev artefakt?



Ak odpoveď nie je jasná, umiestnenie súboru ešte nie je pripravené.



\---



\## 5. Low-risk cleanup priority



\### Priorita A

Najprv zavrieť mantinely:

\- `.gitignore`

\- hygiene docs

\- naming pravidlá

\- structure manifest

\- tests skeleton



\### Priorita B

Potom low-risk presuny:

\- zjednotiť utility skripty

\- oddeliť automation tools od iných scriptov

\- upratať jednorazové helper skripty



\### Priorita C

Až potom execution cleanup:

\- obmedzenie hardcoded ciest

\- jednotné entrypoint pravidlá

\- config/path layer



\---



\## 6. Čo tento manifest zatiaľ nemení



Tento dokument sám o sebe nemení:

\- strategy truth

\- research verdicty

\- winner selection

\- app wording

\- produktové rozhodnutia



Je to len štrukturálny kontrakt pre engineering hygiene.



\---



\## 7. Enforcement pravidlo



Každý budúci cleanup krok má prejsť cez tieto otázky:

\- Je to low-risk?

\- Je to v engineering hygiene scope?

\- Zlepší to orientáciu a maintainability?

\- Nemieša to outputs so source code?

\- Nespôsobí to chaos vo workflow?



Ak nie, krok sa má zmenšiť alebo odložiť.

