"""Credential-free public venue archive. No strategies, account queries or orders.

Every response/error is an append-only observation with request/receive times.
Historical retrieval never becomes prospective evidence by being downloaded now.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
import urllib.request
import zlib

HERE = Path(__file__).resolve().parent
CONTRACT = json.loads((HERE / 'contract.json').read_text())
C = CONTRACT['collector']
HOUR = 3600000
DOCS = [
    'https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees.md',
    'https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size.md',
    'https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data.md',
]


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirect_forbidden')


def validate_request(body):
    kind = body.get('type')
    fields = {'metaAndAssetCtxs': {'type'}, 'l2Book': {'type', 'coin'},
              'candleSnapshot': {'type', 'req'},
              'fundingHistory': {'type', 'coin', 'startTime', 'endTime'}}
    if kind not in fields or set(body) != fields[kind]:
        raise ValueError('non_public_or_unknown_request')
    if kind == 'candleSnapshot':
        q = body['req']
        if set(q) != {'coin', 'interval', 'startTime', 'endTime'} or q['interval'] != '1h':
            raise ValueError('invalid_candle_request')
    else:
        q = body
    if kind != 'metaAndAssetCtxs' and q['coin'] not in C['assets']:
        raise ValueError('asset_not_allowlisted')
    if kind in ('candleSnapshot', 'fundingHistory'):
        if not all(type(q[k]) is int for k in ('startTime', 'endTime')):
            raise ValueError('invalid_timestamp')
        if not 0 <= q['startTime'] < q['endTime'] <= int(time.time()*1000):
            raise ValueError('unclosed_or_reversed_request')


def fetch(body=None, url=None):
    if body is not None:
        validate_request(body)
        url = C['url']
        request = urllib.request.Request(url, data=encoded(body),
                                        headers={'Content-Type': 'application/json'})
    else:
        if url not in DOCS:
            raise ValueError('document_not_allowlisted')
        request = urllib.request.Request(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=12) as response:
        raw = response.read(C['max_response_bytes']+1)
        if len(raw) > C['max_response_bytes']:
            raise ValueError('response_size_limit')
        return raw


def validate_response(body, raw):
    value = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    kind = body['type']
    if kind == 'metaAndAssetCtxs':
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError('metadata_shape')
        universe = value[0]['universe']
        if len(universe) != len(value[1]) or len({x['name'] for x in universe}) != len(universe):
            raise ValueError('metadata_alignment')
        for ctx in value[1]:
            if not isinstance(ctx, dict):raise ValueError('context_shape')
        # Missing individual marks/funding remain missing in original bytes.
    elif kind == 'l2Book':
        if value.get('coin') != body['coin'] or len(value.get('levels', [])) != 2:
            raise ValueError('book_shape')
    else:
        if not isinstance(value, list):raise ValueError('history_shape')
        q = body.get('req', body)
        times = []
        for item in value:
            if kind == 'candleSnapshot':
                if item['s'] != q['coin'] or item['i'] != '1h':raise ValueError('bar_identity')
                t = item['t']
                if item['T'] > q['endTime']:raise ValueError('unclosed_bar')
            else:
                if item['coin'] != q['coin']:raise ValueError('funding_identity')
                t = item['time']
            if not q['startTime'] <= t <= q['endTime']:raise ValueError('time_outside_request')
            times.append(t)
        if times != sorted(set(times)):raise ValueError('duplicate_or_unsorted_history')
    return value


def open_archive(root):
    root = Path(root).resolve()
    # CLI additionally enforces the exact isolated root on VPS.
    root.mkdir(parents=True, exist_ok=True)
    manifest = root/'collection_manifest.json'
    binding = {'experiment_id': CONTRACT['experiment_id'],
               'contract_sha256': hashlib.sha256((HERE/'contract.json').read_bytes()).hexdigest(),
               'collector_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'kind': 'PUBLIC_DATA_COLLECTION_NOT_FORWARD_TOURNAMENT'}
    if manifest.exists():
        old = json.loads(manifest.read_text())
        if any(old.get(k) != v for k, v in binding.items()):
            raise ValueError('immutable_collector_binding_changed')
    else:
        with manifest.open('x') as f:
            json.dump(dict(binding, frozen_utc=utc()), f, sort_keys=True)
            f.flush();os.fsync(f.fileno())
    db = sqlite3.connect(root/'venue.sqlite', timeout=5)
    db.execute('PRAGMA synchronous=FULL')
    db.execute('PRAGMA journal_mode=DELETE')
    db.executescript('''
      CREATE TABLE IF NOT EXISTS observations (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, asset TEXT NOT NULL,
        requested_utc TEXT NOT NULL, received_utc TEXT NOT NULL,
        request TEXT NOT NULL, status TEXT NOT NULL, payload BLOB NOT NULL,
        payload_sha256 TEXT NOT NULL, previous_hash TEXT NOT NULL,
        row_hash TEXT NOT NULL UNIQUE);
      CREATE INDEX IF NOT EXISTS lookup ON observations(kind,asset,status,id);
      CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON observations
      BEGIN SELECT RAISE(ABORT,'append_only'); END;
      CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON observations
      BEGIN SELECT RAISE(ABORT,'append_only'); END;
    ''')
    return db


def append(db, kind, asset, request, requested, raw, status):
    received = utc()
    db.execute('BEGIN IMMEDIATE')
    try:
        last = db.execute('SELECT row_hash FROM observations ORDER BY id DESC LIMIT 1').fetchone()
        previous = last[0] if last else 'GENESIS'
        digest = hashlib.sha256(raw).hexdigest()
        record = [kind, asset, requested, received, encoded(request).decode(), status, digest, previous]
        row_hash = hashlib.sha256(encoded(record)).hexdigest()
        db.execute('INSERT INTO observations(kind,asset,requested_utc,received_utc,request,status,payload,payload_sha256,previous_hash,row_hash) VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (*record[:6], zlib.compress(raw), digest, previous, row_hash))
        db.commit()
    except BaseException:
        db.rollback();raise


def last_success(db, kind, asset):
    row = db.execute("SELECT request,payload FROM observations WHERE kind=? AND asset=? AND status='OK' ORDER BY id DESC LIMIT 1", (kind, asset)).fetchone()
    return (json.loads(row[0]), json.loads(zlib.decompress(row[1]))) if row else None


def collect(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    total = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    if total >= C['state_limit_bytes'] or shutil.disk_usage(root).free < C['disk_reserve_bytes']:
        raise RuntimeError('disk_guard_collection_paused')
    db = open_archive(root)
    calls = 0;errors = 0
    # Closed hourly boundary; no current candle is a completed observation.
    end = int(time.time()*1000)//HOUR*HOUR
    try:
        def record(body, asset='', url=None):
            nonlocal calls, errors
            if calls >= C['max_requests_per_activation']:raise RuntimeError('request_budget')
            requested = utc();calls += 1
            raw = None
            try:
                raw = fetch(body, url)
                if body is not None:validate_response(body, raw)
                status = 'OK'
            except Exception as exc:
                # No headers, environment, exception URL or secret ever logged.
                status = 'INVALID_RESPONSE' if raw is not None else 'GAP'
                if raw is None:raw = encoded({'error_type': type(exc).__name__, 'data': None})
                errors += 1
            append(db, body['type'] if body else 'source_document', asset,
                   body if body else {'url': url}, requested, raw, status)
            time.sleep(0.12)

        record({'type': 'metaAndAssetCtxs'})
        for coin in C['assets']:
            record({'type': 'l2Book', 'coin': coin}, coin)
            old = last_success(db, 'candleSnapshot', coin)
            start = end-C['history_hours']*HOUR
            if old and old[1]:start = max(start, max(v['t'] for v in old[1])-HOUR)
            record({'type': 'candleSnapshot', 'req': {'coin': coin, 'interval': '1h', 'startTime': start, 'endTime': end-1}}, coin)
            old = last_success(db, 'fundingHistory', coin)
            start = old[0]['endTime']+1 if old else end-C['history_hours']*HOUR
            # A bounded 400-hour page stays below the 500-item API response cap.
            funding_end = min(end-1, start+C['funding_page_hours']*HOUR-1)
            if start < funding_end:
                record({'type': 'fundingHistory', 'coin': coin, 'startTime': start, 'endTime': funding_end}, coin)
        for url in DOCS:
            present = db.execute("SELECT 1 FROM observations WHERE kind='source_document' AND asset=? AND status='OK' AND received_utc>=? LIMIT 1", (url, utc()[:10])).fetchone()
            if not present:record(None, url, url)
        count = db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
        status = {'status': 'COLLECTING_WITH_GAPS' if errors else 'COLLECTING_PUBLIC_DATA',
                  'tournament': 'NOT_STARTED_REFIT_BLOCKED', 'verdict': 'INCOMPLETE',
                  'utc': utc(), 'calls_this_activation': calls, 'gaps_this_activation': errors,
                  'observations': count, 'strategy_evaluations': 0, 'deepseek_calls': 0,
                  'venue_certified_backtest': False, 'forward_nominees': [],
                  'coverage': 'native_perp_metadata_all; books_and_bars_fixed10; historical_gaps_unknown',
                  'historical_backfill_is_prospective': False}
        tmp = root/'status.tmp';tmp.write_bytes(encoded(status));os.replace(tmp, root/'status.json')
        print(json.dumps(status))
        return status
    finally:
        db.close()


def main():
    p = argparse.ArgumentParser();p.add_argument('--root', type=Path, required=True)
    a = p.parse_args()
    if os.name != 'posix' or a.root.absolute() != Path('/var/lib/trendatlas-phase2'):
        raise ValueError('CLI_requires_isolated_VPS_root')
    import fcntl
    with (a.root/'collector.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        collect(a.root)


if __name__ == '__main__':main()
