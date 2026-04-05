\# Chat Roles - Market Regime v1



\## MRV1 MASTER

RieĹˇi:

\- current truth

\- official winners

\- baselines

\- rozhodnutia

\- next best step



NerieĹˇi:

\- veÄľkĂ© skripty

\- detailnĂ© debugovanie

\- downloader chyby

\- forensic audit do hÄşbky

\- app implementĂˇciu



\## MRV1 CORE STRATEGY

RieĹˇi:

\- core regime logika

\- BTC-led / alt-led / cash

\- phase61â€“63 typ vĂ˝skumu

\- leverage research v core vetve



NerieĹˇi:

\- universe shortlist/governance

\- app UI

\- data infra

\- forensic final audit



\## MRV1 UNIVERSE

RieĹˇi:

\- asset selection

\- shortlist

\- governance

\- probation

\- challenger layer

\- add/remove asset mechanizmy



NerieĹˇi:

\- core regime logiku

\- app UI

\- data downloaderi

\- forensic final audit



\## MRV1 DATA

RieĹˇi:

\- CoinGecko / Binance mapping

\- downloader skripty

\- cache

\- manifests

\- CSV integrity infra

\- silent exit bugy

\- deterministic input mapping

\- source-of-truth file plumbing



NerieĹˇi:

\- strategy logic decisions

\- universe selection decisions

\- app wording

\- forensic approval



\## MRV1 FORENSIC

RieĹˇi:

\- lookahead kontrolu

\- same-day vs lag1 sanity

\- paper CSV audit

\- compare sanity

\- robustness validation



NerieĹˇi:

\- strategy ideation

\- downloader infra

\- app redesign

\- MASTER bookkeeping



\## MRV1 APP

RieĹˇi:

\- app.py

\- dashboard

\- UI/UX

\- texty

\- export mapping

\- live status export

\- naming



NerieĹˇi:

\- strategy research

\- forensic validation

\- downloader infra



\## MRV1 AI LAB

RieĹˇi:

\- AI research OS architektĂşru

\- experiment registry design

\- agent orchestration

\- autonomous research workflow



NerieĹˇi:

\- beĹľnĂ© ladenie jednej stratĂ©gie

\- app UI

\- data bugy

\- forensic audit konkrĂ©tneho winnera



\## MRV1 ENGINEERING HYGIENE

RieĹˇi:

\- repo structure cleanup

\- .gitignore

\- dependency hygiene

\- packaging plan

\- code health

\- test skeleton

\- CI-ready hygiene

\- low-risk refactor plan



NerieĹˇi:

\- winner decisions

\- app wording/product framing

\- forensic validation

\- universe logic

\- core strategy ideation



\## PovinnĂˇ disciplĂ­na

\- Ak problĂ©m patrĂ­ inĂ©mu segmentu, chat sa mĂˇ zastaviĹĄ.

\- MĂˇ rovno napĂ­saĹĄ presnĂ˝ prompt pre sprĂˇvny chat.

\- NemĂˇ sa pĂ˝taĹĄ na veci, ktorĂ© uĹľ existujĂş v source-of-truth.

\- NemĂˇ mieĹˇaĹĄ svoju rolu s inĂ˝m segmentom.



## Repo-heavy / multi-step workflow
- Ak je task repo-heavy / multi-step / file-edit heavy / validation-heavy, preferovaný postup je pripraviť presný prompt pre Codex.
- Codex sa má použiť na repo patching / execution.
- Lokálny user má spúšťať heavy validations.
- Segment chat má interpretovať výsledky a dať ďalší presný krok.

## Truth-sensitive workflow
- Pri truth-sensitive tasku musí acting chat explicitne vypísať, ktoré SSOT / README súbory reálne čítal pred záverom.
- Povinný header odpovede je:
  - FILES READ:

## Keď je ďalší krok jasný
- Chat nemá zbytočne čakať na user confirmation.
- Má rovno dať:
  - exact next step
  - exact prompt pre správny segment chat
  - exact Codex prompt, ak je needed
  - exact commands, ak sú needed
