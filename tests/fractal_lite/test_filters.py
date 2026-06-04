"""Tests for the filters: AttributeFilter (string attrs) and TypeFilter (booleans).

Covers hiding semantics, AttributeFilter's string coercion, TypeFilter's direct
boolean comparison, and immutability.
"""

from fractal_lite import Dataset
from fractal_lite._dataset import ZarrUrl
from fractal_lite._filters import AttributeFilter, TypeFilter


def _dataset() -> Dataset:
    return Dataset(
        name="ds",
        zarr_dir="/z",
        zarr_urls=[
            ZarrUrl(url="/z/a", attributes={"well": "A"}, types={"is_3D": True}),
            ZarrUrl(url="/z/b", attributes={"well": "B"}, types={"is_3D": False}),
            ZarrUrl(
                url="/z/c", attributes={"well": "A"}, types={"is_3D": True}, hidden=True
            ),
        ],
    )


def test_type_filter_hides_non_matching():
    ds = _dataset()
    result = TypeFilter(key="is_3D", value=False).run(ds)
    hidden = {zu.url: zu.hidden for zu in result.zarr_urls}
    # is_3D True -> hidden; is_3D False -> visible.
    assert hidden == {"/z/a": True, "/z/b": False, "/z/c": True}


def test_type_filter_already_hidden_stays_hidden_even_when_matching():
    ds = _dataset()
    # "/z/c" matches value True but was already hidden; a filter never un-hides.
    result = TypeFilter(key="is_3D", value=True).run(ds)
    by_url = {zu.url: zu.hidden for zu in result.zarr_urls}
    assert by_url["/z/c"] is True
    assert by_url["/z/b"] is True  # is_3D False -> hidden


def test_type_filter_does_not_mutate_input():
    ds = _dataset()
    TypeFilter(key="is_3D", value=False).run(ds)
    # The original dataset's hidden flags are untouched.
    assert [zu.hidden for zu in ds.zarr_urls] == [False, False, True]


def test_attribute_filter_hides_non_matching_and_coerces_value_to_string():
    ds = _dataset()
    result = AttributeFilter(attribute="well", value="A").run(ds)
    hidden = {zu.url: zu.hidden for zu in result.zarr_urls}
    # well == "A" stays visible; well == "B" is hidden.
    assert hidden == {"/z/a": False, "/z/b": True, "/z/c": True}
