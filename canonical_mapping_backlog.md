\# MRV1 Canonical Mapping Backlog



\## Účel

Tento dokument je backlog pre mapovanie historických research artifacts do čistej canonical vrstvy.



Cieľ:

\- nemať big bang rename

\- nemať chaos pri product truth čítaní

\- postupne zavádzať canonical aliasy, manifests a decisions

\- držať historical layer auditne zachovanú



\---



\## Základné pravidlo



Historical artifacts:

\- môžu zostať na mieste

\- nemusia byť hromadne premenované

\- nesmú byť bez explicitného rozhodnutia považované za canonical truth



Canonical layer:

\- má byť malá

\- má byť stabilná

\- má byť downstream-readable

\- má explicitne mapovať historical upstream inputs



\---



\## Stavové značky



\- `TODO`

\- `ACTIVE`

\- `BLOCKED`

\- `DONE`



\---



\## Mapping typy



\### `alias\_to\_canonical`

Historical artifact zostáva zachovaný, ale získa canonical mapping cez manifest/decision/reference.



\### `reference\_only`

Artifact je povolený len ako reference, nie ako official current truth.



\### `official\_input`

Artifact je upstream input pre canonical decision/snapshot/export.



\### `deprecated\_historical`

Artifact ostáva v histórii, ale nemá sa ďalej používať ako downstream source.



\### `needs\_forensic\_review`

Artifact alebo artifact family má vysoké riziko mismatchu a potrebuje audit.



\---



\## Prioritné domény



\### 1. Strategy truth

Cieľ:

\- jasne oddeliť baseline truth, universe truth, leverage truth a product direction



Stav:

\- bootstrap canonical decision existuje



Ďalšie kroky:

\- vytvoriť explicitný strategy snapshot

\- namapovať historical inputs do manifestu



Status:

\- `TODO`



\---



\### 2. Benchmark reference

Cieľ:

\- držať BTC benchmark ako reference, nie ako zamaskovaný winner truth



Stav:

\- bootstrap canonical benchmark reference existuje



Ďalšie kroky:

\- doplniť prípadné export/reference files

\- doplniť lineage väzby



Status:

\- `TODO`



\---



\### 3. 66G reference layer

Cieľ:

\- držať 66G ako schválený reference point

\- nedovoliť, aby sa plietol s current universe winner truth



Navrhovaný mapping:

\- `reference\_only`



Status:

\- `TODO`



\---



\### 4. 67J winner layer

Cieľ:

\- explicitne oddeliť:

&#x20; - official universe winner

&#x20; - product direction

&#x20; - compare outputs

&#x20; - historical summaries



Navrhovaný mapping:

\- `official\_input` pre canonical strategy/universe decision

\- nie priame downstream čítanie zo starých compare files



Status:

\- `TODO`



\---



\### 5. Leverage truth

Cieľ:

\- zabrániť miešaniu leverage experimentov s live leverage truth



Aktuálny canonical truth:

\- live leverage truth = 1.0x without leverage



Navrhovaný mapping:

\- leverage experiment outputs = `candidate` alebo `reference\_only`

\- live truth carrier = canonical decision/snapshot



Status:

\- `TODO`



\---



\## Prioritné artifact families na audit



\### A. Summary artifacts

Riziko:

\- summary sa často tvári ako final truth



Potrebné:

\- určiť ktoré summary sú:

&#x20; - len informational

&#x20; - candidate

&#x20; - reference

&#x20; - nebezpečne mätúce



Status:

\- `TODO`



\---



\### B. Compare artifacts

Riziko:

\- compare býva nesprávne čítané ako verdict



Potrebné:

\- oddeliť compare od decision vrstvy

\- canonical decisions majú compare len odkazovať, nie sa s nimi pliesť



Status:

\- `TODO`



\---



\### C. Manifest artifacts

Riziko:

\- manifest môže potichu suplovať truth rozhodnutie



Potrebné:

\- oddeliť descriptive manifest od truth-changing decision



Status:

\- `TODO`



\---



\### D. Paper / markdown writeups

Riziko:

\- paper text môže tvrdiť niečo iné než machine-readable truth



Potrebné:

\- párovať paper s canonical decision/manifests

\- nedovoliť paper-only official truth



Status:

\- `TODO`



\---



\## Prvé konkrétne mapping deliverables



\### TODO — `canonical\_strategy\_snapshot.json`

Účel:

\- držať machine-readable current strategy state



\### TODO — `canonical\_universe\_decision.json`

Účel:

\- explicitne oddeliť universe truth od širšieho strategy balíka



\### TODO — `canonical\_leverage\_decision.json`

Účel:

\- explicitne držať current live leverage truth



\### TODO — `canonical\_66g\_reference.json`

Účel:

\- oddeliť schválený reference baseline od official current truth



\---



\## Forensic adoption pravidlo



Každý mapping krok sa má pýtať:

\- je artifact historical alebo canonical?

\- je official, reference alebo candidate?

\- je to decision, snapshot, manifest, export alebo paper?

\- môže to downstream čítať bez rizika?

\- treba to len aliasovať, alebo explicitne zablokovať ako misleading source?



\---



\## Najbližší low-risk cieľ



1\. spísať mismatch riziká

2\. zaviesť strategy snapshot

3\. zaviesť 66G reference contract

4\. až potom riešiť guard scripts

