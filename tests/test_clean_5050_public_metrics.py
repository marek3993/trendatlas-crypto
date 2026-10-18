"""Metrics timing, common windows and publication integrity, independent of live accounts."""
import hashlib
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trendatlas_clean.public_metrics import build_public,publish_public
from trendatlas_clean.data import Panel

class PublicMetricsTests(unittest.TestCase):
    def panel(self):
        idx=pd.date_range('2019-01-01','2022-12-31')
        close=pd.DataFrame({'BTC':100*np.exp(np.arange(len(idx))*.001),'ETH':50*np.exp(np.arange(len(idx))*.001)},index=idx)
        return Panel(close,close*10000,close*0,pd.DataFrame('OBSERVED',index=idx,columns=close.columns),'a'*64,{})
    def test_cagr_compounds_and_all_cards_share_2021_window(self):
        panel=self.panel();w=panel.close*0;w['BTC']=1
        with patch('trendatlas_clean.public_metrics.target_weights',return_value=w):m,series=build_public(panel,{'kind':'reference','symbol_count':2})
        self.assertEqual(m['window'],{'start':'2021-01-01','end':'2022-12-31','days':730})
        growth=(1+series.net_return).prod()
        self.assertAlmostEqual(m['since_2021']['cagr_pct'],(growth**(365.25/730)-1)*100)
        self.assertEqual(series.date.iloc[0],'2021-01-01');self.assertEqual(m['since_2021']['funding_proxy_days'],0)
        self.assertEqual(m['cash_days_pct'],0)
        self.assertEqual([x['year'] for x in m['annual']],[2021,2022])
    def test_d_close_is_held_on_d_plus_one_exactly_once(self):
        panel=self.panel();w=panel.close*0;w.loc['2021-01-01','BTC']=1
        with patch('trendatlas_clean.public_metrics.target_weights',return_value=w):_,s=build_public(panel,{})
        s=s.set_index('date');self.assertEqual(s.at['2021-01-01','gross_exposure'],0);self.assertEqual(s.at['2021-01-02','gross_exposure'],1);self.assertEqual(s.at['2021-01-03','gross_exposure'],0)
    def test_publication_checksums_and_no_wallet_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);publish_public(self.panel(),{'kind':'reference'},p)
            m=json.loads((p/'clean5050_metrics.json').read_text());self.assertEqual(m['timeseries_sha256'],hashlib.sha256((p/'clean5050_timeseries.csv').read_bytes()).hexdigest())
            self.assertFalse(m['real_account_pnl']);self.assertNotIn('account_balance',m)
    def test_missing_benchmark_refuses_publication(self):
        panel=self.panel();panel.close.loc['2021-05-01':'2021-05-10','BTC']=np.nan
        with self.assertRaises(ValueError):build_public(panel,{})
    def test_missing_calendar_day_refuses_a_misleading_annualization(self):
        panel=self.panel()
        for name in ('close','quote_volume','funding','funding_source'):
            setattr(panel,name,getattr(panel,name).drop(pd.Timestamp('2021-05-01')))
        with self.assertRaises(ValueError):build_public(panel,{})
if __name__=='__main__':unittest.main()
