# Parser fixtures

`dji_pocket4p.html` is a single release-note download item captured from
https://www.dji.com/global/downloads/products/osmo-pocket-4p on 2026-09-06.

`dji_pocket4p.pdf` is the unmodified official English release-notes PDF linked
from that page (2026-09-03):
https://terra-1-g.djicdn.com/6189933d30024fc1b331bffe4fe41837/osmo-pocket-4p/RN/20260903/DJI_Osmo_Pocket_4P_Release_Notes_en.pdf

DJI retains copyright. The fixture exercises actual pypdf extraction, including
multiple pages, wrapped bullets, and competing camera/app/accessory versions.
Tests run offline and assert firmware 01.01.71.31, released 2026-09-03.

Other HTML fixtures are small representative vendor extracts used by parser tests.

`browser-devices.json` is a fixed subset for browser interaction tests. It is
intentionally independent of the live device list so management PRs can remove
or rename devices without invalidating UI tests.
