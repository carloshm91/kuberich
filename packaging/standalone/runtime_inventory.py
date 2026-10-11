"""Inspect only the owned build interpreter, without importing the application."""

import json
import platform
import runpy
import sys
import sysconfig
from pathlib import Path

root, output = map(Path, sys.argv[1:])
inventory = runpy.run_path(str(root / "scripts/dependency_inventory.py"))["inventory"]()
inventory.update(
    base_prefix=sys.base_prefix,
    stdlib_license=str(Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"),
    system=platform.system(),
    machine=platform.machine(),
    platform=platform.platform(),
    libc=list(platform.libc_ver()),
)
output.write_text(json.dumps(inventory, sort_keys=True, indent=2) + "\n")
