"""Job folders: the input image is kept with the job so it can be reopened and continued."""

import os

from PIL import Image

from clipasso_studio.engine import jobs


def _image(path, size=(40, 30)):
    Image.new("RGB", size, "white").save(path)
    return str(path)


def test_the_input_is_copied_when_the_job_folder_is_created(tmp_path):
    target = _image(tmp_path / "horse.png")
    job_dir = jobs.make_job_dir(str(tmp_path / "out"), target, "swiftsketch")
    copy = os.path.join(job_dir, "input", "horse.png")
    assert os.path.isfile(copy)  # already before any sketch exists (cancelled / failed runs keep it)
    assert jobs.saved_input(job_dir, target) == copy
    os.remove(target)
    assert jobs.reopen_input(job_dir, target) == copy  # the original is gone: continue with the copy
    # a new run from the copy is named after the image, not after the copy's folder
    assert os.path.basename(jobs.make_job_dir(str(tmp_path / "out"), copy)).startswith("horse_")


def test_the_original_is_used_while_it_exists(tmp_path):
    target = _image(tmp_path / "horse.png")
    job_dir = jobs.make_job_dir(str(tmp_path / "out"), target)
    assert jobs.reopen_input(job_dir, target) == target


def test_old_source_copies_are_renamed_after_the_image(tmp_path):
    job_dir = tmp_path / "camel_20260101-120000"
    job_dir.mkdir()
    _image(job_dir / "source.png")  # CLIPasso Studio 2.1 and older
    target = str(tmp_path / "gone" / "camel.png")
    copy = jobs.reopen_input(str(job_dir), target)
    assert copy == os.path.join(str(job_dir), "input", "camel.png") and os.path.isfile(copy)


def test_no_copy_when_the_input_cannot_be_read(tmp_path):
    job_dir = jobs.make_job_dir(str(tmp_path / "out"), str(tmp_path / "missing.png"))
    assert jobs.saved_input(job_dir) is None
