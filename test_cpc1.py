"""Regression tests for CPC-1 certificate integrity."""

from __future__ import annotations

import copy
import unittest

import cpc1


class CertificateIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.archive = cpc1.fixture_archive()
        self.cases = cpc1.fixture_cases()

    def test_all_fixture_certificates_validate(self) -> None:
        for case in self.cases:
            with self.subTest(case=case.case_id):
                self.assertTrue(cpc1.validate_certificate(cpc1.decide(case, self.archive), self.archive, case))

    def test_substituted_action_is_rejected(self) -> None:
        case = next(case for case in self.cases if case.case_id == "q1-safe")
        forged = copy.deepcopy(cpc1.decide(case, self.archive))
        forged["decision"] = "ACT(drop_everything)"
        self.assertFalse(cpc1.validate_certificate(forged, self.archive, case))

    def test_forged_observation_is_rejected(self) -> None:
        case = next(case for case in self.cases if case.case_id == "q1-safe")
        forged = copy.deepcopy(cpc1.decide(case, self.archive))
        forged["literals"][0]["observed_value"] = False
        forged["literals"][0]["status"] = "mismatched"
        self.assertFalse(cpc1.validate_certificate(forged, self.archive, case))

    def test_cross_task_precedent_is_rejected(self) -> None:
        case = next(case for case in self.cases if case.case_id == "q1-safe")
        forged = copy.deepcopy(cpc1.decide(case, self.archive))
        forged["negative_precedent"] = "archive-2-unsafe"
        self.assertFalse(cpc1.validate_certificate(forged, self.archive, case))


if __name__ == "__main__":
    unittest.main()
