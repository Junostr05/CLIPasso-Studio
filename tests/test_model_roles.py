"""3.7: the models the studio's settings choose, by category (gui/model_roles.py – shown and changed on the models
page)."""

from clipasso_studio import settings_schema as schema
from clipasso_studio.engine import model_store
from clipasso_studio.gui import model_roles


def test_every_role_is_a_setting_of_its_method():
    for method, roles in model_roles.ROLES.items():
        keys = {p.key for p in schema.params_for(method)}
        for role in roles:
            assert role.key in keys and role.category in model_roles.CATEGORIES, (method, role.key)


def test_rows_by_category_with_their_models():
    for method in schema.METHODS:
        rows = model_roles.rows(method, schema.default_settings(method))
        order = [model_roles.CATEGORIES.index(r["category"]) for r in rows]
        assert order == sorted(order) and rows[0]["category"] == "mask", method
        for r in rows:
            assert all(k in model_store.SPECS for k in r["models"])
            assert set(r["missing"]) <= set(r["models"]) and r["experimental"] is False


def test_the_chosen_value_decides_the_model():
    s = schema.default_settings("clipasso")
    by_key = {r["key"]: r for r in model_roles.rows("clipasso", {**s, "clip_model_name": "ViT-B/16"})}
    assert by_key["clip_model_name"]["models"] == ["clip:ViT-B/16"]
    assert by_key["semantic_model"]["models"] == ["clip:ViT-B/16"]  # (the default: the conv model's own)
    sem = {r["key"]: r for r in model_roles.rows("clipasso", {**s, "semantic_model": "siglip_b16"})}["semantic_model"]
    assert sem["models"] == ["semantic:siglip-b16"] and sem["experimental"]
    dino = {r["key"]: r for r in model_roles.rows("clipasso", {**s, "saliency_model": "dino"})}["saliency_model"]
    assert dino["models"] == ["dino"]
    cond = {r["key"]: r for r in model_roles.rows("controlsketch", {**schema.default_settings("controlsketch"),
                                                                    "condition": "hed"})}["condition"]
    assert cond["models"] == ["controlnet:hed", "hed"]
    assert model_roles.choice_models("clipasso", "semantic_model", "openclip_b16", s) == ["semantic:openclip-b16"]
    assert model_roles.experimental("semantic:openclip-b16") and not model_roles.experimental("clip:RN101")


def test_unused_roles_are_marked():
    s = {**schema.default_settings("clipasso"), "mask_object": False}
    mask = {r["key"]: r for r in model_roles.rows("clipasso", s)}["mask_model"]
    assert mask["enabled"] is False
    assert "semantic:siglip-b16" in model_roles.in_use("clipasso", {**s, "semantic_model": "siglip_b16"})
