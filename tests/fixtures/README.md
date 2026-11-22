These existing reduced HTML snapshots contain profile identity, statistics, and fight tables. The earlier investigation recorded their capture as browser-rendered UFCStats pages observed November 16, 2026. That capture history has not been independently reverified; these are offline parser fixtures, not evidence that unattended retrieval currently works.

Source URLs and identities:

| File | Fighter | Source |
|---|---|---|
| 438d497617ecb16e.html | Samuel Sanches | http://ufcstats.com/fighter-details/438d497617ecb16e |
| 4a28cb716c19157a.html | Stephen Thompson | http://ufcstats.com/fighter-details/4a28cb716c19157a |
| 519e4fe37ce9ff75.html | Drew Dober | http://ufcstats.com/fighter-details/519e4fe37ce9ff75 |
| 74939a16c7b56f33.html | Juan Diaz | http://ufcstats.com/fighter-details/74939a16c7b56f33 |
| 787bb1f087ccff8a.html | Ciryl Gane | http://ufcstats.com/fighter-details/787bb1f087ccff8a |

Expected normalized name, record, SLpM, and sample flags are specified in `test_refresh.py`'s EXPECTED mapping and can be checked against these files. The existing Fighter model removes the no-contest suffix when counting fights; tests preserve that behavior. No temporary files or network access are needed to run the fixture tests. These snapshots do not include Kayla's separately supplied excerpt.
