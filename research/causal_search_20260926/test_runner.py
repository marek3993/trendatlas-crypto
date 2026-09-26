from pathlib import Path
import json
import tempfile
import sys
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
import run
import engine
from test_engine import fixture,params


class RunnerTests(unittest.TestCase):
    def test_fold_data_ranges_precede_oos(self):
        spec,_=engine.load_spec()
        for fold in spec['folds']:
            self.assertLess(fold['train_end'],fold['validation_start'])
            self.assertLess(fold['validation_end'],fold['test_start'])

    def test_search_budget_and_parameter_count_locked(self):
        spec,_=engine.load_spec();self.assertEqual(len(spec['variants']),324)
        self.assertEqual(len(spec['partitions']),6)
        self.assertEqual(len({p['id'] for p in spec['variants']}),324)
        self.assertFalse(spec['sealed']['historical_available'])

    def test_cash_fallback_no_artificial_profit(self):
        m=engine.market_from_frames(fixture());r=run.cash_run(m,'2019-01-01','2019-12-31')
        self.assertEqual(engine.summarize(r)['cagr'],0)
        self.assertEqual(len(r['rows']),365)

    def test_selection_never_reads_other_window(self):
        m=engine.market_from_frames(fixture());r=engine.simulate(m,params(),1.25,start='2019-10-01',end='2020-01-31')
        s=engine.summarize(r);s.update(parameter_stability=1,double_cost_cagr=.1,delayed_entry_cagr=.1,
                                        profitable_fold_fraction=1,worst_fold_return=.1)
        records=json.loads(json.dumps({'one':{'2020':s,'2021':dict(cagr=999)}}))
        part=dict(mode='robust',cap=1.25)
        before=run.choose(records,part,'2020','growth')
        self.assertEqual(before[0],'one')
        records['one']['2021']['cagr']=-1
        self.assertEqual(before,run.choose(records,part,'2020','growth'))

    def test_fresh_and_cached_search_use_identical_native_metrics_and_selection(self):
        m=engine.market_from_frames(fixture());r=engine.simulate(m,params(),1.25,start='2019-10-01',end='2020-01-31')
        metric=engine.summarize(r)
        metric.update(cagr=.2,max_drawdown=.1,calmar=np.float64(2),parameter_stability=1,
                      double_cost_cagr=.1,delayed_entry_cagr=.1,profitable_fold_fraction=1,worst_fold_return=.1)
        p=params();part=dict(id='synthetic',mode='robust',cap=1.25)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(run.engine,'simulate',return_value=r),patch.object(run,'metric_windows',return_value={'2020':metric}),patch.object(run,'add_grid_stability'):
                fresh=run.run_search(m,dict(variants=[p]),part,root,root,'test')
                cached=run.run_search(m,dict(variants=[p]),part,root,root,'test')
            self.assertIs(type(fresh[p['id']]['2020']['calmar']),float)
            self.assertEqual(fresh,cached)
            self.assertEqual(run.choose(fresh,part,'2020','growth')[0],p['id'])
            self.assertEqual(run.choose(fresh,part,'2020','growth'),run.choose(cached,part,'2020','growth'))

    def test_research_output_rejects_production_paths(self):
        with self.assertRaises(ValueError):run.bounded_out(run.ROOT/'outputs'/'research_test_forbidden')


if __name__=='__main__':unittest.main()
