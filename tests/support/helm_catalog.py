"""Original in-memory chart/repository bytes for owned Helm lifecycle tests."""

import hashlib
import io
import json
import tarfile
from collections.abc import Mapping

import yaml


def chart_package(
    name: str = "owned-chart",
    version: str = "1.0.0",
    *,
    values: bytes = b"message: synthetic-first\npassword: synthetic-private\n",
    files: Mapping[str, bytes] | None = None,
    metadata: Mapping[str, object] | None = None,
) -> bytes:
    entries = {
        "Chart.yaml": yaml.safe_dump(
            {
                "apiVersion": "v2",
                "name": name,
                "version": version,
                "type": "application",
                **(metadata or {}),
            }
        ).encode(),
        "values.yaml": values,
        "templates/configmap.yaml": (
            b"apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: {{ .Release.Name }}-settings\n"
            b"data:\n  message: {{ .Values.message | quote }}\n  password: {{ .Values.password | quote }}\n"
        ),
        **(files or {}),
    }
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for path, data in sorted(entries.items()):
            item = tarfile.TarInfo(name + "/" + path)
            item.size = len(data)
            item.mode = 0o600
            archive.addfile(item, io.BytesIO(data))
    return output.getvalue()


def repository_index(packages: Mapping[tuple[str, str], bytes]) -> bytes:
    entries: dict[str, list[dict[str, object]]] = {}
    for (name, version), package in packages.items():
        entries.setdefault(name, []).append(
            {
                "name": name,
                "version": version,
                "apiVersion": "v2",
                "urls": [f"{name}-{version}.tgz"],
                "digest": hashlib.sha256(package).hexdigest(),
            }
        )
    return yaml.safe_dump({"apiVersion": "v1", "entries": entries}).encode()


def dependency_lock(
    declarations: list[dict[str, object]], locked: list[dict[str, object]]
) -> bytes:
    fields = (
        "name",
        "version",
        "repository",
        "condition",
        "tags",
        "enabled",
        "import-values",
        "alias",
    )

    def typed(value: dict[str, object]) -> dict[str, object]:
        return {
            key: value[key]
            for key in fields
            if key in value and value[key] not in (None, "", False, [])
        }

    content = (
        json.dumps(
            [[typed(item) for item in declarations], [typed(item) for item in locked]],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .encode()
    )
    return yaml.safe_dump(
        {"digest": "sha256:" + hashlib.sha256(content).hexdigest(), "dependencies": locked}
    ).encode()
