"""Choosing the best sketch by its look: LAION's aesthetic score, the user's taste from thumbs up / down (logistic
regression on CLIP embeddings), the embeddings kept with the runs, the setting and the thumbs in the studio."""

import json
import os

import numpy as np
import pytest

from clipasso_studio.engine import model_store

HAS_CLIP = model_store.is_available("clip:ViT-B/32")
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">'
       '<path d="M 20 112 C 60 40 160 40 204 112" fill="none" stroke="#000000" stroke-width="6"/></svg>')


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def _embs(n, seed=0):
    rng = np.random.default_rng(seed)
    return [_unit(rng.normal(size=512)) for _ in range(n)]


def test_laion_head():
    from clipasso_studio.engine import aesthetic

    w, b = aesthetic.head()
    assert w.shape == (512,) and 3.0 < b < 4.0
    assert aesthetic.beauty(np.zeros(512, np.float32)) == pytest.approx(b)
    e = _unit(w)  # the direction the head likes most
    assert aesthetic.beauty(e) > aesthetic.beauty(-e)


def test_embedding_belongs_to_its_sketch(tmp_path):
    from clipasso_studio.engine import aesthetic

    svg = tmp_path / "best_iter.svg"
    svg.write_text(SVG)
    e = _embs(1)[0]
    aesthetic.save_embedding(str(tmp_path), str(svg), e)
    assert np.allclose(aesthetic.read_embedding(str(tmp_path), str(svg)), e)
    assert np.allclose(aesthetic.read_embedding(str(tmp_path)), e)  # (any sketch of the run)
    svg.write_text(SVG.replace("204 112", "200 100"))  # erased or edited since
    assert aesthetic.read_embedding(str(tmp_path), str(svg)) is None
    assert aesthetic.read_embedding(str(tmp_path / "nowhere")) is None


def test_taste_needs_ten_ratings_of_both_kinds():
    from clipasso_studio.engine import aesthetic

    rng = np.random.default_rng(1)
    like = _unit(rng.normal(size=512))
    embs = [_unit(like * (1 if k % 2 else -1) * 0.3 + rng.normal(size=512) * 0.05) for k in range(12)]
    labels = np.array([k % 2 == 1 for k in range(12)])
    assert aesthetic.train(np.array(embs[:9]), labels[:9]) is None  # too few
    assert aesthetic.train(np.array(embs), np.ones(12, bool)) is None  # only thumbs up
    model = aesthetic.train(np.array(embs), labels)
    assert model["n"] == 12 and model["up"] == 6 and len(model["w"]) == 512
    assert aesthetic.taste(embs[1], model) > 0 > aesthetic.taste(embs[0], model)
    fresh_like, fresh_dislike = _unit(like * 0.3 + rng.normal(size=512) * 0.05), _unit(-like * 0.3)
    assert aesthetic.taste(fresh_like, model) > aesthetic.taste(fresh_dislike, model)
    json.dumps(model)  # kept as JSON


def test_ratings_are_kept_and_forgotten(user_data):
    from clipasso_studio.engine import aesthetic

    embs = _embs(12, seed=3)
    for k, e in enumerate(embs):
        data = aesthetic.set_rating(f"job/run{k}", e, 1 if k < 6 else -1)
        assert (data["model"] is not None) == (k >= 9)
    assert aesthetic.counts() == (6, 6) and aesthetic.load_taste()["model"]["n"] == 12
    aesthetic.set_rating("job/run0", embs[0], -1)  # changed its mind
    assert aesthetic.counts() == (5, 7)
    data = aesthetic.set_rating("job/run0", None, None)  # taken back
    assert aesthetic.counts(data) == (5, 6) and data["model"]["n"] == 11
    aesthetic.set_rating("job/run1", None, None)
    assert aesthetic.load_taste()["model"]["n"] == 10
    aesthetic.set_rating("job/run2", None, None)
    assert aesthetic.load_taste()["model"] is None  # fewer than ten again
    aesthetic.forget_taste()
    assert aesthetic.counts() == (0, 0) and not aesthetic.taste_path().exists()


def test_choose():
    from clipasso_studio.engine import aesthetic

    w, _ = aesthetic.head()
    nice, plain = _unit(w), _unit(-w)
    fid = [70.0, 69.0, 64.0]
    clip = [70.0, 69.0, 64.0]
    assert aesthetic.choose(fid, [plain, nice, nice], "faithful", clip=clip) == 0
    assert aesthetic.choose(fid, [plain, nice, nice], "beautiful", clip=clip) == 1  # a little less similar, nicer
    assert aesthetic.choose(fid, [plain, plain, nice], "beautiful", clip=clip) == 0  # nicer, but far off
    assert aesthetic.choose(fid, [plain, None, nice], "beautiful", clip=clip) == 0  # (an embedding is missing)
    assert aesthetic.choose(fid, [plain, nice, nice], "beautiful", clip=[70.0, None, 64.0]) == 0
    assert aesthetic.choose([1.0], [nice], "beautiful", clip=[60.0]) == 0
    model = {"mean": [0.0] * 512, "w": list(-w / np.linalg.norm(w) * 5), "b": 0.0}  # likes what LAION does not
    assert aesthetic.choose(fid, [nice, plain, plain], "mine", model, clip) == 1
    assert aesthetic.choose(fid, [nice, plain, plain], "mine", None, clip) == 0  # not learnt yet: as before


def test_finish_job_picks_by_the_setting(tmp_path, user_data):
    from clipasso_studio.engine import aesthetic, jobs

    w, _ = aesthetic.head()
    target = tmp_path / "in.png"
    from PIL import Image

    Image.new("RGB", (32, 32), "white").save(target)
    job = tmp_path / "job"
    results = []
    for k, (score, emb) in enumerate(((70.0, _unit(-w)), (69.5, _unit(w)))):
        run = job / f"in_seed{k}"
        run.mkdir(parents=True)
        (run / "best_iter.svg").write_text(SVG)
        aesthetic.save_embedding(str(run), str(run / "best_iter.svg"), emb)
        results.append(jobs.SeedResult(seed=k, run_name=run.name, run_dir=str(run), best_loss=0.5, best_iter=10,
                                       iterations_done=10, best_svg=str(run / "best_iter.svg"), status="done",
                                       method="swiftsketch", clip_score=score))
    settings = {"method": "swiftsketch", "num_sketches": 2}
    assert jobs.finish_job(str(job), str(target), settings, results)["best_run"] == "in_seed0"
    summary = jobs.finish_job(str(job), str(target), dict(settings, best_by="beautiful"), results)
    assert summary["best_run"] == "in_seed1" and summary["best_by"] == "beautiful"
    assert summary["runs"][1]["aesthetic"] > summary["runs"][0]["aesthetic"]
    assert jobs.finish_job(str(job), str(target), dict(settings, best_by="mine"), results)["best_run"] == "in_seed0"
    assert jobs.write_meta(str(job), ratings={"in_seed1": 1})["ratings"] == {"in_seed1": 1}


def test_best_by_setting():
    from clipasso_studio import settings_schema as schema

    for method in ("clipasso", "swiftsketch", "controlsketch"):
        s = schema.default_settings(method)
        assert s["best_by"] == "faithful"
        p = schema.PARAMS_BY_KEY.get("best_by") or next(q for q in schema.params_for(method) if q.key == "best_by")
        assert p.choices == ("faithful", "beautiful", "mine")
        assert schema.is_enabled(p, dict(s, num_sketches=3, turbo=False))
        assert not schema.is_enabled(p, dict(s, num_sketches=1))
        assert schema.normalize(dict(s, best_by="mine"))["best_by"] == "mine"
    assert "best_by" not in schema.default_settings("scenesketch")
    assert ["--best_by", "beautiful"] == schema.to_cli_args(dict(schema.default_settings("clipasso"),
                                                                 best_by="beautiful"))[-2:]


@pytest.mark.skipif(not HAS_CLIP, reason="CLIP ViT-B/32 missing (run tools/fetch_models.py)")
def test_embedding_of_a_run_in_its_own_process(tmp_path):
    import subprocess
    import sys

    from clipasso_studio.engine import aesthetic

    run = tmp_path / "run"
    run.mkdir()
    (run / "best_iter.svg").write_text(SVG)
    code = subprocess.run([sys.executable, "-m", "clipasso_studio", "--embed", str(run)], capture_output=True,
                          text=True, timeout=300, cwd=os.path.dirname(os.path.dirname(__file__)))
    assert code.returncode == 0, code.stderr
    e = aesthetic.read_embedding(str(run), str(run / "best_iter.svg"))
    assert e.shape == (512,) and abs(float(np.linalg.norm(e)) - 1) < 1e-3
    assert 1.0 < aesthetic.beauty(e) < 10.0
