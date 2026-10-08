"""Independent quantity × price arithmetic against the unchanged engine replay."""
import copy
import math
import numpy as np
from research.phase2_v2.engine import evaluate
from research.phase2_v2.contract import load


def check(m, targets, folds, result, initial_state=None):
    state = copy.deepcopy(initial_state); c = load()['execution']
    fee = c['fee_bps']/10000; slip = c['slippage_bps']/10000
    n = len(m.assets); maximum = 0.; costs_error = 0.
    for row in result['equity']:
        day = row['date']; i = m.dates.get_indexer([day])[0]
        previous_q = np.array(state['quantity'] if state else np.zeros(n), dtype=float)
        previous_cash = state['cash'] if state else 100.
        marks = np.array(state['previous_mark'] if state else np.where(np.isfinite(m.close[i-1]), m.close[i-1], 0.))
        replay = evaluate(m, 'PRODUCTION', [[day, day]], production_targets=targets, initial_state=state)
        after = replay['checkpoint']; q = np.array(after['quantity']); change = q-previous_q
        op = np.where(np.isfinite(m.opening[i]), m.opening[i], 0.); cl = np.where(np.isfinite(m.close[i]), m.close[i], op)
        price = op*(1+np.sign(change)*slip); fee_charge = np.abs(change)*price*fee
        cash_after_fills = previous_cash-float(change@price)-float(fee_charge.sum())
        borrow = max(0., -cash_after_fills)*c['borrow_apr']/365.25
        costs = float((np.abs(change)*op*slip+fee_charge).sum())+borrow
        pnl = float(previous_q@(op-marks)+q@(cl-op))-costs
        old_nav = previous_cash+float(previous_q@marks); new_nav = cash_after_fills-borrow+float(q@cl)
        maximum = max(maximum, abs(old_nav+pnl-row['equity']), abs(new_nav-row['equity']))
        costs_error = max(costs_error, abs(costs-row['costs_usd']))
        if not math.isclose(new_nav, row['equity'], rel_tol=1e-9, abs_tol=1e-8): raise AssertionError('independent_quantity_price_pnl')
        if not math.isclose(costs, row['costs_usd'], rel_tol=1e-9, abs_tol=1e-8): raise AssertionError('independent_fill_costs')
        state = copy.deepcopy(after)
    return {'method': 'quantity_times_open_gap_plus_close_move_minus_independently_rebuilt_fees_slippage_borrow',
            'days_checked': len(result['equity']), 'max_nav_error': maximum, 'max_cost_error': costs_error, 'passed': True}
