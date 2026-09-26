# Rozhodnutie o ďalšom risk-overlay výskume

Pripravené po úspešnom dokončení všetkých 19 regresných testov kandidáta a 17 existujúcich kontraktových/dashboard testov.

**Kandidát je vhodný na ďalší obmedzený offline risk-overlay výskum.** Východiskom má byť výhradne tento kauzálny ledger s jeho predpokladmi a hashemi. Výsledok zatiaľ nepreukazuje očakávaný živý výkon stratégie.

Celý interval má CAGR 31,4471 %, drawdown −40,6292 %, Sharpe 0,7511 a Calmar 0,7740. Od 2025-01-01 do 2026-09-25 je čistý výnos iba 13,5089 %, anualizovaný 7,5853 %, drawdown −31,9467 % a Sharpe 0,3830. Posledná časť histórie je teda výrazne slabšia než celkový výsledok. Tieto čísla používajú rovnaké definície ako hlavný report, bez zmeny parametrov.

Najlepší deň, TRX 2024-12-03, má net +95,7482 % a predstavuje približne 29,26 % celkového logaritmického rastu. Jeho držba prešla kontrolou kauzality a identity; závislosť výsledku od jedného veľkého pohybu ostáva relevantná pre robustnosť. Model končí na indexe 9,9272 oproti BTC 8,6576 na rovnakom cenovom okne; samotné vyššie konečné číslo nedokazuje stabilnú výhodu.

Pred ďalším porovnávaním overlayov treba fixovať tento baseline a jeho nákladovú/exekučnú konvenciu, vopred oddeliť hodnotiace obdobia a doplniť chýbajúce venue mark/funding a point-in-time makro údaje. Vhodným ďalším overením je citlivosť na reálnu latenciu a plnenia pri nezmenených pravidlách. V tejto úlohe sa žiadny overlay ani stop-loss netestoval a žiadny parameter sa nehľadal podľa výnosu.

Pôvodné CAGR približne 182 % a drawdown približne −13 % sa nemajú používať ako referenčný risk budget. Korekcia ukazuje približne 41 % historický pokles aj s veľkým podielom času v CASH. Pri budúcom hodnotení treba merať aj zníženie príležitostí, obrat a zhoršenie nákladov, nie iba najlepší drawdown po optimalizácii.

Tento report nie je schválenie zmeny live targetu ani nasadenia. Posledný ekonomický cieľ rekonštrukcie je LTC 1,25×, zatiaľ čo weekly kandidát zostáva AVAX; rozdiel odhaľuje chybu pôvodnej línie. Aktuálna pozícia a produkčný runtime sa nemenili. Kolízia reduce-only ochranných objednávok s rotáciou zostáva samostatným budúcim problémom.
