"""List fighters in either publication schema. Optional case-insensitive name fragment."""

import argparse
from contextlib import closing

from scraper.database import reader

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", nargs="?", default="")
    args = parser.parse_args()
    with closing(reader("ufc_fighters.db")) as db:
        for row in db.execute(
            "SELECT id,name,weight_class,record FROM fighters WHERE name LIKE ? ORDER BY name",
            ("%" + args.name + "%",),
        ):
            print(*row, sep="\t")
