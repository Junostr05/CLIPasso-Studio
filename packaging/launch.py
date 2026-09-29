"""PyInstaller entry script."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from clipasso_studio.__main__ import main

    sys.exit(main())
