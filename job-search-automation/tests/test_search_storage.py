from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jobfinder.config import load_config
from jobfinder.demo import demo_items
from jobfinder.extract import extract_job
from jobfinder.score import evaluate
from jobfinder.search import build_queries
from jobfinder.storage import JobStore
from jobfinder.utils import utc_now_iso


class SearchAndStorageTests(unittest.TestCase):
    def test_query_modes_expand_coverage(self) -> None:
        config = load_config()
        quick = build_queries(config.search, "quick")
        standard = build_queries(config.search, "standard")
        deep = build_queries(config.search, "deep")
        self.assertEqual(len(quick), 6)
        self.assertGreater(len(standard), len(quick))
        self.assertGreaterEqual(len(deep), 55)
        self.assertTrue(any(query.startswith("site:ostjob.ch") for query in deep))
        self.assertTrue(any(query.startswith("site:pwc.ch") for query in deep))

    def test_history_marks_only_first_observation_new(self) -> None:
        config = load_config()
        job = extract_job(*demo_items()[0])
        assessment = evaluate(job, config.data)
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "history.sqlite3")
            try:
                first_scan = store.start_scan("demo", "offline", utc_now_iso())
                self.assertTrue(store.upsert(first_scan, job, assessment))
                second_scan = store.start_scan("demo", "offline", utc_now_iso())
                self.assertFalse(store.upsert(second_scan, job, assessment))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
