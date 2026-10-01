"""Gallery 2.0: model / view, scan cache, multi-selection, name / tags / notes, many results."""

import json
import os
import time

import pytest


def _job(out, name, created, clip=50.0, method="swiftsketch", seconds=10.0, finished=True):
    from clipasso_studio import settings_schema as schema

    job = os.path.join(out, name)
    run = os.path.join(job, f"{name}_run")
    os.makedirs(run)
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224"><path d="M 10 10 C 20 20 30 30 '
           '40 40" stroke="rgb(0,0,0)" stroke-width="2" fill="none"/></svg>')
    with open(os.path.join(run, "best_iter.svg"), "w") as f:
        f.write(svg)
    summary = {"target": os.path.join(out, f"{name}.png"), "created": created,
               "settings": schema.default_settings(method), "method": method, "clip_score": clip,
               "seconds": seconds, "best_svg": os.path.join(run, "best_iter.svg"), "best_run": f"{name}_run",
               "runs": [{"seed": 0, "run_name": f"{name}_run", "run_dir": run, "best_loss": 0.2, "best_iter": 0,
                         "iterations_done": 1, "best_svg": os.path.join(run, "best_iter.svg"), "status": "done",
                         "method": method, "clip_score": clip, "seconds": seconds}]}
    if finished:
        with open(os.path.join(job, "job.json"), "w") as f:
            json.dump(summary, f)
    return job


@pytest.fixture
def gallery(qapp, tmp_path, user_data):
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.pages.gallery import GalleryPage

    settings_module._instance = None
    out = tmp_path / "out"
    out.mkdir()
    app_settings().data["output_dir"] = str(out)
    page = GalleryPage()
    page.resize(1000, 700)
    page.show()
    yield page, str(out)
    page.close()
    settings_module._instance = None


def test_meta_is_kept_when_a_job_is_finished_again(tmp_path):
    from clipasso_studio.engine import jobs

    job = _job(str(tmp_path), "a", "2026-09-01 10:00:00")
    with open(os.path.join(job, "job.json")) as f:
        legacy = json.load(f)
    legacy["favourite"] = True  # a favourite of version 2.x
    with open(os.path.join(job, "job.json"), "w") as f:
        json.dump(legacy, f)
    assert jobs.job_summary(job)["favourite"] is True
    jobs.write_meta(job, favourite=False, title="My camel", tags=["animals"], notes="for Anna")
    s = jobs.job_summary(job)
    assert s["favourite"] is False and s["title"] == "My camel" and s["tags"] == ["animals"]
    jobs.write_meta(job, title=None)
    assert "title" not in jobs.read_meta(job) and jobs.read_meta(job)["notes"] == "for Anna"
    with pytest.raises(KeyError):
        jobs.write_meta(job, colour="red")


def test_scan_cache_reads_only_changed_jobs(tmp_path, monkeypatch):
    from clipasso_studio.engine import jobs
    from clipasso_studio.gui.pages.gallery import ScanCache

    a = _job(str(tmp_path), "a", "2026-09-01 10:00:00")
    _job(str(tmp_path), "b", "2026-09-02 10:00:00")
    unfinished = _job(str(tmp_path), "c", "2026-09-03 10:00:00", finished=False)
    jobs.write_state(unfinished, os.path.join(str(tmp_path), "c.png"), {"method": "swiftsketch"}, "interrupted")
    cache = ScanCache()
    assert len(cache.scan(str(tmp_path))) == 3
    reads = []
    real = jobs.job_summary
    monkeypatch.setattr(jobs, "job_summary", lambda d: reads.append(os.path.basename(d)) or real(d))
    cache.scan(str(tmp_path))
    assert reads == ["c"]  # only the unfinished one (its sketches may change)
    jobs.write_meta(a, favourite=True)
    reads.clear()
    found = dict(cache.scan(str(tmp_path)))
    assert sorted(reads) == ["a", "c"] and found[a]["favourite"] is True
    import shutil

    shutil.rmtree(a)
    assert a not in dict(cache.scan(str(tmp_path)))


def test_sorting_filters_tags_and_selection(gallery, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    page, out = gallery
    a = _job(out, "zebra", "2026-09-01 10:00:00", clip=80.0, seconds=30.0)
    b = _job(out, "apple", "2026-09-02 10:00:00", clip=60.0, seconds=90.0, method="clipasso")
    c = _job(out, "mango", "2026-09-03 10:00:00", clip=None, seconds=5.0)
    page.refresh()

    def shown():
        return [os.path.basename(it.job_dir) for it in page.items()]

    expected = {"newest": ["mango", "apple", "zebra"], "oldest": ["zebra", "apple", "mango"],
                "score": ["zebra", "apple", "mango"], "duration": ["apple", "zebra", "mango"],
                "name": ["apple", "mango", "zebra"]}
    for sort, order in expected.items():
        page.sort.setCurrentIndex(page.SORTS.index(sort))
        assert shown() == order, sort
    page.sort.setCurrentIndex(0)
    page.filter.set_current("clipasso")
    page._apply()
    assert shown() == ["apple"]
    page.filter.set_current("all")

    page.save_info(c, title="Ripe mango", tags=["fruit", "summer"], notes="for the kitchen")
    assert page.item(c).name == "Ripe mango"
    assert [page.tag_filter.itemData(i) for i in range(page.tag_filter.count())] == ["", "fruit", "summer"]
    page.tag_filter.setCurrentIndex(page.tag_filter.findData("fruit"))
    assert shown() == ["mango"]
    page.tag_filter.setCurrentIndex(0)
    page.search.setText("kitchen")  # notes are searched too
    page._apply()
    assert shown() == ["mango"]
    page.search.setText("")
    page._apply()

    page.select([a, b])
    assert {it.job_dir for it in page.selected_items()} == {a, b} and page.selection_bar.isVisibleTo(page)
    QTest.keyClick(page.view, Qt.Key_F)  # favourite for all selected
    assert page.item(a).favourite and page.item(b).favourite
    page.toggle_favourite_selected()
    assert not page.item(a).favourite
    exported = []
    monkeypatch.setattr("clipasso_studio.gui.dialogs.export_many", lambda parent, items: exported.append(items))
    page.sel_export_btn.click()
    assert sorted(d for d, _ in exported[0]) == sorted([a, b])
    opened = []
    page.open_job.connect(opened.append)
    page.view.setCurrentIndex(page.model.index(page.model.row_of(c)))
    QTest.keyClick(page.view, Qt.Key_Return)
    assert opened == [c]

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    page.select([a, b])
    QTest.keyClick(page.view, Qt.Key_Delete)
    assert not os.path.exists(a) and not os.path.exists(b) and os.path.exists(c)
    page.refresh()
    assert shown() == ["mango"]


def test_info_dialog_values(qapp):
    from clipasso_studio.gui.pages.gallery import GalleryItem, JobInfoDialog

    dlg = JobInfoDialog(GalleryItem("/x/job", {"target": "/x/camel.png", "tags": ["a"], "notes": "n"}))
    dlg.tags.setText("#animals, birthday; animals ")
    dlg.name.setText("  ")
    assert dlg.values() == {"title": None, "tags": ["animals", "birthday"], "notes": "n"}


def test_a_thousand_results(gallery):
    page, out = gallery
    for i in range(1000):
        _job(out, f"job{i:04d}", f"2026-09-{1 + i % 28:02d} {i % 24:02d}:00:00", clip=float(i % 100))
    start = time.perf_counter()
    page.refresh()
    first = time.perf_counter() - start
    page.view.viewport().repaint()  # only the visible tiles are drawn (their previews are rendered once)
    start = time.perf_counter()
    page.refresh()
    again = time.perf_counter() - start
    page.search.setText("job09")
    start = time.perf_counter()
    page._apply()
    search = time.perf_counter() - start
    assert len(page.items()) == 100
    assert first < 10 and again < 2 and search < 0.5, (first, again, search)
