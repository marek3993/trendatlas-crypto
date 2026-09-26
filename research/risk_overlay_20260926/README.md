# Rozhodovací report: stop-loss, trailing stop a take-profit

**NENASADZOVAŤ. Výskum variantov sa zastavil, pretože aktuálny produkčný baseline sa z publikovaných vstupov nedá reprodukovať.** Toto nie je zistenie, že stopy nefungujú. Nespustil sa walk-forward ani holdout a neexistujú tri validné najlepšie varianty.

Research vetva vychádza z `origin/main` **6fccbc388c1db75f6b46113fac15b7d3232e4123**, publikovaného 2026-09-26 pre uzavretý deň 2026-09-25. Pôvodná lokálna vetva bola staršia; jej oddelená reprodukcia nižšie nie je náhradou aktuálnej produkcie. Produkcia, timer, AVAX a burzové príkazy zostali nedotknuté.

## Aktuálny baseline: reprodukcia zlyhala

Kanonický snapshot/timeseries: **2018-05-05 až 2026-09-25**, 3 066 riadkov. Nezmenený adaptér odmietol vstupy:

```text
btc_ohlcv cannot be behind the validated durable BTC-persistence source day,
and no canonical fallback benchmark is available from the durable baseline paper
(btc_last_day=2026-05-05 fallback_last_day=2026-05-08 source_day=2026-09-25)
```

**Presná príčina:** publikované Production Core a trend-status artefakty sú novšie než spoločný raw/durable vstupný balík v Gite. Príkaz bežal nad zmrazenými vstupmi čistého checkoutu. Nedopĺňal dáta, nemenil dátumy ani neobchádzal existujúcu validáciu. `results.json` ukladá chybu a deklarované/dostupné hashe; rozlišuje aj rozdiel vysvetlený iba CRLF/LF.

| Metrika | Aktuálny publikovaný snapshot — NEZREPRODUKOVANÝ |
|---|---:|
| CAGR | 182,1216 % |
| Celkový výnos | 602 239,9336 % |
| Maximum drawdown | −12,9306 % |
| Sharpe / Sortino | 2,1980 / 3,6271 |
| trade_count / switch_count | 205 / 205 |
| Poplatky / sklz, súčet denných NAV nákladov v p. b. | 11,5200 / 15,7000 |
| Borrow / funding, rovnaké jednotky | 2,447639 / 0 |

Tieto čísla iba citujú modelový snapshot. Nie sú account PnL ani doklad úspešnej reprodukcie. Pravidlo používateľa „pri nezhode zastav výskum a vysvetli rozdiel“ sa uplatnilo. Na aktuálnom baseline sa po tejto chybe nevykonalo porovnávanie overlay.

## Oddelený lokálny augustový archív

Pred zistením novšieho vzdialeného buildu bol dvakrát reprodukovaný pôvodný lokálny archív **2018-05-05 až 2026-08-19**, 3 029 riadkov. Všetkých 69 stĺpcov sedí pri atol=1e-9/rtol=1e-12; všetky zaokrúhlené snapshot metriky sú presne zhodné. Výpočet používa nezmenený aktívny adaptér a ETF automat z durable BTC-persistence vstupov; celý upstream selector grid od raw cien sa nespúšťal. Výsledky majú prefix `local_`.

| Metrika | Reprodukovaný starší model |
|---|---:|
| CAGR / celkový výnos | 176,6605 % / 461 043,0106 % |
| Maximum drawdown / Calmar | −14,4265 % / 12,2456 |
| Kanonický Sharpe / Sortino | 2,1638 / 3,5095 |
| Ročná volatilita, populačná σ a 365,25 dní | 52,0074 % |
| Najhorší deň, 2020-09-02 | −9,4476 % |
| Čas v trhu / turnover v notional/NAV jednotkách | 22,5817 % / 269,75 |
| trade_count / switch_count | 211 / 211 |
| Poplatky / sklz, súčet denných NAV nákladov v p. b. | 12,13875 / 16,00000 |
| Borrow / funding, rovnaké jednotky | 2,422998 / 0 |

Produkčný trade_count je počet zmien aktíva, nie round-trip obchody alebo burzové fills. Nákladové súčty nie sú dolárové platby ani percentá počiatočného kapitálu. Kanonický Sortino používa odchýlku záporných výnosov od ich vlastného priemeru. Alternatívny downside RMS cez všetky dni s MAR=0 dáva 8,0961; výsledky definície explicitne rozlišujú. Nie je to zlepšenie stratégie.

Doplňujúce chyby tohto lokálneho archívu sú nezávisle potvrdené:

- **Identita aktíva:** 2024-12-03 vykazuje DOGE 1× a +96,1085972851 %. Raw DOGE má −4,2984666839 %, raw TRX +96,1085972851 %. Stop na DOGE nemožno testovať nad ziskom TRX. Ďalších 397 aktívnych riadkov má `BASE` bez rozkladu na obchodované mince. Z 684 aktívnych riadkov má 116 pokrytých riadkov rozdiel oproti dennému výnosu označenej mince nad 1 bp; prechodové dni treba skúmať osobitne.
- **Časovanie:** po BTC expozícii 0,5× dňa 2025-01-06 príde 2025-01-07 pokles BTC −5,1655098615 %. Dnešný close 96 954,61 pod EMA10 97 617,371337 prepne model na CASH a zároveň vynuluje dnešný hrubý výnos. Predchádzajúca expozícia krát pohyb predstavuje diagnosticky −2,5827549308 %, kanonický net riadok má iba −0,1225 % nákladov. Syntetický test nezmeneného produkčného automatu preukazuje rovnaké spätné filtrovanie: zmena dnešného close filtra zmení dnešný výnos −3 % na 0 %.
- **Venue dáta:** v pôvodnom lokálnom strome existujú Binance spot 4h dáta 12 mincí a funding BTC/ETH/BNB/SOL/XRP. Nie sú to doložené Hyperliquid mark ceny ani kompletný hodinový funding obchodovaných mincí. Tieto archívne 4h/funding súbory sú aj v čistom checkout-e; ich časové pokrytie a hashe sú v oddelených inventároch. Nevykonal sa ich overlay backtest.

Tieto zistenia nie sú opravou baseline. Augustové chyby ani percentá sa automaticky neprenášajú na septembrový build. Produkčná stratégia sa neprepísala.

## Universe, náklady a plánované varianty

Identita stratégie zostáva `phase68g_etf_flow_impulse_early_risk_cooldown_15`. V lokálnom archíve sú core overlay kandidáti ADA/AVAX/BNB/DOGE/DOT/ETH/LINK/TRX/XRP, vyradené LTC/SOL. Pozorované modelové označenia sú ADA/BASE/BTC/CASH/DOGE/ETH/LINK/TRX; BASE nie je burzová minca. Expozície 0/0,5/0,75/1/1,25×. Referenčný universe víťaz sa nezamieňa za aktívny input chain.

Lokálny adapter odvodil maker/taker 1,5/4,5 bp, taker režim, transition sklz 10 bp, borrow 12 % ročne nad 1× a nulový funding. Presné denné náklady vrátane pass-through vrstiev zostali zachované. Parametre, seed **20260926**, hashe a dátové rozsahy sú v príslušných manifestoch. Najhorší obchod, win rate, priemerný zisk/strata a profit factor sa neuvádzajú ako validné obchodné metriky bez zosúladeného ekonomického fill ledgeru.

| Požadovaná časť | Stav |
|---|---|
| A: aktuálny baseline | Reprodukcia odmietnutá pre nekonzistentné vstupy |
| B: katastrofický ATR 2/3/4/5 | Nespustené |
| C: aktivácia 1/2 ATR, trail 2/3/4 ATR | Nespustené |
| D: 25/50 % TP pri 2/3 ATR | Nespustené |
| E: dve obmedzené kombinácie | Nespustené |
| Fixný 5 % benchmark | Nespustený |
| Najlepšie tri / walk-forward / holdout | Žiadne validné výsledky |
| Dopad overlay na CAGR, drawdown, náklady, obchody | Nezmeraný |
| Porovnanie historických prepadov a veľkých víťazov | Nespustené |

`contract.json` ukladá 18 plánovaných variantov vrátane baseline, kauzálne ATR, nepriaznivé intrabar poradie, gap/partial fill, reentry až pri nasledujúcom kanonickom vyhodnotení a walk-forward pravidlá. Nevykonal sa parameter mining. História už bola predmetom starších lokálnych štúdií; spätne ju neoznačíme za globálne nedotknutý holdout. Po oprave dôkazového základu treba zmraziť nový dopredný holdout.

## Leverage a rotácia

Read-only burzový capture 2026-09-26 12:27:54 UTC: **AVAX 9,58, cross 10×, unifiedAccount**. Notional 104,6136 USD / USDC total 83,982708 USD = **1,245656×**. Sú to postupné API odpovede, nie atomický snapshot. Fees sú 4,5 bp taker a 1,5 bp maker. Capture neobsahuje adresu ani kľúč.

Aktuálny kanonický executor používa `equity * target_exposure` a unified equity spracúva správne. Sizing sa nenásobí 10. Trackovaná politika už nastavuje **execution_leverage=2**, max 3; burzový setting 10 je samostatný drift na preverenie. Starý súčet spot+perp patrí legacy recovery ceste a nie je vydávaný za aktuálnu produkčnú chybu. Ďalší patch nastavujúci 2 by bol duplicitný; žiadny sa nepripravil ani neaplikoval.

Podrobný margin/funding/liquidation audit a neblokujúci návrh ochrany vrátane BTC → AVAX, AVAX → ETH a pozícia → CASH obsahuje **LEVERAGE_AND_ARCHITECTURE.md**. Overlay engine sa po zlyhaní baseline neimplementoval. Nevznikol nový gate, allowlist ani approval systém.

## Reprodukcia a ďalší krok

Z koreňa research checkoutu, Python 3.12.10; presné pandas/numpy verzie sú v manifestoch:

```powershell
python research/risk_overlay_20260926/run_audit.py
python research/risk_overlay_20260926/run_audit.py --source local
python research/risk_overlay_20260926/test_audit.py
python research/risk_overlay_20260926/leverage_audit.py
```

Oba audity majú zámerný návratový kód **2** (aktuálne vstupy odmietnuté / lokálna ekonomická validácia zlyhala). Testy a leverage replay majú kód 0. Všetky štyri bežné príkazy sú offline. Jednorazové pôvodné zachytenie používalo `--freeze` a `--capture-live`; pri existujúcich dôkazoch odmietnu prepis.

Dva ZIP balíky uchovávajú presné modelové/cenové vstupy; rozbaľujú sa iba do dočasného adresára. Nezapisuje sa do produkčných data/outputs. `local_` balík pochádza z pôvodného pracovného stromu a current balík z čistého `origin/main`. Kód a hashe sú pripnuté k research commitu. Úplný povinný audit a git zoznam: **AUDIT.md**.

Ďalší potrebný krok je získať kompletný dátový balík rovnakého produkčného buildu, zosúladiť signal/fill/return intervaly a rozklad BASE, preukázať reprodukciu a až potom vyhodnotiť overlay. Z tejto úlohy nevzniklo oprávnenie na deploy alebo živé príkazy.

Jednotné offline overenie celého balíka: `python research/risk_overlay_20260926/validate_research.py` (23 testov, návratový kód 0; oba vedecké audity pritom očakávane vracajú 2).
