# Leverage audit a návrh ochrany

## Potvrdený stav a samostatná chyba

Read-only capture 2026-09-26T12:27:54.939122Z potvrdil unifiedAccount, AVAX 9,58, cross leverage 10, notional 104,6136 USD a USDC total 83,982708. Exposure z týchto burzových údajov je približne 1,245656×. Nie je odvodená z modelového `actual_held_asset` ani `effective_market_exposure`. Aktuálna pozícia bola iba prečítaná; nebol odoslaný, zmenený ani zrušený príkaz.

**Aktuálny kanonický executor je `production_execution.py`, spúšťaný iba cez `run_trendatlas_production.py`.** Jeho `account_equity_and_available` používa pri unifiedAccount spot stable total a nepripočítava individual-perp accountValue. To zodpovedá aktuálnemu SSOT aj [oficiálnemu account abstraction kontraktu](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes). Na zachytených číslach vracia equity 83,982708 USD a cieľ 1,25× je 104,978385 USD.

Presný kanonický sizing výraz je `0.0 if is_cash(target_asset) else equity * target_exposure`. Deterministický test ho kompiluje z AST aktuálneho kódu bez spúšťania submittera. Pri equity 100 a expozícii 1,25× je notional 125 pri exchange settingu 2× aj 10×.

**Spresnenie nálezu zo staršieho lokálneho checkoutu:** starý `submit_controlled_real_order.py::compute_total_trading_equity_usd` sčíta spot a perp accountValue. Pre capture by dal 96,286575 USD a cieľ 120,358219 USD. Táto funkcia patrí legacy manuálnej recovery ceste. Nie je to doklad chyby aktuálneho kanonického sizingu a neopravovali sme ju v rámci research. Nová produkčná cesta ju pre sizing nepoužíva.

**Rozdiel repo verzus burza:** `execution/config/live_order_policy.json` v main už obsahuje `execution_leverage=2`, `max_execution_leverage=3`, max strategy exposure 2 a margin buffer 5 %. Burza na otvorenej AVAX pozícii hlási 10×. Kanonický planner pri NO_ACTION nevytvorí order step a samotné odsúhlasenie expozície nevyvoláva zosúladenie leverage. Signed adapter aktualizuje leverage iba pred príkazom zvyšujúcim expozíciu; pri reduce-only ho nemení. Je to možné vysvetlenie zachovania starej hodnoty, nie potvrdená rekonštrukcia Pi udalostí. Navyše trackovaný policy allowlist neobsahuje AVAX, hoci burza AVAX drží. Aktuálna Pi konfigurácia a historický journal neboli čítané; rozdiel treba vyšetriť samostatne, bez pridávania nového allowlistu.

**Leverage patch sa nepripravil:** zmena trackovanej hodnoty na 2 by bola duplicitná a nevysvetlila by runtime drift. Táto úloha nemení žiadne nastavenie burzy, scheduler alebo executor.

## Čo by znamenalo 2×

Pri notionali 104,6136 je počiatočná margin požiadavka približne 10,46136 pri 10× a 52,3068 pri 2×. Pri cieli 1,25× je 2× najnižšie celočíselné nastavenie, ktoré aritmeticky umožňuje cieľ: počiatočná marža je 62,5 % kapitálu, zostáva 37,5 % pred ďalšími záväzkami, nákladmi a cenovým pohybom. S existujúcim 5 % planner bufferom je požiadavka 65,625 % equity. Formálny policy strop 2× by pri exchange 2× a rovnakom bufferi vyžadoval 105 % equity; pre tento strop 2× nie je všeobecne dostatočné, hoci pre pozorované maximum stratégie 1,25× je aritmeticky dostatočné. To nie je záruka bezpečnosti pre všetky aktíva, účtové režimy a margin tiers. [Margining](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/margining)

Nižšia páka môže obmedziť jednorazovú príliš veľkú objednávku cez vyššiu počiatočnú maržu. Nie je absolútnym account exposure limitom: závisí od režimu, ostatných pozícií, kolaterálu a neskoršieho cenového pohybu. Neopraví chybný equity vstup.

Pri rovnakom notionali a kolateráli **cross** zmena settingu sama nepredĺži liquidation distance. Podľa dokumentácie skutočná cross liquidation cena nezávisí od nastavenej páky. Pri **isolated** nižšia páka mení pridelenú maržu, a tým aj vzdialenosť likvidácie. Capture obsahuje liquidationPx 2,2668818811 ako burzou publikovaný údaj; neprepočítavame ho z modelovej páky. [Liquidations](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/liquidations)

Funding sa vyrovnáva hodinovo podľa pozície; pri nezmenenom notionali a držbe ho prepnutie 10× → 2× samo nezmení. Nejde o úrok iba z časti nad 1×. [Funding](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding) Obchodné poplatky sa pri nezmenenom vykonanom objeme a účtovej sadzbe nemenia samotným leverage settingom. Read-only `userFees` potvrdilo 4,5 bp taker a 1,5 bp maker. [Fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees)

## Návrh architektúry; zatiaľ neimplementovaný

1. Kanonický denný signál určuje cieľ a notional. Executor vlastní zatvorenie starej pozície a otvorenie novej. Overlay nevracia povolenie/zakázanie rotácie a nemá právomoc vyberať trh alebo navyšovať pozíciu.
2. Samostatný ochranný worker dostáva potvrdené burzové fills/pozíciu a `position_generation`, nie modelovú expozíciu. Jeho výstupy sú výhradne reduce-only close/reduce a sprísnenie stopu. Pri long sa stop nesmie znížiť; redukcia je ohraničená potvrdeným zvyšným množstvom. Po TP sa nový stop vzťahuje iba na zvyšok.
3. Journal obsahuje generation, canonical signal ID, client order ID, entry fills, počiatočné ATR, high-water mark, posledný potvrdený stop, TP fill množstvo a stav potvrdenia. Najprv sa zapíše zámer, potom sa po burzovom potvrdení zapíše výsledok; rovnaký client ID sa pri neistom výsledku zisťuje, nie slepo duplikuje. Pri reštarte sa zreconciliujú pozície, otvorené príkazy a fills s journalom. Chýbajúci high-water sa rekonštruuje z uloženého mark streamu/journalu; bez dostatočných dát sa nepredstiera presná rekonštrukcia, nahlási sa degradovaná ochrana a denná rotácia pokračuje.
4. Denná rotácia má prednosť pred ochranným workerom. Vyhlási nový generation a invaliduje staré lokálne úlohy. Staré ochranné príkazy sa označene zrušia/reconciliujú, stará pozícia sa zatvorí reduce-only a nový cieľ sa otvorí podľa kanonického signálu. Zlyhanie ochranného workeru alebo journalu sa nesmie propagovať ako gate do tejto cesty. Úspech rotácie stále vyžaduje dostupnú burzu a vykonateľné objednávky.
5. Stop reentry je úlohou nasledujúceho kanonického denného vyhodnotenia. Overlay počas medzidobia nevytvára nový vstup; nie je pridaný asset allowlist ani manuálne schvaľovanie.

| Scenár | Povinné správanie budúcej integrácie |
|---|---|
| BTC → AVAX | Starý BTC generation zneplatniť, BTC close pokračuje aj pri chybe overlay, AVAX vstup určuje kanonický signál |
| AVAX → ETH | Zatvoriť AVAX, otvoriť ETH; žiadny prenos AVAX ATR/TP/high-water na ETH |
| Pozícia → CASH | Vykonať reduce-only close; chybný journal nesmie zabrániť zatvoreniu |
| Partial TP + rotácia | Zatvoriť iba potvrdený zvyšok, neotvoriť opačnú pozíciu |
| Stop + denný signál | Počas dňa nevstupovať; ďalšie kanonické vyhodnotenie môže otvoriť svoj cieľ |
| Worker exception / timeout / reštart | Degradovaná ochrana a alert, bez nového execution gate |

**Existujúca integračná prekážka, neopravená:** aktuálny `production_execution.py::build_execution_plan` blokuje pri otvorených príkazoch (`conflicting_open_order`). Aj kontrola medzi rotačnými krokmi v orchestratore vyžaduje prázdny open-order stav. Trvalé stop príkazy by tak dnes mohli blokovať rotáciu. Prípadná implementácia musí najprv upraviť kontrakt identifikácie a lifecycle vlastných reduce-only ochrán a otestovať rotácie. Samotné pridanie stop workeru k dnešnému executoru nie je prijateľný deploy návrh. Existujúce allowlisty či schvaľovanie tento research patch nerozširuje.

Native reduce-only príkaz nie je automaticky viazaný na lokálny generation. Ak zrušenie starého stopu zlyhá a ten istý trh sa znovu otvorí, starý príkaz môže zmenšiť novú pozíciu. Generation journal sám túto burzovú pretekovú situáciu neodstráni. Návrh nesľubuje súčasne nulové riziko starého stopu a absolútne neblokujúci vstup pri nedostupnom cancellation API; tento prípad vyžaduje explicitný integračný test a zdokumentované obmedzenie. Nesmie sa zakryť ďalším globálnym gate.

## Trigger a simulácia

Hyperliquid TP/SL spúšťa **mark price**. Fill je samostatná udalosť na order booku; stop cena nie je zaručená realizačná cena. Dokumentácia uvádza 10 % slippage tolerance pre market TP/SL a rozdiely medzi fixed-size a position TP/SL. Konzervatívna simulácia musí modelovať gap, náklady, neúplný/neuskutočnený fill a poradie stop/TP; obyčajný OHLC priechod cez stop nie je garantované plnenie. [TP/SL kontrakt](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl)

Všetky uvedené rotačné a ochranné scenáre sú požiadavky budúceho testovania, nie tvrdenie, že takáto produkčná integrácia už prešla testom. Tento balík testuje dôkazy pre zastavenie research, nie hotový overlay.

Deterministické testy existujúceho kanonického plannera overili syntetické BTC → AVAX, AVAX → ETH a AVAX → CASH, invariantný notional pri 2×/10× a jeho aktuálne blokovanie otvoreným ochranným príkazom. Nepreukazujú funkčnosť zatiaľ neimplementovaného overlay ani opravu tejto integračnej prekážky.
