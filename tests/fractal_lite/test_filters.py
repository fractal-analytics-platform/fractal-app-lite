"""Tests for the filters: AttributeFilter (string attrs) and TypeFilter (booleans).

Covers deactivation semantics, AttributeFilter's string coercion, TypeFilter's
direct boolean comparison, and immutability.
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
                url="/z/c",
                attributes={"well": "A"},
                types={"is_3D": True},
                active=False,
            ),
        ],
    )


def test_type_filter_deactivates_non_matching():
    ds = _dataset()
    result = TypeFilter(key="is_3D", value=False).run(ds)
    active = {zu.url: zu.active for zu in result.zarr_urls}
    # is_3D True -> deactivated; is_3D False -> active.
    assert active == {"/z/a": False, "/z/b": True, "/z/c": False}


def test_type_filter_already_inactive_stays_inactive_even_when_matching():
    ds = _dataset()
    # "/z/c" matches value True but was already inactive; a filter never re-activates.
    result = TypeFilter(key="is_3D", value=True).run(ds)
    by_url = {zu.url: zu.active for zu in result.zarr_urls}
    assert by_url["/z/c"] is False
    assert by_url["/z/b"] is False  # is_3D False -> deactivated


def test_type_filter_does_not_mutate_input():
    ds = _dataset()
    TypeFilter(key="is_3D", value=False).run(ds)
    # The original dataset's active flags are untouched.
    assert [zu.active for zu in ds.zarr_urls] == [True, True, False]


def test_attribute_filter_deactivates_non_matching_and_coerces_value_to_string():
    ds = _dataset()
    result = AttributeFilter(attribute="well", value="A").run(ds)
    active = {zu.url: zu.active for zu in result.zarr_urls}
    # well == "A" stays active; well == "B" is deactivated.
    assert active == {"/z/a": True, "/z/b": False, "/z/c": False}
