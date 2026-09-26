from datetime import date
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parent))
import paper
import engine
from prepare import write_json
from test_engine import params


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.prices=self.root/'prices';self.out=self.root/'out'
        self.prices.mkdir();self.out.mkdir();spec,_=engine.load_spec()
        with zipfile.ZipFile(paper.HERE/'inputs.zip') as z:
            for identity in spec['identity']:
                name=identity['member'];old=pd.read_csv(z.open(name));price=float(old.close.iloc[-1])
                pd.DataFrame(dict(date=['2026-09-26','2026-09-27'],open=[price,price],high=[price*1.01]*2,low=[price*.99]*2,close=[price]*2,volume=[10000]*2)).to_csv(self.prices/name,index=False)
        self.seal=dict(start='2026-09-27',end='2027-09-26',source_hashes=paper.policy_hashes(),
                       candidates={'B':dict(id='synthetic_only',parameters=params(),cap=1.25,mode='robust')})
        write_json(self.out/'forward_seal.json',self.seal)

    def test_no_future_or_incomplete_bars(self):
        with self.assertRaisesRegex(ValueError,'Incomplete/current/future'):
            paper.evaluate(self.seal,self.prices,self.out,today=date(2026,9,27))

    def test_forward_record_idempotent_and_never_promotes(self):
        a=paper.evaluate(self.seal,self.prices,self.out,today=date(2026,9,28))
        b=paper.evaluate(self.seal,self.prices,self.out,today=date(2026,9,28))
        self.assertEqual(a,b);self.assertFalse(a['orders'])
        self.assertFalse(a['evaluations']['B']['accepted_as_winner'])
        self.assertEqual(a['status'],'FORWARD_PAPER_IN_PROGRESS')

    def test_revised_accepted_sealed_bar_is_rejected(self):
        paper.evaluate(self.seal,self.prices,self.out,today=date(2026,9,28))
        path=self.prices/'BTCUSDT_1d.csv';f=pd.read_csv(path);f.loc[1,'close']*=1.001;f.to_csv(path,index=False)
        with self.assertRaisesRegex(ValueError,'changed or removed'):
            paper.evaluate(self.seal,self.prices,self.out,today=date(2026,9,28))

    def test_changed_frozen_code_is_rejected(self):
        self.seal['source_hashes']={}
        with self.assertRaisesRegex(AssertionError,'fingerprint mismatch'):
            paper.evaluate(self.seal,self.prices,self.out,today=date(2026,9,28))

    def test_changed_historical_bundle_is_rejected_before_forward_evaluation(self):
        altered=self.root/'tampered';altered.mkdir();(altered/'inputs.zip').write_bytes(b'changed history')
        with patch.object(paper,'HERE',altered):
            with self.assertRaisesRegex(AssertionError,'Frozen history bundle changed'):
                paper.policy_hashes()


if __name__=='__main__':unittest.main()
