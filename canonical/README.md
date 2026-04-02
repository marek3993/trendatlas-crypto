\# MRV1 Canonical Layer



\## Účel

Tento priečinok je čistá canonical/product truth vrstva nad historickým research chaosom.



Cieľ:

\- nemať product/app/downstream čítanie priamo z historických phase outputs

\- oddeliť official truth od exploratory history

\- zaviesť stabilné, čitateľné a auditovateľné artifacts



\---



\## Základné pravidlo



Historical/research layer môže zostať takmer tak ako je.



Canonical layer vzniká nad ňou a má byť:

\- malá

\- čistá

\- explicitná

\- stabilná

\- downstream-readable



\---



\## Podpriečinky



\### `decisions/`

Oficiálne truth-changing rozhodnutia.



Príklady:

\- strategy decision

\- universe decision

\- leverage decision



\---



\### `manifests/`

Canonical manifests a lineage manifests.



Príklady:

\- canonical artifacts manifest

\- domain manifests

\- lineage manifests



\---



\### `exports/`

Čisté downstream exports.



Príklady:

\- app-facing exports

\- product metrics exports

\- benchmark exports



\---



\### `references/`

Schválené referenčné artefakty, ktoré nie sú current official live state.



Príklady:

\- frozen 66G reference

\- frozen benchmark reference



\---



\## Consumption rule



Downstream vrstvy majú preferovať canonical artifacts, nie historical research files.



Poradie priority:

1\. canonical decisions

2\. canonical snapshots/manifests

3\. canonical exports

4\. canonical references



Historical layer je:

\- auditná

\- forenzná

\- pomocná

\- nie primary product truth source



\---



\## Truth discipline



Každý budúci canonical truth-bearing artifact má mať:

\- explicitný artifact type

\- explicitnú truth domain

\- explicitný truth status

\- lineage minimum

\- jasný consumer scope



\---



\## Low-risk adoption



Cieľ nie je big bang rename celého projektu.



Správny postup:

1\. založiť canonical layer

2\. vytvoriť canonical manifests

3\. vytvoriť prvé canonical decisions/snapshots

4\. až potom riešiť mismatch guards a audit tooling

