\# MRV1 Tests Skeleton



Toto ešte nie je plný test suite.

Je to minimálny skeleton pre engineering hygiene a infra bezpečnosť.



\## Cieľ

V prvej fáze majú testy chytať hlavne:

\- chýbajúce kritické súbory

\- rozbitý source\_of\_truth contract

\- rozbitú základnú repo štruktúru

\- zjavne nevalidné export contracts tam, kde sú definované



\## Priorita testov



\### 1. Source of truth integrity

Overiť existenciu:

\- `source\_of\_truth/README.md`

\- `source\_of\_truth/master\_state.md`

\- `source\_of\_truth/chat\_roles.md`

\- `source\_of\_truth/project\_truth.json`

\- `source\_of\_truth/paths\_registry.json`

\- `source\_of\_truth/current\_issues.md`



\### 2. Repo structure smoke checks

Overiť, že:

\- kritické top-level priečinky existujú

\- neexistujú zakázané committed artefakty typu `node\_modules`

\- repo neobsahuje zjavný temp/cache bordel v tracked vrstve



\### 3. Script import / entry smoke checks

Pre kritické skripty:

\- basic import check

\- prípadne `--help` alebo dry-run smoke check, ak to script podporuje



\### 4. Export contract checks

Len tam, kde je contract jasne definovaný:

\- required columns existujú

\- základné typy alebo non-empty checks

\- bez zásahu do strategy rozhodnutí



\## Čo zatiaľ neriešiť

\- vysoké test coverage

\- detailné research correctness testy

\- product wording

\- performance benchmarking

\- winner validation



\## Phase 1 deliverable princíp

Najprv zavrieť:

\- integrity

\- smoke

\- základnú reproducibility disciplínu



Až potom:

\- unit testy helperov

\- integration testy runner chainov

\- CI pipeline gates



\## Poznámka

Testy v MRV1 majú byť najprv ochranné mantinely, nie akademické coverage cvičenie.

