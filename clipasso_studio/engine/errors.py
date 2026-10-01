"""Errors the user can act on (a failed download, a damaged update file, nothing to export …).

``code`` names the translated text (``ui.err.<code>`` in the GUI); the English message is what the
command line and the logs show. ``params`` fill in the text.
"""

from __future__ import annotations


class UserError(RuntimeError):
    def __init__(self, code: str, message: str, **params):
        super().__init__(message)
        self.code = code
        self.params = params
