"""3.5: the two layers of a SceneSketch cell (background, object) – shown, sent to the phone, exported."""

import os
import xml.etree.ElementTree as ET

from tests.helpers import SCENE_BG, SCENE_OBJ, fake_scene_job

NS = "{http://www.w3.org/2000/svg}"
INK = "{http://www.inkscape.org/namespaces/inkscape}"


def _ds(svg: str) -> list[str]:
    return [el.get("d") for el in ET.fromstring(svg).iter(f"{NS}path")]


def test_cell_parts(tmp_path):
    from clipasso_studio.gui import scene_layers, strokes

    job = fake_scene_job(str(tmp_path), "scene_job", str(tmp_path / "scene.png"))
    cell = os.path.join(job, "scene_scenesketch_L8_level0")
    with open(os.path.join(cell, "best_iter.svg"), encoding="utf-8") as f:
        svg = f.read()
    assert scene_layers.available(cell) and not scene_layers.available(str(tmp_path))
    assert _ds(scene_layers.part(svg, cell, "background")) == SCENE_BG
    assert _ds(scene_layers.part(svg, cell, "object")) == SCENE_OBJ
    assert scene_layers.part(svg, cell, "all") == svg and scene_layers.part(svg, str(tmp_path), "object") == svg
    # after the eraser (a stroke of each layer removed) the layers still part right
    edited = strokes.remove_strokes(svg, [0, 3])
    assert _ds(scene_layers.part(edited, cell, "background")) == SCENE_BG[1:]
    assert _ds(scene_layers.part(edited, cell, "object")) == SCENE_OBJ[:1]
    # two layers: background below the object, named as given
    root = ET.fromstring(scene_layers.layered(svg, cell, ("Hintergrund", "Objekt")))
    groups = [g for g in root.iter(f"{NS}g") if g.get(f"{INK}groupmode") == "layer"]
    assert [g.get(f"{INK}label") for g in groups] == ["Hintergrund", "Objekt"]
    assert [[p.get("d") for p in g] for g in groups] == [SCENE_BG, SCENE_OBJ]


def test_layered_export(tmp_path, user_data):
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import export_jobs

    settings_module._instance = None
    job = fake_scene_job(str(tmp_path), "scene_job", str(tmp_path / "scene.png"))
    src = os.path.join(job, "scene_scenesketch_L8_level0", "best_iter.svg")
    dest = tmp_path / "layers.svg"
    sketch = export_jobs.info(src, os.path.dirname(src))
    o = export_jobs.check("svglayers", {"style": "pencil", "background": "#ffeecc", "frame": "content"}, sketch)
    export_jobs.run("svglayers", src, os.path.dirname(src), str(dest), o)
    root = ET.parse(dest).getroot()
    groups = [g for g in root.iter(f"{NS}g") if g.get(f"{INK}groupmode") == "layer"]
    assert len(groups) == 2 and all(len(list(g.iter())) > 1 for g in groups)  # (styled strokes stay in their layer)
    assert any(el.get("fill") == "#ffeecc" for el in root.iter(f"{NS}rect"))
    assert export_jobs.extension("svglayers") == "svg" and export_jobs.applies("svglayers")["transparent"]
    settings_module._instance = None
