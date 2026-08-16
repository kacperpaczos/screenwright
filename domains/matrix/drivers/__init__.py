"""Adaptery StoreDriver per dystrybucja."""

from domains.matrix.drivers.appcenter import AppCenterDriver
from domains.matrix.drivers.discover import DiscoverDriver
from domains.matrix.drivers.gnome_software import GnomeSoftwareDriver
from domains.matrix.drivers.mintinstall import MintInstallDriver
from domains.matrix.drivers.ubuntu import UbuntuDriver

__all__ = [
    "AppCenterDriver",
    "DiscoverDriver",
    "GnomeSoftwareDriver",
    "MintInstallDriver",
    "UbuntuDriver",
]
