"""Source parser registry for firmware sync."""

from .apple import sync_apple_support
from .atomos import sync_atomos_support
from .bambu import sync_bambu_wiki
from .byd import sync_byd_release_notes
from .dji import sync_dji_downloads
from .godox import sync_godox_listing
from .merlin import sync_merlin_releases
from .pihole import sync_pihole_releases
from .playstation import sync_playstation_support
from .sony import sync_sony_cscs
from .static_source import sync_static
from .tplink import sync_tplink_downloads

SYNC_HANDLERS = {
    "dji_downloads": sync_dji_downloads,
    "sony_cscs": sync_sony_cscs,
    "godox_listing": sync_godox_listing,
    "apple_support": sync_apple_support,
    "atomos_support": sync_atomos_support,
    "bambu_wiki": sync_bambu_wiki,
    "tplink_downloads": sync_tplink_downloads,
    "playstation_support": sync_playstation_support,
    "pihole_releases": sync_pihole_releases,
    "byd_release_notes": sync_byd_release_notes,
    "merlin_releases": sync_merlin_releases,
    "static": sync_static,
}

SOURCE_VENDOR = {
    "dji_downloads": "dji",
    "sony_cscs": "sony",
    "godox_listing": "godox",
    "apple_support": "apple",
    "atomos_support": "atomos",
    "bambu_wiki": "bambu",
    "tplink_downloads": "tplink",
    "playstation_support": "playstation",
    "pihole_releases": "pihole",
    "byd_release_notes": "byd",
    "merlin_releases": "asuswrt-merlin",
    "static": "static",
}
