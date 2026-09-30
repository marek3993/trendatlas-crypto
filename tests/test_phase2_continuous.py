import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from research.phase2_continuous import broker, collector_v2, runtime
from research.phase2_continuous.engine import digest, evaluate_fold, synthetic_market, targets, validate_genes


class Phase2ContinuousTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_causal_signal_cost_and_complete_episode_stresses(self):
        market = synthetic_market()
        genes = {"family":"J","trend_days":120,"vol_days":20,"vol_target":0.10,"exit_confirm_days":1}
        before = targets(market,genes,600,{"previous":None})
        market.close[800:] *= 50
        self.assertEqual(before.tolist(),targets(market,genes,600,{"previous":None}).tolist())
        nominal = evaluate_fold(market,genes,"2020-08-14","2020-12-11")
        double = evaluate_fold(market,genes,"2020-08-14","2020-12-11",cost_mult=2)
        delayed = evaluate_fold(market,genes,"2020-08-14","2020-12-11",delay_entries=True)
        self.assertLessEqual(double["last_nav"],nominal["last_nav"]+1e-8)
        self.assertTrue(nominal["audit"]["pnl_reconciled"])
        self.assertTrue(nominal["audit"]["episodes_not_split_on_rebalance"])
        self.assertEqual(delayed["days"],nominal["days"])
        with self.assertRaises(ValueError):
            validate_genes(dict(genes,unknown=1))

    def test_two_generations_successor_resume_and_fallback(self):
        first = runtime.run(self.root,None,synthetic=True,workers=1,seconds=50)
        self.assertEqual(first["evaluation_counts"]["COMPLETE"],320)
        self.assertEqual(first["outer_oos"],"LOCKED")
        self.assertEqual(first["forward_2027"],"SEALED")
        again = runtime.run(self.root,None,synthetic=True,workers=1,seconds=10)
        self.assertEqual(again["evaluation_counts"]["COMPLETE"],320)
        with patch.object(broker,"api_key",return_value=None):
            for _ in range(5):self.assertTrue(broker.broker_once(self.root/"mailbox"))
        resumed = runtime.run(self.root,None,synthetic=True,workers=1,seconds=60)
        self.assertTrue(resumed["cycle"][0].endswith("000002"))
        db = sqlite3.connect(self.root/"research.sqlite")
        try:
            self.assertEqual(db.execute("SELECT status FROM cycles ORDER BY ordinal LIMIT 1").fetchone()[0],"SEALED_DEVELOPMENT")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM evaluations WHERE status='COMPLETE'").fetchone()[0],960)
            self.assertEqual(db.execute("SELECT COUNT(*)-COUNT(DISTINCT key) FROM evaluations").fetchone()[0],0)
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])
            key = db.execute("SELECT key FROM evaluations WHERE status='COMPLETE' LIMIT 1").fetchone()[0]
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE evaluations SET status='RUNNING' WHERE key=?",(key,))
        finally:db.close()

    def test_interrupted_reservation_recovers_without_duplicate_key(self):
        runtime.run(self.root,None,synthetic=True,workers=1,seconds=30,steps=1)
        db=sqlite3.connect(self.root/"research.sqlite")
        try:
            key=db.execute("SELECT key FROM evaluations WHERE status='PENDING' LIMIT 1").fetchone()[0]
            db.execute("UPDATE evaluations SET status='RUNNING' WHERE key=?",(key,));db.commit()
        finally:db.close()
        runtime.run(self.root,None,synthetic=True,workers=1,seconds=30,steps=1)
        db=sqlite3.connect(self.root/"research.sqlite")
        try:
            self.assertEqual(db.execute("SELECT status FROM evaluations WHERE key=?",(key,)).fetchone()[0],"COMPLETE")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM evaluations WHERE key=?",(key,)).fetchone()[0],1)
        finally:db.close()

    def test_broker_success_invalid_proposal_and_failure(self):
        runtime.run(self.root,None,synthetic=True,workers=1,seconds=30)
        mailbox = self.root/"mailbox"
        requests = sorted((mailbox/"requests").glob("*.json"))
        request = json.loads(requests[0].read_text())
        parent = request["payload"]["parents"][0]
        genes = dict(parent["genes"])
        family = genes["family"]
        key = next(iter(runtime.SPACE[family]))
        genes[key] = next(v for v in runtime.SPACE[family][key] if v!=genes[key])
        payload = {"candidates":[{"parent":parent["id"],"genes":genes,"hypothesis":"Change one parameter."},
                                 {"parent":parent["id"],"genes":dict(genes,invalid=1),"hypothesis":"Invalid."}]}
        def success(_payload,_key):return json.dumps(payload),{"total_tokens":400,"usd_upper_estimate":.0003},"deepseek-flash"
        with patch.object(broker,"api_key",return_value="test-key"):
            self.assertTrue(broker.broker_once(mailbox,transport=success))
        result = json.loads((mailbox/"responses"/(requests[0].stem+".json")).read_text())
        self.assertEqual(result["state"],"COMPLETE")
        self.assertEqual(result["usage"]["total_tokens"],400)
        accepted = runtime.accepted_mutations(result["content"],request["payload"]["parents"],set(),family)
        self.assertEqual(len(accepted),1)
        def failure(_payload,_key):raise ConnectionError("offline")
        with patch.object(broker,"api_key",return_value="test-key"):
            self.assertTrue(broker.broker_once(mailbox,transport=failure))
        states = [json.loads(p.read_text())["state"] for p in (mailbox/"responses").glob("*.json")]
        self.assertIn("FALLBACK",states)

    def test_document_url_fix_preserves_archive_manifest_lineage(self):
        self.assertEqual(len(collector_v2.DOCS),3)
        self.assertTrue(all(not url.endswith(".md") for url in collector_v2.DOCS))
        manifest = {"experiment_id":collector_v2.CONTRACT["experiment_id"],
                    "collector_sha256":collector_v2.PREVIOUS_COLLECTOR_SHA,
                    "contract_sha256":collector_v2.PREVIOUS_CONTRACT_SHA,
                    "kind":"PUBLIC_DATA_COLLECTION_NOT_FORWARD_TOURNAMENT"}
        (self.root/"collection_manifest.json").write_text(json.dumps(manifest))
        db=sqlite3.connect(self.root/"venue.sqlite")
        try:
            db.execute("CREATE TABLE observations(id INTEGER PRIMARY KEY,row_hash TEXT)")
            db.execute("INSERT INTO observations VALUES(1,'last-hash')")
            db.commit()
        finally:db.close()
        changed=collector_v2.migrate_manifest(self.root)
        self.assertEqual(changed["migrations"][0]["last_row_hash_before"],"last-hash")
        self.assertEqual(changed["migrations"][0]["observation_count_before"],1)
        db=sqlite3.connect(self.root/"venue.sqlite")
        try:self.assertEqual(db.execute("SELECT row_hash FROM observations").fetchone()[0],"last-hash")
        finally:db.close()
        with self.assertRaises(ValueError):collector_v2.migrate_manifest(self.root)

    def test_new_contract_starts_separate_cycle_after_terminal_space(self):
        db=runtime.connect(self.root)
        try:
            with db:
                db.execute("INSERT INTO cycles VALUES(?,?,?,?,?,?,?)",
                           ("phase2_dev_20260929_000001",1,"SPACE_EXHAUSTED",1,"2026-09-29T00:00:00+00:00","old-contract","same-input"))
            new=runtime.ensure_cycle(db,"new-code","new-contract","same-input")
            self.assertTrue(new.endswith("000002"))
            self.assertEqual(db.execute("SELECT status FROM cycles WHERE ordinal=1").fetchone()[0],"SPACE_EXHAUSTED")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cycles").fetchone()[0],2)
            with self.assertRaises(RuntimeError):runtime.ensure_cycle(db,"other-code","another-contract","same-input")
        finally:db.close()


if __name__=="__main__": unittest.main()
