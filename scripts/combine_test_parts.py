"""Combine coverage and evidence from parallel test parts; conflicting files fail."""

import argparse
import shutil
import sys
from pathlib import Path

from coverage import Coverage
from coverage.exceptions import CoverageException

from scripts.ci_policy import TEST_PARTS

DATA = "coverage-part.data"


def collect(parts: Path, prefix: str, count: int, root: Path) -> list[Path]:
    """Copy each part's evidence into `root/artifacts`; return the part coverage files."""
    found = sorted(path.name for path in parts.iterdir()) if parts.is_dir() else []
    expected = sorted(f"{prefix}{index}" for index in range(1, count + 1))
    if found != expected:
        raise ValueError(
            f"Expected test parts {', '.join(expected)}; found {', '.join(found) or 'none'}."
        )
    data = []
    for name in expected:
        part = parts / name
        if not (part / DATA).is_file():
            raise ValueError(f"Test part {name} has no coverage data.")
        data.append(part / DATA)
        evidence = part / "artifacts"
        for source in sorted(evidence.rglob("*")) if evidence.is_dir() else ():
            if source.is_symlink():
                raise ValueError(
                    f"Test part {name} contains a symbolic link: {source.relative_to(part)}"
                )
            target = root / source.relative_to(part)
            if source.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif target.exists():
                if target.read_bytes() != source.read_bytes():
                    raise ValueError(f"Test parts disagree about {target.relative_to(root)}.")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
    return data


def combine(data: list[Path], root: Path) -> None:
    (root / ".coverage").unlink(missing_ok=True)
    coverage = Coverage(data_file=str(root / ".coverage"), config_file=str(root / "pyproject.toml"))
    coverage.combine([str(path) for path in data], strict=True, keep=True)
    coverage.save()
    coverage.load()
    coverage.report(show_missing=True, skip_covered=True)
    coverage.json_report(outfile=str(root / "coverage.json"))
    coverage.xml_report(outfile=str(root / "coverage.xml"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parts", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--count", type=int, default=TEST_PARTS)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        combine(collect(args.parts, args.prefix, args.count, args.root), args.root)
    except (ValueError, OSError, CoverageException) as error:
        print(f"Combining test parts failed: {error}", file=sys.stderr)
        return 1
    print(f"Combined coverage and evidence from {args.count} test parts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
