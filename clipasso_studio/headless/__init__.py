"""The sketch engine without a window, for the Mac app: ``python -m clipasso_studio.headless``.

The Mac app (SwiftUI) starts this as a helper process and talks to it in JSON lines over stdin / stdout
(``protocol.py``, ``server.py``); it also exports the parameter schema and the model list as JSON (``export.py``).
Neither Qt nor (until a job runs) PyTorch is imported here.
"""
