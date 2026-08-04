from __future__ import annotations

import unittest

from jobfinder.config import load_config
from jobfinder.demo import demo_items
from jobfinder.extract import extract_job
from jobfinder.score import evaluate


class ExtractionScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config()
        cls.values = [extract_job(hit, page) for hit, page in demo_items()]

    def test_json_ld_fields_are_extracted(self) -> None:
        job = self.values[1]
        self.assertEqual(job.company, "Eastern Process Systems AG")
        self.assertEqual((job.workload_min, job.workload_max), (60, 60))
        self.assertTrue(job.verified)
        self.assertEqual(job.extraction_method, "json-ld JobPosting")

    def test_strong_business_central_match(self) -> None:
        assessment = evaluate(self.values[1], self.config.data)
        self.assertTrue(assessment.accepted)
        self.assertGreaterEqual(assessment.score, 8.0)

    def test_senior_title_is_a_stretch_not_rejection(self) -> None:
        assessment = evaluate(self.values[2], self.config.data)
        self.assertTrue(assessment.accepted)
        self.assertTrue(any("senior" in risk for risk in assessment.risks))

    def test_applied_company_is_removed(self) -> None:
        assessment = evaluate(self.values[3], self.config.data)
        self.assertFalse(assessment.accepted)
        self.assertIn("already applied", assessment.removal_reason or "")

    def test_multiple_hard_filters_are_explained(self) -> None:
        assessment = evaluate(self.values[4], self.config.data)
        self.assertFalse(assessment.accepted)
        reason = assessment.removal_reason or ""
        self.assertIn("workload", reason)
        self.assertIn("location", reason)
        self.assertIn("German", reason)
        self.assertIn("5 years", reason)


if __name__ == "__main__":
    unittest.main()
