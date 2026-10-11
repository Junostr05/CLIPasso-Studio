"""The version number is kept in one place (clipasso_studio/__init__.py); the packaging reads it."""

import re
from pathlib import Path

import clipasso_studio

ROOT = Path(__file__).resolve().parent.parent


def test_version_is_kept_in_one_place():
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+)?", clipasso_studio.__version__)  # (PEP 440: 3.1.0b1)
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in pyproject
    assert not re.search(r'^version\s*=\s*"', pyproject, re.M)
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert not re.search(r'#define AppVersion "', iss)
    assert not (ROOT / "packaging" / "version_info.txt").exists()


def test_version_info_template_is_filled_like_the_spec():
    info = (ROOT / "packaging" / "version_info.in").read_text(encoding="utf-8")
    assert "{version}" in info and "{vtuple}" in info
    filled = info.replace("{version}", "3.1.4").replace("{vtuple}", str((3, 1, 4, 0)))
    assert "filevers=(3, 1, 4, 0)" in filled and "'ProductVersion', '3.1.4'" in filled
    spec = (ROOT / "packaging" / "clipasso_studio.spec").read_text(encoding="utf-8")
    assert "version_info.in" in spec
    # small patches: the exe carries the release in which it last changed (not the app's version), the app's
    # modules are files next to it – the same text as the 3.3.0 build, so its exe stays the same
    m = re.search(r'^EXE_VERSION = "(\d+)\.(\d+)"$', spec, re.M)
    assert m and (int(m.group(1)), int(m.group(2))) <= tuple(int(n) for n in clipasso_studio.__version__.split(".")[:2])
    assert '_info.replace("{version}", EXE_VERSION)' in spec and "_nums + [0] * (4 - len(_nums))" in spec
    assert 'module_collection_mode={"clipasso_studio": "pyc"}' in spec
    # ... and byte for byte the same from build to build: a fixed build time, a fixed hash seed (splash file list)
    assert 'os.environ.setdefault("SOURCE_DATE_EPOCH", str(EXE_TIMESTAMP))' in spec
    workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    assert workflow.count('PYTHONHASHSEED: "0"') == 1  # (4.0: the onedir build only – installer and portable ZIP)
    assert "onefile" not in workflow and "body_path: release_body.md" in workflow  # (which file to download first)
    downloads = (ROOT / "packaging" / "downloads.md").read_text(encoding="utf-8")
    assert "{version}" in downloads and "CLIPassoStudio-CPU-Setup.exe" in downloads and "Portable.exe" not in downloads


def _pins(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"([A-Za-z0-9_.\-]+)==([^\s\;]+)", line.strip())
        if m:
            out[m.group(1).lower().replace("_", "-")] = m.group(2)
    return out


def test_lock_files_match_the_requirements():
    """Every exact pin of the requirements is in the release lock files (run tools/lock_requirements.py)."""
    req = ROOT / "requirements"
    for ed in ("cpu", "gpu"):
        lock = _pins(req / f"lock-{ed}.txt")
        assert lock, ed
        for name in ("app.txt", "build.txt", f"torch-{ed}.txt"):
            for pkg, ver in _pins(req / name).items():
                assert pkg in lock, (ed, pkg)
                assert lock[pkg].split("+")[0] == ver, (ed, pkg, lock[pkg], ver)


def _imports() -> list[tuple[str, int, str, bool]]:
    """Every absolute import of the app's modules: (file, line, module, optional – in a try that catches the
    ImportError)."""
    import ast

    catches = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}
    out = []
    for path in sorted((ROOT / "clipasso_studio").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            else:
                continue
            optional, p = False, parents.get(node)
            while p is not None and not optional:
                if isinstance(p, ast.Try):
                    for h in p.handlers:
                        types = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
                        optional |= h.type is None or any(getattr(t, "id", "") in catches for t in types)
                p = parents.get(p)
            out += [(path.relative_to(ROOT).as_posix(), node.lineno, n, optional) for n in names]
    return out


def test_the_app_imports_only_what_the_build_contains():
    """3.8.1: the experimental sketch improvement imported scipy – installed for the tests, left out of the build
    (ModuleNotFoundError in the app). Every import of the app is the standard library, the app, or a locked
    requirement; none is one the spec excludes (an optional import in a try that catches the ImportError may)."""
    import ast
    import sys
    from importlib.metadata import packages_distributions

    spec = (ROOT / "packaging" / "clipasso_studio.spec").read_text(encoding="utf-8")
    excludes = ast.literal_eval(re.search(r"^excludes = (\[.*?\n\])", spec, re.S | re.M).group(1))
    assert "scipy" in excludes and "matplotlib" in excludes
    norm = lambda name: re.sub(r"[-_.]+", "-", name).lower()  # noqa: E731
    dists = {ed: {norm(m.group(1)) for m in re.finditer(r"^([A-Za-z0-9_.\-]+)==",
                                                         (ROOT / "requirements" / f"lock-{ed}.txt")
                                                         .read_text(encoding="utf-8"), re.M)}
             for ed in ("cpu", "gpu")}
    of = packages_distributions()
    imports = _imports()
    assert len(imports) > 500 and any(n == "torch" for _, _, n, _ in imports)
    wrong = []
    for path, line, name, optional in imports:
        if optional:
            continue
        if any(name == e or name.startswith(e + ".") for e in excludes):
            wrong.append(f"{path}:{line} {name} (excluded from the build)")
        top = name.split(".")[0]
        if top in sys.stdlib_module_names or top == "clipasso_studio":
            continue
        for ed, locked in dists.items():
            if not {norm(d) for d in of.get(top, [])} & locked:
                wrong.append(f"{path}:{line} {name} (not in lock-{ed}.txt)")
    assert wrong == []


def test_installer_matches_the_app():
    """The uninstaller finds the app data and the files the app writes for it; both editions can be
    installed side by side (own shortcut names); an update removes the libraries of the old version."""
    from clipasso_studio.gui import storage, updates

    raw = (ROOT / "packaging" / "installer.iss").read_bytes()
    iss = raw.decode("utf-8")
    if any(ord(c) > 127 for c in iss):
        assert raw.startswith(b"\xef\xbb\xbf")  # ISCC reads UTF-8 only with a BOM (German texts)
    iss += (ROOT / "packaging" / "uninstall_code.iss").read_text(encoding="ascii")  # (#include)
    assert re.search(r'#define AppDataName "([^"]+)"', iss).group(1) == clipasso_studio.APP_ID
    assert f"AppGuid = '{updates.APP_GUID}'" in iss and "AppId={" + updates.APP_GUID + "_{#Edition}" in iss
    assert storage.MODELS_LOCATION in iss and storage.OUTPUT_LOCATION in iss
    assert 'Type: filesandordirs; Name: "{app}\\_internal"' in iss
    assert '#define ShortcutName "CLIPasso Studio GPU"' in iss and 'Name: "{autodesktop}\\{#ShortcutName}"' in iss


def test_ci_runs_the_phone_page_in_a_browser():
    """The browser tests of the phone page (tests/e2e) run on Linux – they skip themselves without a browser."""
    workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    dev = (ROOT / "requirements" / "dev.txt").read_text(encoding="utf-8")
    assert "playwright install --with-deps chromium" in workflow
    assert any(line.startswith("playwright==") for line in dev.splitlines())
    assert (ROOT / "tests" / "e2e" / "app_harness.py").is_file()
