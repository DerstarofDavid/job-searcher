from __future__ import annotations

import unittest

from jobfinder.utils import canonicalize_url, company_matches, parse_workload


class UtilityTests(unittest.TestCase):
    def test_workload_ranges(self) -> None:
        self.assertEqual(parse_workload("Pensum 40–60%"), (40, 60))
        self.assertEqual(parse_workload("workload: 20% to 50%"), (20, 50))
        self.assertEqual(parse_workload("Vollzeit"), (100, 100))

    def test_company_matching_is_tolerant_but_not_overbroad(self) -> None:
        self.assertTrue(company_matches("Julius Baer AG", "Julius Bär"))
        self.assertTrue(company_matches("SIX Group AG", "SIX Group"))
        self.assertFalse(company_matches("HSG Solutions AG", "HSG"))

    def test_tracking_parameters_are_removed(self) -> None:
        value = canonicalize_url("https://Example.com/job/1/?utm_source=x&id=7#top")
        self.assertEqual(value, "https://example.com/job/1?id=7")


if __name__ == "__main__":
    unittest.main()
