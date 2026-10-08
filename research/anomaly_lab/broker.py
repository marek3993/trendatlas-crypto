"""Reuse Phase2's credential, transport, cache and reservation/accounting code.

The adapter is installed only in this broker process and is restored afterwards;
no Phase2 source files, policies, mailboxes or running processes are changed.
"""
from contextlib import contextmanager
import argparse
from pathlib import Path
from research.phase2_v2 import broker as backend
from research.phase2_v2.market import canonical
from .contract import load

SYSTEM = ('Return JSON with exactly one top-level key hypotheses, a list of at most four objects. '
          'Each object has exactly inputs (string list), rule (family, threshold, horizon, action), '
          'direction (same as action), horizon (same as rule horizon), mechanism (text), '
          'parameters (exactly threshold), falsification (text), parent (supplied parent ID or null). '
          'Use only the supplied finite enum schema. No code, verdict, PASS or trading permission. '
          'Explore failures, frequencies, weak validation growth and price aftermath. '
          'Only supplied prior training is available. History is seen development. '
          'Prospective 2026-09-27 through 2027-09-26 and 2027 are LOCKED/SEALED. '
          'Spot volume may be a declared proxy; derivatives are unavailable, never zero.')


def compact(payload):
    c = load()
    out = {k: payload[k] for k in ('scope', 'training_cutoff', 'schema', 'horizons', 'aggregates', 'derivatives', 'historical_independence')}
    def size(value):
        return len(canonical({'model': 'deepseek-flash', 'thinking': {'type': 'disabled'},
                              'max_tokens': c['budgets']['output_tokens_max'], 'response_format': {'type': 'json_object'},
                              'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': canonical(value)}]}).encode())
    out['aggregates'] = list(out['aggregates'])
    while size(out) > c['budgets']['wire_bytes_max'] and out['aggregates']:
        out['aggregates'].pop()
    if size(out) > c['budgets']['wire_bytes_max']: raise ValueError('lab_wire_budget')
    return out


def body(payload):
    return {'model': 'deepseek-flash', 'thinking': {'type': 'disabled'}, 'max_tokens': load()['budgets']['output_tokens_max'],
            'response_format': {'type': 'json_object'}, 'messages': [{'role': 'system', 'content': SYSTEM},
                                                                   {'role': 'user', 'content': canonical(compact(payload))}]}


@contextmanager
def configured():
    names = ('POLICY', 'CONTRACT', 'wire_body', 'wire_payload'); saved = {n: getattr(backend, n) for n in names}
    c = load(); b = c['budgets']
    try:
        backend.POLICY = {**saved['POLICY'], 'scope': 'anomaly_prior_training_only', 'input_token_ceiling': b['wire_bytes_max'],
                          'output_token_ceiling': b['output_tokens_max']}
        backend.CONTRACT = {'api_calls_per_cycle_max': b['api_calls_lifetime_max'],
                            'api_tokens_per_cycle_max': b['api_tokens_lifetime_max'], 'api_usd_per_cycle_max': b['api_usd_upper_lifetime_max']}
        backend.wire_body = body; backend.wire_payload = compact
        yield
    finally:
        for name, value in saved.items(): setattr(backend, name, value)


def once(mailbox, transport=None):
    with configured():
        return backend.broker_once(Path(mailbox), transport or backend.call_deepseek)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--mailbox', type=Path, required=True); a = p.parse_args()
    print(canonical({'processed': once(a.mailbox)}))
