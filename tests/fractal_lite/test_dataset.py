"""Tests for the Dataset model: validation, CSV round-trip, imagelist folding."""

import pytest

from fractal_lite import Dataset
from fractal_lite import _dataset as ds_mod
from fractal_lite._dataset import ZarrUrl


def _dataset() -> Dataset:
    return Dataset(
        name="ds",
        zarr_dir="/data/z",
        zarr_urls=[
            ZarrUrl(
                url="/data/z/A/0",
                attributes={"plate": "p1", "well": "A"},
                types={"is_3D": True},
                active=True,
            ),
            ZarrUrl(
                url="/data/z/B/0",
                attributes={"plate": "p1", "well": "B"},
                types={"is_3D": False},
                active=False,
            ),
        ],
    )


def test_validator_rejects_url_outside_zarr_dir():
    with pytest.raises(ValueError, match="not under zarr_dir"):
        Dataset(
            name="ds",
            zarr_dir="/data/z",
            zarr_urls=[ZarrUrl(url="/elsewhere/x", attributes={})],
        )


def test_validator_rejects_sibling_prefix_dir():
    # /data/zarr must not accept a sibling /data/zarr2 (path-boundary check).
    with pytest.raises(ValueError, match="not under zarr_dir"):
        Dataset(
            name="ds",
            zarr_dir="/data/zarr",
            zarr_urls=[ZarrUrl(url="/data/zarr2/x", attributes={})],
        )


def test_validator_accepts_symlinked_zarr_dir(tmp_path):
    # A symlink to the real zarr_dir must compare equal (realpath), so a url
    # under the symlinked path is accepted. Mirrors the macOS picker resolving
    # /tmp -> /private/tmp.
    real = tmp_path / "real_zarr"
    real.mkdir()
    link = tmp_path / "link_zarr"
    link.symlink_to(real)
    ds = Dataset(
        name="ds",
        zarr_dir=str(link),
        zarr_urls=[ZarrUrl(url=str(real / "img.zarr"), attributes={})],
    )
    assert ds.zarr_urls[0].url == str(real / "img.zarr")


def test_csv_round_trip(tmp_path):
    zarr_dir = tmp_path / "z"
    zarr_url_A0 = zarr_dir / "A" / "0"
    zarr_url_B0 = zarr_dir / "B" / "0"
    ds = Dataset(
        name="ds",
        zarr_dir=str(zarr_dir),
        zarr_urls=[
            ZarrUrl(
                url=str(zarr_url_A0),
                attributes={"plate": "p1", "well": "A"},
                types={"is_3D": True},
                active=True,
            ),
            ZarrUrl(
                url=str(zarr_url_B0),
                attributes={"plate": "p1", "well": "B"},
                types={"is_3D": False},
                active=False,
            ),
        ],
    )
    csv = tmp_path / "ds.csv"
    ds.to_csv(csv)
    loaded = Dataset.from_csv(csv)

    # zarr_dir is re-inferred from the common parent of all urls.
    assert loaded.zarr_dir == str(zarr_dir)

    def key(d: Dataset):
        return sorted(
            (
                zu.url,
                zu.active,
                tuple(sorted(zu.attributes.items())),
                tuple(sorted(zu.types.items())),
            )
            for zu in d.zarr_urls
        )

    assert key(loaded) == key(ds)


def test_from_imagelist_update_new_image_inherits_from_origin():
    ds = _dataset()
    updated = ds.from_imagelist_update(
        [
            {
                "zarr_url": "/data/z/A/0_corr",
                "origin": "/data/z/A/0",
                "attributes": {"well": "A2"},
                "types": {"is_3D": False},
            }
        ]
    )
    new = next(zu for zu in updated.zarr_urls if zu.url == "/data/z/A/0_corr")
    # origin attributes inherited (plate), overlaid by update attributes (well);
    # types are kept separate from attributes.
    assert new.attributes == {"plate": "p1", "well": "A2"}
    # origin types inherited (is_3D True), overlaid by update types (is_3D False).
    assert new.types == {"is_3D": False}


def test_from_zarr_urls_merges_new_and_existing():
    ds = _dataset()
    merged = ds.from_zarr_urls(
        [
            # new url
            ZarrUrl(url="/data/z/C/0", attributes={"plate": "p1", "well": "C"}),
            # existing url: attributes union, new values win
            ZarrUrl(url="/data/z/A/0", attributes={"well": "A2", "channel": "405"}),
        ]
    )
    by_url = {zu.url: zu for zu in merged.zarr_urls}
    assert by_url["/data/z/C/0"].attributes == {"plate": "p1", "well": "C"}
    assert by_url["/data/z/A/0"].attributes == {
        "plate": "p1",
        "well": "A2",
        "channel": "405",
    }
    # No urls dropped; one added.
    assert len(merged.zarr_urls) == len(ds.zarr_urls) + 1


def test_remove_zarr_url():
    ds = _dataset()
    removed = ds.remove_zarr_url("/data/z/A/0")
    urls = [zu.url for zu in removed.zarr_urls]
    assert urls == ["/data/z/B/0"]
    # Original is untouched (immutable copy).
    assert len(ds.zarr_urls) == 2


def test_remove_zarr_url_absent_is_no_op():
    ds = _dataset()
    removed = ds.remove_zarr_url("/data/z/does/not/exist")
    assert [zu.url for zu in removed.zarr_urls] == [zu.url for zu in ds.zarr_urls]


class _FakeImage:
    def __init__(self, is_3d):
        self.is_3d = is_3d


class _FakePlate:
    def __init__(self, images):
        self._images = images

    def get_images(self):
        return self._images


def test_from_raw_urls_image_keeps_attributes(monkeypatch):
    # Regression: the parsed is_3D flag must survive into the dataset as a type.
    monkeypatch.setattr(
        ds_mod, "open_ome_zarr_container", lambda url: _FakeImage(is_3d=True)
    )
    ds = Dataset(name="ds", zarr_dir="/data/z")
    updated = ds.from_raw_urls(["/data/z/img.zarr"])
    [zu] = updated.zarr_urls
    assert zu.url == "/data/z/img.zarr"
    assert zu.attributes == {}
    assert zu.types == {"is_3D": True}


def test_from_raw_urls_plate_expands_wells(monkeypatch):
    def _not_a_container(url):
        raise ValueError("not a container")

    monkeypatch.setattr(ds_mod, "open_ome_zarr_container", _not_a_container)
    monkeypatch.setattr(
        ds_mod,
        "open_ome_zarr_plate",
        lambda url: _FakePlate({"B/3/0": _FakeImage(is_3d=False)}),
    )
    ds = Dataset(name="ds", zarr_dir="/data/z")
    updated = ds.from_raw_urls(["/data/z/plate.zarr"])
    [zu] = updated.zarr_urls
    assert zu.url == "/data/z/plate.zarr/B/3/0"
    # well name is zero-padded from the (string) column index; is_3D is a type.
    assert zu.attributes == {"well": "B03"}
    assert zu.types == {"is_3D": False}


def test_from_imagelist_update_existing_url_merges_attributes():
    ds = _dataset()
    updated = ds.from_imagelist_update(
        [{"zarr_url": "/data/z/A/0", "attributes": {"channel": "405"}}]
    )
    existing = next(zu for zu in updated.zarr_urls if zu.url == "/data/z/A/0")
    assert existing.attributes == {"plate": "p1", "well": "A", "channel": "405"}
    # No new rows were added for an update that targets an existing url.
    assert len(updated.zarr_urls) == len(ds.zarr_urls)
