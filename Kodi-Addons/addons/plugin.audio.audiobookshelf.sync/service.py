# SPDX-License-Identifier: GPL-3.0-or-later
"""Background service entry point (progress sync, downloads, auto-download)."""
from resources.lib import service_core

if __name__ == "__main__":
    service_core.Service().run()
