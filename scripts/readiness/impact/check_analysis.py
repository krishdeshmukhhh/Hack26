"""Standard-library checks using only separately stored synthetic fixtures."""
import csv
import tempfile
import unittest
from pathlib import Path

from analyze import FIELDS, analyze

FIXTURES = Path(__file__).parent / "synthetic-fixtures"


class AnalysisChecks(unittest.TestCase):
    def test_mixed(self):
        result = analyze(FIXTURES / "SYNTHETIC-mixed.csv", True)
        self.assertEqual(result["participants_observed"], 3)
        curio = result["conditions"]["curio"]
        self.assertEqual(curio["started"], 3)
        self.assertEqual(curio["statuses"], {"completed": 1, "error": 1, "timeout": 1})
        self.assertEqual(curio["metrics"]["elapsed_seconds"]["median"], 100)
        self.assertEqual(curio["completed_only_elapsed"]["median"], 100)
        usual = result["conditions"]["usual"]
        self.assertEqual(usual["metrics"]["elapsed_seconds"]["missing"], 1)
        self.assertEqual(usual["metrics"]["effort_1_7"]["observed"], 2)
        self.assertIsNone(result["conditions"]["unassisted"]["completed_only_elapsed"]["median"])
        self.assertEqual(result["successful_pairs_only"][0]["curio_minus_usual_seconds"], -40)
        self.assertEqual(result["participants_without_successful_timed_pair"], 2)
        self.assertEqual(len(result["warnings"]), 2)
        self.assertEqual(len(result["source"]["sha256"]), 64)

    def test_empty_and_mode(self):
        self.assertEqual(analyze(FIXTURES / "SYNTHETIC-empty.csv", True)["conditions"], {})
        with self.assertRaises(ValueError):
            analyze(FIXTURES / "SYNTHETIC-mixed.csv")

    def test_invalid_and_missing(self):
        with (FIXTURES / "SYNTHETIC-mixed.csv").open() as stream:
            original = next(csv.DictReader(stream))
        changes = [{"elapsed_seconds": "nan"}, {"elapsed_seconds": "inf"},
                   {"elapsed_seconds": "-1"}, {"elapsed_seconds": "601"},
                   {"wrong_actions": "1.5"}, {"frustration_1_7": "8"},
                   {"status": "unknown"}, {"period": "3"},
                   {"status": "timeout", "elapsed_seconds": "20"}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "SYNTHETIC-temp.csv"
            def write(rows):
                with path.open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=FIELDS)
                    writer.writeheader()
                    writer.writerows(rows)
            for change in changes:
                with self.subTest(change=change):
                    write([original | change])
                    with self.assertRaises(ValueError):
                        analyze(path, True)
            write([original, original])
            with self.assertRaises(ValueError):
                analyze(path, True)
            write([original | {"elapsed_seconds": "", "interventions": ""}])
            result = analyze(path, True)["conditions"]["usual"]
            self.assertEqual(result["metrics"]["elapsed_seconds"]["missing"], 1)
            self.assertIsNone(result["completed_only_elapsed"]["median"])
            path.write_text("bad,header\n")
            with self.assertRaises(ValueError):
                analyze(path, True)


if __name__ == "__main__":
    unittest.main()
