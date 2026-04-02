\# MRV1 Naming Discipline



\## Účel

Tento dokument zavádza minimálnu naming disciplínu pre Market Regime v1.



Cieľ:

\- znížiť chaos

\- zlepšiť orientáciu

\- zlepšiť maintainability

\- znížiť počet nejasných alebo duplictných scriptov



\---



\## 1. Základné pravidlo



Názov súboru má hovoriť:

\- čo to je

\- čo to robí

\- aký má scope



Názov nemá byť len:

\- dočasný

\- emočný

\- nejasný

\- generický



\---



\## 2. Zakázané štýly názvov



Nepoužívať názvy typu:

\- `test.py`

\- `run.py`

\- `script.py`

\- `helper.py`

\- `final.py`

\- `final\_new.py`

\- `fix.py`

\- `tmp.py`

\- `tmp2.py`

\- `new\_script.py`



Dôvod:

\- nulová informačná hodnota

\- vysoké riziko duplicít

\- zlá orientácia pri raste repa



\---



\## 3. Preferovaný naming pattern



Preferovaný pattern má byť:



`<domain>\_<action>\_<scope>.py`



Podľa potreby:



`<domain>\_<action>\_<scope>\_v1.py`



Použiť len keď verzia naozaj dáva zmysel.



\---



\## 4. Odporúčané doménové prefixy



Príklady prefixov:

\- `phase66g\_`

\- `phase67j\_`

\- `phase68f\_`

\- `research\_os\_`

\- `automation\_`

\- `app\_`

\- `truth\_`

\- `validate\_`

\- `refresh\_`

\- `export\_`



Pravidlo:

\- prefix má povedať, do akej oblasti script patrí

\- nemá byť náhodný ani skrátený do nečitateľnej formy



\---



\## 5. Action časť názvu



Action má pomenovať hlavnú činnosť.



Dobré príklady:

\- `refresh`

\- `validate`

\- `export`

\- `build`

\- `generate`

\- `run`

\- `summarize`

\- `compare`

\- `approve`

\- `create`



Zlé príklady:

\- `do`

\- `make`

\- `thing`

\- `work`

\- `stuff`



\---



\## 6. Scope časť názvu



Scope má hovoriť, na čo presne sa script vzťahuje.



Dobré príklady:

\- `source\_of\_truth\_integrity`

\- `autonomous\_loop\_runner`

\- `tradable\_basis`

\- `production\_soft\_filters`

\- `workflow\_run\_first\_safe\_run`



Zlé príklady:

\- `main`

\- `new`

\- `final`

\- `better`

\- `fixed`



\---



\## 7. Markdown / JSON / config naming



Pre markdown, json a config súbory platí rovnaký princíp:

\- názov musí byť explicitný

\- názov má popisovať contract alebo účel



Dobré príklady:

\- `repo\_hygiene\_contract.md`

\- `repo\_structure\_manifest.md`

\- `naming\_discipline.md`

\- `project\_truth.json`

\- `paths\_registry.json`



Zlé príklady:

\- `notes.md`

\- `misc.md`

\- `config2.json`

\- `new.json`



\---



\## 8. Version suffix disciplína



Suffix typu `\_v1`, `\_v2` používať len keď:

\- existuje paralelná verzia so skutočne odlišným contractom

\- je to dočasne potrebné pre bezpečný prechod

\- staršia verzia ešte stále musí žiť



Nepoužívať `\_v2`, `\_final`, `\_final2`, `\_real\_final`.



\---



\## 9. Jednorazové skripty



Ak je script jednorazový, názov to má stále hovoriť normálne.

Aj jednorazový script musí byť čitateľný.



Dobré:

\- `phase68f\_realistic\_leverage\_validation\_tradable\_basis.py`



Zlé:

\- `oneoff\_fix.py`

\- `quick\_patch.py`



Ak jednorazový script stratí hodnotu, má sa neskôr archivovať alebo odstrániť.

Pri odstránení treba explicitne uviesť čo sa odstraňuje a prečo.



\---



\## 10. Duplicitné názvy a skoro-duplicitné názvy



Treba sa vyhýbať stavom, kde existuje viac súborov ako:

\- `validate\_truth.py`

\- `validate\_truth\_new.py`

\- `validate\_truth\_final.py`



To je hygiene zlyhanie.



Správny postup:

\- buď jeden jasný názov

\- alebo explicitne verzovaný/priestorovo oddelený názov podľa scope



\---



\## 11. Function a variable naming minimum



Aj keď tento dokument rieši hlavne súbory, platí minimum aj pre vnútro kódu:

\- žiadne `x`, `data2`, `tmp`, `res\_final`

\- názvy majú byť explicitné

\- constants majú byť jasne odlíšené

\- magic správanie má mať pomenovanie, nie skrytý význam



\---



\## 12. Enforcement



Pred vytvorením nového súboru sa má overiť:

\- je názov deskriptívny?

\- je z názvu jasná doména?

\- je z názvu jasná akcia?

\- je z názvu jasný scope?

\- nehrozí duplicita s existujúcim scriptom?



Ak nie, názov ešte nie je hotový.

