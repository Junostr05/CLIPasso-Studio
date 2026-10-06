"""The progress of the running job on the app's taskbar button (Windows: ITaskbarList3) – green while it runs, yellow
while it is paused, red when it failed – so a long job can be followed with the window minimised. Through COM with
ctypes (no extra package); on other systems, or when Windows refuses, it does nothing."""

from __future__ import annotations

import sys

# TBPFLAG
NOPROGRESS, INDETERMINATE, NORMAL, ERROR, PAUSED = 0x0, 0x1, 0x2, 0x4, 0x8
STEPS = 1000  # the bar's resolution (calls only when it moves by a step)

CLSID_TASKBARLIST = "{56FDF344-FD6D-11d0-958A-006097C9A090}"
IID_ITASKBARLIST3 = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}"
# vtable: IUnknown (0-2), ITaskbarList HrInit (3) … ITaskbarList3 SetProgressValue (9), SetProgressState (10)
_HR_INIT, _SET_VALUE, _SET_STATE = 3, 9, 10


def state_for(status: str | None, fraction: float | None) -> tuple[int, float | None]:
    """(taskbar state, filled part 0..1 or None) for a job's status and progress."""
    if status == "running":
        if fraction is None or fraction <= 0:
            return INDETERMINATE, None  # (loading the models: no steps yet)
        return NORMAL, min(fraction, 1.0)
    if status == "paused":
        return PAUSED, min(max(fraction or 0.0, 0.0), 1.0)
    if status == "failed":
        return ERROR, 1.0
    if status == "busy":  # other work in the background (moving folders, unpacking an update)
        return (INDETERMINATE, None) if fraction is None else (NORMAL, min(max(fraction, 0.0), 1.0))
    return NOPROGRESS, None


class Taskbar:
    """The taskbar button of the window ``hwnd`` (``int(widget.winId())``)."""

    def __init__(self, hwnd: int):
        self.hwnd = int(hwnd)
        self._list = None
        self._last: tuple | None = None
        self.error = ""  # why there is no taskbar object (Windows)
        if sys.platform == "win32":
            try:
                self._list = _create()
            except (OSError, AttributeError, ValueError) as exc:
                self.error = str(exc)

    @property
    def available(self) -> bool:
        return self._list is not None

    def set(self, state: int, fraction: float | None = None) -> None:
        key = (state, None if fraction is None else round(fraction * STEPS))
        if key == self._last:
            return
        self._last = key
        if self._list is None:
            return
        try:
            _call(self._list, _SET_STATE, ("hwnd", "int"), self.hwnd, state)
            if fraction is not None and state not in (NOPROGRESS, INDETERMINATE):
                _call(self._list, _SET_VALUE, ("hwnd", "u64", "u64"), self.hwnd, key[1], STEPS)
        except OSError:  # (the button is not there yet, e.g. right after the start)
            self._last = None

    def clear(self) -> None:
        self.set(NOPROGRESS)


def _create():
    import ctypes

    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)  # (Qt has done it already on the GUI thread: S_FALSE)
    clsid, iid = _guid(CLSID_TASKBARLIST), _guid(IID_ITASKBARLIST3)
    ptr = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(ptr))  # INPROC
    if hr != 0 or not ptr.value:
        raise OSError(f"CoCreateInstance(TaskbarList) failed: {hr & 0xFFFFFFFF:#010x}")
    _call(ptr, _HR_INIT, ())
    return ptr


def _guid(text: str):
    import ctypes

    class GUID(ctypes.Structure):
        _fields_ = [("data1", ctypes.c_uint32), ("data2", ctypes.c_uint16), ("data3", ctypes.c_uint16),
                    ("data4", ctypes.c_ubyte * 8)]

    g = GUID()
    hr = ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
    if hr != 0:
        raise ValueError(text)
    return g


def _call(obj, index: int, kinds: tuple, *args) -> None:
    """Call the COM method ``index`` of the object's vtable; an error HRESULT raises OSError."""
    import ctypes
    from ctypes import wintypes

    types = {"hwnd": wintypes.HWND, "int": ctypes.c_int, "u64": ctypes.c_ulonglong}
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *(types[k] for k in kinds))
    hr = proto(vtable[index])(obj, *args)
    if hr < 0:
        raise OSError(f"ITaskbarList3 call {index} failed: {hr & 0xFFFFFFFF:#010x}")
