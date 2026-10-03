"""PyInstaller entry script."""

import multiprocessing
import sys

if __name__ == "__main__":
    from clipasso_studio import gpu_runtime

    gpu_runtime.activate()  # PyTorch for older graphics cards, if switched on: before anything imports torch
    multiprocessing.freeze_support()  # (worker processes start here too, so they use the same PyTorch)
    from clipasso_studio.__main__ import main

    sys.exit(main())
