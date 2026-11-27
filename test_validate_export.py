import csv
import tempfile
import unittest
from pathlib import Path

from scraper.contract import HEADERS, Fighter
from validate_export import changes, guard, read_csv


def row(i=0, **kwargs):
    fields = {
        "name": "Example",
        "url": f"https://www.ufc.com/athlete/example-{i}",
        "fighter_id": str(i),
        "source": "UFC.com",
        "history_status": "unknown",
    }
    return Fighter(**(fields | kwargs))


class ValidationTests(unittest.TestCase):
    def test_retention_and_growth_include_actual_id_overlap(self):
        rows = {str(i): row(i) for i in range(100)}
        guard(rows, dict(list(rows.items())[:95]))
        for other in [
            dict(list(rows.items())[:94]),
            {str(i + 100): row(i + 100) for i in range(100)},
            rows | {str(i): row(i) for i in range(100, 126)},
        ]:
            with self.assertRaisesRegex(ValueError, "Roster"):
                guard(rows, other)

    def test_coverage_and_change_detection(self):
        known = {
            "history_status": "complete",
            "fights_in_ufc": 1,
            "bad_sample": True,
            "last_fight_date": "2026-11-22",
        }
        a = {"a": row(slpm=0, most_recent_fight=1, **known)}
        b = {"a": row(slpm=0, most_recent_fight=2, **known)}
        self.assertFalse(any(changes(a, b).values()))
        with self.assertRaisesRegex(ValueError, "Coverage"):
            guard(a, {"a": row()})
        self.assertEqual(
            changes(a, {"a": row(slpm=1, most_recent_fight=1, **known)})["changed"][
                "a"
            ],
            {"slpm": [0, 1]},
        )

    def test_contract_and_csv_shape(self):
        for invalid in [
            {"name": "Unknown"},
            {"dob": "0"},
            {"url": "https://evil.test/athlete/a"},
            {"height": -1},
            {"strdef": 1.1},
            {"slpm": "nan"},
            {"bad_sample": True},
            {"fights_in_ufc": 0},
            {"fighter_id": ""},
        ]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                row(**invalid)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "file.csv"
            for case in (
                "empty",
                "duplicate",
                "header",
                "width",
                "bad-flag",
                "duplicate-source",
                "malformed",
            ):
                with path.open("w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(
                        list(HEADERS.values()) + (["Name"] if case == "header" else [])
                    )
                    if case != "empty":
                        vals = row(source_id="1").model_dump(mode="json", by_alias=True)
                        if case == "bad-flag":
                            vals["BadSample"] = "unknown"
                        w.writerow(
                            list(vals.values()) + (["extra"] if case == "width" else [])
                        )
                        if case == "duplicate":
                            w.writerow(vals.values())
                        if case == "duplicate-source":
                            w.writerow(
                                row(1, source_id="1").model_dump(mode="json").values()
                            )
                        if case == "malformed":
                            f.write('"abc')
                with (
                    self.subTest(case=case),
                    self.assertRaises((ValueError, csv.Error)),
                ):
                    read_csv(path)
