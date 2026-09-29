import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

from research.phase2_forward import admission, collector


class AdmissionTests(unittest.TestCase):
    def test_new_id_cannot_bypass_refit(self):
        result=admission.check(dt.date(2026,9,29), {'closed_through':'2026-09-28',
            'append_only_verified':True,'complete_pit_coverage':True,'source_hashes_verified':True})
        self.assertIn('fixed_refit_not_due',result['reasons'])
        self.assertIn('no_new_complete_annual_outer_window',result['reasons'])
        self.assertEqual(result['forward_nominees'],[])

    def test_calendar_alone_does_not_launch(self):
        result=admission.check(dt.date(2027,1,1),{})
        self.assertEqual(result['verdict'],'BLOCKED_WITHOUT_STATE_CHANGE')
        self.assertIn('append_only_verified_missing',result['reasons'])

    def test_fold_gaps_and_budget(self):
        c=admission.CONTRACT;b=c['budget']
        self.assertEqual(b['candidate_slots_max'],5*2*3*2*(8+2*4))
        self.assertEqual(b['api_calls_max'],5*3*2*2)
        end=None
        for f in c['windows']['folds']:
            if end:self.assertLess(end,f['outer_exploratory'][0])
            end=f['outer_exploratory'][1]
            self.assertLess(end,'2024-01-01')
            for w in f['inner']:
                self.assertLess(w['train_start'],w['train_end'])
                gap=(dt.date.fromisoformat(w['validation_start'])-dt.date.fromisoformat(w['train_end'])).days-1
                self.assertGreaterEqual(gap,c['windows']['purge_days']+c['windows']['embargo_days'])


class SealedAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).resolve().parents[1]/'causal_migration/runtime.py'
        spec=importlib.util.spec_from_file_location('phase2_migration_test',path)
        cls.runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.runtime)

    def invoke(self,status):
        r=self.runtime
        with patch.object(sys,'argv',['runtime.py','ready','--platform','vps']), \
             patch.object(Path,'resolve',lambda p:p), \
             patch.object(r.legacy,'verify',return_value={'status':status}), \
             patch.object(r.legacy,'load_engine') as load:
            value=r.main()
            if status=='SEALED':load.assert_not_called()
            return value

    def test_sealed_execcondition_is_successful_skip(self):
        self.assertEqual(self.invoke('SEALED'),1)

    def test_failed_and_unknown_remain_failure(self):
        self.assertEqual(self.invoke('FAILED'),255)
        self.assertEqual(self.invoke('UNKNOWN'),255)

    def test_checkpoint_still_admitted(self):
        self.assertEqual(self.invoke('CHECKPOINTED'),0)

    def test_corrupt_sealed_is_not_hidden(self):
        with patch.object(sys,'argv',['runtime.py','ready','--platform','vps']), \
             patch.object(Path,'resolve',lambda p:p), \
             patch.object(self.runtime.legacy,'verify',side_effect=RuntimeError('bad hash')):
            with self.assertRaises(RuntimeError):self.runtime.main()


class PublicCollectorTests(unittest.TestCase):
    def test_account_and_order_requests_forbidden(self):
        for body in [{'type':'clearinghouseState','user':'0x1'}, {'type':'order'},
                     {'type':'metaAndAssetCtxs','user':'0x1'}, {'type':'l2Book','coin':'UNKNOWN'}]:
            with self.assertRaises(ValueError):collector.validate_request(body)

    def test_redirect_forbidden(self):
        with self.assertRaises(ValueError):collector.NoRedirect().redirect_request(None,None,302,'',{},'https://evil.invalid')

    def test_closed_candle_inclusive_endpoint(self):
        q={'type':'candleSnapshot','req':{'coin':'BTC','interval':'1h','startTime':0,'endTime':3599999}}
        value=[{'s':'BTC','i':'1h','t':0,'T':3599999}]
        self.assertEqual(collector.validate_response(q,json.dumps(value)),value)
        value[0]['T']=3600000
        with self.assertRaises(ValueError):collector.validate_response(q,json.dumps(value))

    def test_bad_metadata_alignment(self):
        with self.assertRaises(ValueError):collector.validate_response({'type':'metaAndAssetCtxs'},b'[{"universe":[{"name":"BTC"}]},[]]')

    def test_missing_mark_never_zero(self):
        raw=b'[{"universe":[{"name":"BTC"}]},[{"openInterest":null}]]'
        value=collector.validate_response({'type':'metaAndAssetCtxs'},raw)
        self.assertNotIn('markPx',value[1][0])
        self.assertIsNone(value[1][0]['openInterest'])

    def test_append_only_hash_chain_and_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=collector.open_archive(tmp)
            for _ in range(2):collector.append(db,'metaAndAssetCtxs','',{'type':'metaAndAssetCtxs'},collector.utc(),b'{}','OK')
            rows=db.execute('SELECT payload,payload_sha256,previous_hash,row_hash FROM observations ORDER BY id').fetchall()
            self.assertEqual(rows[1][2],rows[0][3])
            self.assertEqual(hashlib.sha256(zlib.decompress(rows[0][0])).hexdigest(),rows[0][1])
            for sql in ['DELETE FROM observations','UPDATE observations SET status=\'bad\'']:
                with self.assertRaises(sqlite3.IntegrityError):db.execute(sql)
                db.rollback()
            db.close()
            p=Path(tmp)/'collection_manifest.json';p.write_text('{}')
            with self.assertRaises(ValueError):collector.open_archive(tmp)

    def test_error_does_not_create_zero_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(collector,'fetch',side_effect=TimeoutError),patch.object(collector.time,'sleep'):
                status=collector.collect(tmp)
            self.assertGreater(status['gaps_this_activation'],0)
            self.assertEqual(status['verdict'],'INCOMPLETE')
            db=sqlite3.connect(Path(tmp)/'venue.sqlite')
            self.assertEqual(db.execute("SELECT COUNT(*) FROM observations WHERE status='OK'").fetchone()[0],0)
            payload=json.loads(zlib.decompress(db.execute('SELECT payload FROM observations LIMIT 1').fetchone()[0]))
            self.assertIsNone(payload['data']);db.close()


if __name__=='__main__':unittest.main()
