"""Dependent calendar-block inference with explicit assumptions and lifetime debt."""
import math
import numpy as np


def alpha_for(trial, alpha=.05):
    if type(trial) is not int or trial < 1: raise ValueError('invalid_lifetime_trial')
    return alpha/(trial*(trial+1))


def block_interval(numerator, denominator, block=30, repeats=1023, seed=0, scale=1.):
    """Moving calendar blocks jointly resample exposure and event count (not IID rows)."""
    a = np.asarray(numerator, float); b = np.asarray(denominator, float)
    if len(a) != len(b) or not len(a) or b.sum() <= 0: return None
    if len(a) < block*2: return None
    rng = np.random.default_rng(seed); n = len(a); k = math.ceil(n/block)
    estimates = []
    for _ in range(repeats):
        starts = rng.integers(0, n-block+1, size=k)
        ix = (starts[:, None]+np.arange(block)).ravel()[:n]
        exposure = b[ix].sum()
        if exposure > 0: estimates.append(float(a[ix].sum()/exposure*scale))
    return [float(x) for x in np.quantile(estimates, [.025, .975])] if estimates else None


def block_test(differences, calendar_indices, trial, *, block=30, min_blocks=8, repeats=4095, seed=0):
    """One sign per common calendar block; within-block serial dependence preserved.

    Conditional on block magnitudes, the null assumes independent symmetric block
    signs. This is a disclosed model, never a guarantee for dependent financial data.
    The union bound controls lifetime comparisons only when conditional p-values
    are valid. Adaptive past-only proposals do not consume the future block label.
    """
    alpha = alpha_for(trial)
    if not len(differences): return {'p': None, 'alpha': alpha, 'blocks': 0, 'rejected': False, 'ci95': None}
    d = np.asarray(differences, float); ix = np.asarray(calendar_indices, int)//block
    labels = sorted(set(ix)); values = np.array([d[ix == k].mean() for k in labels])
    if not np.isfinite(values).all(): raise ValueError('nonfinite_statistic')
    n = len(values)
    if n < min_blocks:
        return {'p': None, 'alpha': alpha, 'blocks': n, 'rejected': False, 'ci95': None}
    observed = float(values.mean()); rng = np.random.default_rng(seed)
    if n <= 15:
        integers = np.arange(2**n, dtype=np.uint32)
        signs = ((integers[:, None] >> np.arange(n)) & 1)*2.-1
        null = signs@values/n
        p = float(np.mean(null >= observed-1e-12)); draws = len(null)
    else:
        null = rng.choice([-1., 1.], size=(repeats, n))@values/n
        p = float((1+np.sum(null >= observed-1e-12))/(repeats+1)); draws = repeats+1
    means = values[rng.integers(0, n, size=(repeats, n))].mean(axis=1)
    ci = [float(x) for x in np.quantile(means, [.025, .975])]
    return {'p': p, 'alpha': alpha, 'blocks': n, 'rejected': p <= alpha and observed > 0,
            'mean_excess': observed, 'ci95': ci, 'draws': draws, 'p_resolution': 1/draws,
            'assumption': 'conditionally independent symmetric common calendar block signs',
            'historical_claim': 'development_association_only'}
