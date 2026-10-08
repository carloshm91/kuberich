"""Opt-in read-only AKS smoke; explicit test context, no ambient credential fallback."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from kuberich.domain.connections import ConnectionProblem, ConnectionRequest
from kuberich.errors import AppError
from scripts.verify_eks_auth import verify


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--kubectl", required=True)
    parser.add_argument("--acknowledge-test-cluster", required=True, action="store_true")
    args = parser.parse_args()
    try:
        evidence = asyncio.run(
            verify(
                ConnectionRequest(
                    kubeconfig=args.kubeconfig,
                    context=args.context,
                    namespace=args.namespace,
                    timeout=30,
                ),
                Path(args.kubectl),
                provider="aks",
            )
        )
    except (AppError, ConnectionProblem, OSError, ValueError, TypeError, UnicodeError):
        print(
            "AKS smoke failed. Check the explicit test configuration, Azure login and read permissions. No private output was retained.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
