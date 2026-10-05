"""Time budget: the settings that give the best expected sketch within a time on this computer."""

import pytest


@pytest.fixture
def cpu_only(user_data, monkeypatch):
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import methods_ui

    settings_module._instance = None
    monkeypatch.setattr(methods_ui, "_cuda", False)
    yield methods_ui
    settings_module._instance = None


def test_fits_the_budget_with_the_best_variant(cpu_only):
    from clipasso_studio import settings_schema as schema

    mu = cpu_only
    s = schema.default_settings("clipasso")
    assert mu.estimate_seconds(s, False) > 60 * 60
    for minutes in (5, 15, 60):
        changes, secs = mu.fit_to_budget(s, minutes * 60, False)
        assert secs <= minutes * 60 and set(changes) <= {"turbo", "num_sketches", "num_iter", "num_aug_clip"}
        assert mu.estimate_seconds({**s, **changes}, False) == pytest.approx(secs)
    # more time never means a worse choice
    q = [mu._budget_quality("clipasso", {**{k: s[k] for k in ("turbo", "num_sketches", "num_iter", "num_aug_clip")},
                                         **mu.fit_to_budget(s, m * 60, False)[0]}, s) for m in (5, 15, 60)]
    assert q == sorted(q)
    # it fits already: nothing to change
    quick = {**s, "num_iter": 150, "num_sketches": 1, "turbo": True, "num_aug_clip": 0}
    assert mu.fit_to_budget(quick, 24 * 3600, False)[0] == {"num_iter": 2001, "num_sketches": 3, "turbo": False,
                                                            "num_aug_clip": 4}


def test_nothing_fits_the_quickest_variant(cpu_only):
    from clipasso_studio import settings_schema as schema

    mu = cpu_only
    s = schema.default_settings("controlsketch")
    changes, secs = mu.fit_to_budget(s, 60, False)  # one minute on the processor: impossible
    assert secs > 60 and changes.get("turbo") and changes.get("num_iter") == 150
    sw = schema.default_settings("swiftsketch")
    changes, _ = mu.fit_to_budget(sw, 3600, False)
    assert changes["num_sketches"] == 8  # more to choose the best from, but not a wall of sketches
    scene = schema.default_settings("scenesketch")
    changes, _ = mu.fit_to_budget(scene, 10 ** 7, False)
    assert "simplicity_levels" not in changes  # time enough: the matrix the user chose stays
