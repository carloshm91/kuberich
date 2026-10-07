"""Read installed metadata and original notices without importing dependencies.

Invoked with the isolated runtime interpreter, not the development environment.
"""

import base64
import hashlib
import json
import sys
from importlib.metadata import distributions
from pathlib import Path
from typing import Any


def inventory() -> dict[str, Any]:
    packages = []
    prefix = Path(sys.prefix).resolve()
    for distribution in distributions():
        metadata = distribution.metadata
        notices = []
        for file in distribution.files or []:
            parts = Path(str(file)).parts
            if not any(part.endswith(".dist-info") for part in parts):
                continue
            name = Path(str(file)).name.lower()
            if not (
                "licenses" in parts or name.startswith(("license", "copying", "notice", "authors"))
            ):
                continue
            path = Path(str(distribution.locate_file(file))).resolve()
            if not path.is_relative_to(prefix) or not path.is_file():
                raise ValueError("Dependency notice leaves the owned installation")
            content = path.read_bytes()
            notices.append(
                {
                    "file": str(file),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "content_base64": base64.b64encode(content).decode("ascii"),
                }
            )
        packages.append(
            {
                "name": metadata["Name"],
                "version": distribution.version,
                "license_expression": metadata.get("License-Expression"),
                "license": metadata.get("License"),
                "classifiers": metadata.get_all("Classifier", []),
                "requires": metadata.get_all("Requires-Dist", []),
                "project_urls": metadata.get_all("Project-URL", []),
                "home_page": metadata.get("Home-page"),
                "notices": notices,
            }
        )
    return {"python": sys.version.split()[0], "packages": sorted(packages, key=lambda p: p["name"])}


if __name__ == "__main__":
    value = json.dumps(inventory(), sort_keys=True) + "\n"
    if len(sys.argv) == 2:
        Path(sys.argv[1]).write_text(value, encoding="utf-8")
    else:
        print(value, end="")
