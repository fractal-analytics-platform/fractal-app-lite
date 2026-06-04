"""End-to-end test: actually run a converter task in its own pixi environment.

This is slow — collecting builds the converter package's pixi env on first use — so
it is marked ``e2e`` and excluded by ``pytest -m 'not e2e'`` / ``pixi run -e dev
test-fast``. It exercises the full path: collect -> resolve -> run -> dataset fold.
"""

from pathlib import Path

import pytest

from fractal_lite import Dataset

DATA = Path(__file__).resolve().parent.parent / "data" / "hcs_1w1p1c1z1t"
TASK_NAME = "Convert Evident ScanR Plate to OME-Zarr"


@pytest.mark.e2e
def test_scanr_converter_end_to_end(registry, converters_targz, tmp_path):
    registry.collect_from_targz(converters_targz, overwrite=True)

    zarr_dir = tmp_path / "output_zarr"
    zarr_dir.mkdir()
    dataset = Dataset(name="e2e", zarr_dir=str(zarr_dir))

    task = registry.get_task(f"{TASK_NAME} [{converters_targz.name}]").model_copy(
        update={
            "kwargs_non_parallel": {
                "acquisitions": [{"path": str(DATA)}],
                "overwrite": "Overwrite",
            }
        }
    )

    result = task.run(dataset)

    assert len(result.zarr_urls) >= 1
    first = result.zarr_urls[0]
    assert first.url.startswith(str(zarr_dir))
    # The converter actually wrote an OME-Zarr group to disk.
    assert list(zarr_dir.glob("*.zarr"))
