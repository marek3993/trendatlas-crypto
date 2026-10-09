import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from research import continuous_research_protocol as protocol
from research.continuous_research import planner,schema,broker
from research.continuous_research.common import canonical,digest,atomic
from tests.test_continuous_research import setup,proposal,reply,boot,gene,evaluator,discovery


class ProtocolRegressionTests(unittest.TestCase):
    def test_overlay_creates_missing_package_parents(self):
        from scripts.deploy_continuous_research_protocol import overlay
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);archive=p/'bundle.zip'
            with zipfile.ZipFile(archive,'w') as z:
                for name in protocol.FILES:z.writestr(name,'fixture')
            with zipfile.ZipFile(archive) as z:overlay(z,p/'empty-release')
            for name in protocol.FILES:self.assertEqual((p/'empty-release'/name).read_text(),'fixture')

    def payload(self,db,mail):
        rid,_=planner.ensure_request(db,mail)
        return rid,json.loads(db.execute('SELECT body FROM requests WHERE id=?',(rid,)).fetchone()[0])['payload']

    def test_legacy_wire_unchanged_and_new_example_bound(self):
        with tempfile.TemporaryDirectory() as root:
            db,mail=setup(root);rid,p=self.payload(db,mail)
            old=protocol.BASE_WIRE(p)
            self.assertEqual(protocol.wire_body(p,[rid]),old)
            p['parents']*=2;p['duplicate_genes']=[gene(2),gene(3)]
            p['parents'][0]['diagnostic_only']={'leak':'SEALED_CANARY'}
            for parent in p['parents']:
                parent['validation']=copy.deepcopy(parent['training'])
            new=protocol.wire_body(p)
            text=canonical(new)
            self.assertIn('REQUIRED JSON OUTPUT EXAMPLE',text)
            self.assertIn('evaluation is REQUIRED',text)
            self.assertNotIn('SEALED_CANARY',text)
            self.assertLessEqual(len(text.encode())+256,6500)
            self.assertEqual(new['max_tokens'],1500);db.close()

    def test_old_malformed_native_shape_stays_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            db,mail=setup(root);rid,p=self.payload(db,mail)
            value={'state':'COMPLETE','content':canonical({'type':'json_object','proposals':[proposal()]}),
                   'request':rid,'wire_hash':digest(protocol.BASE_WIRE(p))}
            atomic(mail/'responses'/f'{rid}.json',value);planner.ingest(db,mail)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM proposals').fetchone()[0],0)
            row=json.loads(db.execute('SELECT body FROM ingested').fetchone()[0])
            self.assertEqual(row['errors'],[{'reason':'AI_envelope'}]);db.close()

    def test_new_wire_receipt_remains_exact_and_backtests(self):
        from research.continuous_research import runtime
        with tempfile.TemporaryDirectory() as root:
            db,mail=setup(root)
            with patch.object(planner,'wire_body',protocol.wire_body):
                rid,p=self.payload(db,mail);value=reply()
                atomic(mail/'responses'/f'{rid}.json',{'state':'COMPLETE','content':value['choices'][0]['message']['content'],
                  'request':rid,'wire_hash':digest(protocol.wire_body(p))})
                runtime.tick(db,root,mail,lambda:(None,None),evaluator,discovery_fn=discovery)
            row=json.loads(db.execute("SELECT body FROM proposals WHERE origin='AI_AUTHORED'").fetchone()[0])
            self.assertEqual(row['genes'],proposal()['genes'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM backtests').fetchone()[0],6);db.close()

    def test_unfrozen_or_changed_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            db,mail=setup(root);db.close()
            with self.assertRaisesRegex(ValueError,'protocol_not_frozen'):
                protocol.verify_ledger(Path(root)/'research.sqlite',{'fixture':True})
            with self.assertRaisesRegex(ValueError,'protocol_code_changed'):
                protocol.verify_manifest(Path(__file__).resolve().parents[1],{'files':{}})


if __name__=='__main__':unittest.main()
