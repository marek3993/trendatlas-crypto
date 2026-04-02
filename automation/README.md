# MRV1 Automation

Safe automation layer pre Market Regime v1.

## Scope
Rieši:
- browser automation workflow
- task specs
- run logging
- reports
- screenshots
- pending truth patches
- safe approval-gated updates do source_of_truth

Nerieši:
- winner decisions
- strategy ideation
- forensic validation
- app wording
- repo hygiene
- tokenomiku

## Safe mode
Automation nesmie priamo prepisovať source_of_truth.
Automation môže len:
- vykonať task
- uložiť log
- uložiť report
- pripraviť pending truth patch

Apply truth patchu je oddelený krok.
