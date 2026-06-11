import os
from pathlib import Path
from typing import Any

# import polars as pl
# from ngio import open_ome_zarr_container, open_ome_zarr_plate
from pydantic import BaseModel, Field, model_validator

_FIXED_COLS = {"zarr_url", "active"}
# CSV column prefix marking a ``types`` entry, so attributes and types round-trip
# as distinct columns (e.g. ``type:is_3D``).
_TYPE_PREFIX = "type:"


def _is_within_dir(url: str, zarr_dir: str) -> bool:
    """Whether ``url`` points inside ``zarr_dir`` (or is ``zarr_dir`` itself).

    Uses ``realpath`` so symlinked paths compare equal (on macOS the native
    folder picker resolves ``/tmp`` -> ``/private/tmp``, etc.) and compares on
    path boundaries so ``/data/zarr`` does not match a sibling ``/data/zarr2``.
    """
    root = os.path.realpath(zarr_dir)
    target = os.path.realpath(url)
    return target == root or target.startswith(root + os.sep)


class ZarrUrl(BaseModel):
    url: str
    attributes: dict[str, Any]
    types: dict[str, bool] = Field(default_factory=dict)
    active: bool = True

    def matches_input_types(self, input_types: dict[str, bool]) -> bool:
        """Whether this image satisfies a task's declared ``input_types``.

        A declared key only excludes the image when the image carries that key
        with a *differing* value. A missing key counts as a match, so the image
        is still run on (this is the opposite of ``TypeFilter``, which deactivates
        images missing the key). All declared keys must match (AND).
        """
        for key, value in input_types.items():
            if key in self.types and self.types[key] != value:
                return False
        return True


def _parse_ome_zarr_url(url: str) -> list["ZarrUrl"]:
    """Probe ``url`` as an OME-Zarr image, then a plate.

    Returns the parsed image(s) — a single image for a container, or one entry
    per well image for a plate (well-expanded). Returns an empty list if ``url``
    is neither.
    """
    try:
        raise NotImplementedError("_parse_ome_zarr_url not implemented")
        # ome_zarr = open_ome_zarr_container(url)
        # return [ZarrUrl(url=url, attributes={}, types={"is_3D": ome_zarr.is_3d})]
    except Exception:
        pass
    try:
        plate = open_ome_zarr_plate(url)
    except Exception:
        return []
    images: list[ZarrUrl] = []
    for path, image in plate.get_images().items():
        row, col, _ = path.split("/")
        images.append(
            ZarrUrl(
                url=f"{url}/{path}",
                attributes={"well": f"{row}{int(col):02d}"},
                types={"is_3D": image.is_3d},
            )
        )
    return images


class ImageListUpdate(BaseModel):
    zarr_url: str
    origin: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    types: dict[str, bool] = Field(default_factory=dict)


class Dataset(BaseModel):
    name: str
    zarr_dir: str
    zarr_urls: list[ZarrUrl] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_zarr_urls_in_dir(self) -> "Dataset":
        for zu in self.zarr_urls:
            if not _is_within_dir(zu.url, self.zarr_dir):
                raise ValueError(f"{zu.url!r} is not under zarr_dir {self.zarr_dir!r}")
        return self

    def from_imagelist_update(
        self, imagelist_update: list[dict[str, Any]]
    ) -> "Dataset":
        source_attrs: dict[str, dict[str, Any]] = {
            zu.url: zu.attributes for zu in self.zarr_urls
        }
        source_types: dict[str, dict[str, bool]] = {
            zu.url: zu.types for zu in self.zarr_urls
        }
        zarr_urls = []
        for row in imagelist_update:
            update = ImageListUpdate.model_validate(row)
            # Inherit attributes/types from the origin image (if any), then overlay
            # the task's own attributes and types (right-hand side has priority).
            base_attrs = source_attrs.get(update.origin, {}) if update.origin else {}
            base_types = source_types.get(update.origin, {}) if update.origin else {}
            attributes = {**base_attrs, **update.attributes}
            types = {**base_types, **update.types}
            zarr_url = ZarrUrl(
                url=update.zarr_url,
                attributes=attributes,
                types=types,
                active=True,
            )
            zarr_urls.append(zarr_url)
        return self.from_zarr_urls(zarr_urls)

    def from_zarr_urls(self, zarr_urls: list[ZarrUrl]) -> "Dataset":
        # Merge new URLs with existing ones, unioning attributes and types
        # (new values win).
        existing_by_url = {zu.url: zu for zu in self.zarr_urls}
        for zu in zarr_urls:
            if zu.url in existing_by_url:
                old = existing_by_url[zu.url]
                existing_by_url[zu.url] = old.model_copy(
                    update={
                        "attributes": {**old.attributes, **zu.attributes},
                        "types": {**old.types, **zu.types},
                    }
                )
            else:
                existing_by_url[zu.url] = zu
        return Dataset(
            name=self.name,
            zarr_dir=self.zarr_dir,
            zarr_urls=list(existing_by_url.values()),
        )

    def with_output_types(
        self,
        run_urls: list[str],
        produced_urls: list[str],
        output_types: dict[str, bool],
    ) -> "Dataset":
        """Apply a task's ``output_types`` after a run.

        ``run_urls`` are the images the task ran on; ``produced_urls`` are the
        images it reported in ``image_list_updates`` (new or in-place). When the
        task produced nothing, its inputs count as produced.

        For every image the task touched (run urls and produced), each declared
        output key is set to its value on produced images and to the opposite
        value on the others; an image carrying the opposite value is deactivated.
        Only the declared keys are touched, only ``active=False`` is ever set
        (never re-activated), and images outside the touched set are left untouched.
        """
        if not output_types:
            return self
        produced = set(produced_urls) if produced_urls else set(run_urls)
        touched = set(run_urls) | produced
        new_urls: list[ZarrUrl] = []
        for zu in self.zarr_urls:
            if zu.url not in touched:
                new_urls.append(zu)
                continue
            is_produced = zu.url in produced
            types = dict(zu.types)
            active = zu.active
            for key, value in output_types.items():
                assigned = value if is_produced else (not value)
                types[key] = assigned
                if assigned != value:
                    active = False
            new_urls.append(zu.model_copy(update={"types": types, "active": active}))
        return self.model_copy(update={"zarr_urls": new_urls})

    def clear_images(self) -> "Dataset":
        """Return a copy with all images removed (but the same zarr_dir)."""
        return self.model_copy(update={"zarr_urls": []})

    def remove_zarr_url(self, url: str) -> "Dataset":
        """Return a copy with the image at ``url`` removed (no-op if absent)."""
        return self.model_copy(
            update={"zarr_urls": [zu for zu in self.zarr_urls if zu.url != url]}
        )

    def from_raw_urls(self, urls: list[str]) -> "Dataset":
        new_urls: list[ZarrUrl] = []
        failed: list[str] = []
        for url in urls:
            parsed = _parse_ome_zarr_url(url)
            if parsed:
                new_urls.extend(parsed)
            else:
                failed.append(url)

        if failed:
            # TODO log failures somewhere instead of just printing
            pass
        return self.from_zarr_urls(new_urls)

    def to_csv(self, path: str | Path) -> None:
        rows = []
        for zu in self.zarr_urls:
            row: dict[str, Any] = {"zarr_url": zu.url, "active": zu.active}
            row.update(zu.attributes)
            # Types are written as prefixed columns so they reload into ``types``.
            row.update({f"{_TYPE_PREFIX}{k}": v for k, v in zu.types.items()})
            rows.append(row)
        raise NotImplementedError("This is a slim version, with no polars.")
        pl.DataFrame(rows).write_csv(path)

    @classmethod
    def from_csv(cls, path: str | Path) -> "Dataset":
        path = Path(path)
        raise NotImplementedError("This is a slim version, with no polars.")
        df = pl.read_csv(path)
        if df.is_empty():
            raise ValueError(
                "Cannot load Dataset from an empty CSV (zarr_dir cannot be inferred)."
            )
        name = path.stem
        urls = df["zarr_url"].to_list()
        zarr_dir = os.path.commonpath([str(Path(u).parent) for u in urls])
        type_cols = [c for c in df.columns if c.startswith(_TYPE_PREFIX)]
        attr_cols = [
            c for c in df.columns if c not in _FIXED_COLS and c not in type_cols
        ]
        zarr_urls = []
        for row in df.iter_rows(named=True):
            attributes = {k: row[k] for k in attr_cols if row[k] is not None}
            types = {
                k[len(_TYPE_PREFIX) :]: bool(row[k])
                for k in type_cols
                if row[k] is not None
            }
            zarr_urls.append(
                ZarrUrl(
                    url=row["zarr_url"],
                    active=row["active"],
                    attributes=attributes,
                    types=types,
                )
            )
        return cls(name=name, zarr_dir=zarr_dir, zarr_urls=zarr_urls)
