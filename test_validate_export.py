import csv
import tempfile
import unittest
from pathlib import Path
from validate_export import REQUIRED, validate

class ValidationTests(unittest.TestCase):
    def test_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            previous, candidate = [Path(directory) / n for n in ('previous.csv', 'candidate.csv')]
            fields = sorted(REQUIRED)
            rows = [dict.fromkeys(fields, '') for _ in range(100)]
            for i, row in enumerate(rows):
                row.update(Name=f'Fighter {i}', URL=f'http://ufcstats.com/fighter-details/{i:016x}', BadSample='False')
            def write(path, values):
                with path.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(values)
            write(previous, rows)
            for count in (100, 95):
                write(candidate, rows[:count])
                validate(candidate, previous)
            write(candidate, [dict(row, BadSample='True') for row in rows])
            with self.assertRaisesRegex(ValueError, 'bad sample'): validate(candidate, previous)
            write(candidate, [dict(rows[0], BadSample='unknown')])
            with self.assertRaisesRegex(ValueError, 'invalid BadSample'): validate(candidate, previous)
            write(candidate, rows[:94])
            with self.assertRaisesRegex(ValueError, 'roster drop'): validate(candidate, previous)
            write(candidate, rows + [rows[0]])
            with self.assertRaisesRegex(ValueError, 'duplicate profile'): validate(candidate, previous)
            candidate.write_text('Name,URL\n"unterminated')
            with self.assertRaises((ValueError, csv.Error)): validate(candidate, previous)
            write(candidate, [dict(rows[0], URL='invalid')])
            with self.assertRaisesRegex(ValueError, 'unusable'): validate(candidate, previous)

if __name__ == '__main__': unittest.main()
