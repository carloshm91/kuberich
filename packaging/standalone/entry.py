"""PyInstaller entry; all runtime decisions live in the covered package."""

from kuberich.runtime import main

raise SystemExit(main())
