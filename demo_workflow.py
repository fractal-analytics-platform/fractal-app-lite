"""Manual check: a real, end-to-end ``Workflow`` on actual ScanR data.

Run with:  pixi run python try_real_workflow.py

Unlike try_output_types.py (which stubs the subprocess layer), this collects two
real task packages from the curated package index and runs three real tasks in
their own pixi environments:

  ScanR converter  ->  HCS projection  ->  Thresholding

The dataset starts empty: the converter reads the raw acquisition directory and
writes a fresh OME-Zarr plate (3D images). The HCS projection then declares
``input_types={is_3D: True}`` / ``output_types={is_3D: False}``, so it runs on
those 3D images and produces visible 2D projections (hiding the 3D originals).
Thresholding has no type constraints, so it runs on whatever is still visible --
the 2D projections. Every task is configured to overwrite so the workflow can be
re-run in place against the same ``zarr_dir``.
"""

from pathlib import Path

from fractal_lite import Dataset, Workflow, tasks_registry
from fractal_lite._package_index import find_package

# Raw Evident ScanR acquisition to convert (2 wells, 4 positions, 4 channels,
# 5 z-planes, 1 timepoint).
RAW_ACQUISITION = (
    "/Users/locerr/data/Converters_Test_Data_Clean/Evident-scanR/raw/hcs_2w4p4c5z1t_seq"
)

CONVERTER_TASK = "Convert Evident ScanR Plate to OME-Zarr"
PROJECTION_TASK = "Project Image (HCS Plate)"
THRESHOLD_TASK = "Threshold Segmentation"


def show(title: str, ds: Dataset) -> None:
    print(title)
    if not ds.zarr_urls:
        print("  (no images)")
    for zu in ds.zarr_urls:
        state = "active  " if zu.active else "INACTIVE"
        print(f"  [{state}] {zu.url}  attrs={zu.attributes} types={zu.types}")
    print()


def collect_from_index(pkg_name: str) -> None:
    """Collect a package's GitHub release using the curated package index."""
    entry = find_package(pkg_name)
    if entry is None:
        raise ValueError(f"{pkg_name!r} is not in the package index.")
    tasks_registry.collect_from_gitrelease(
        entry.repo_url, tag=entry.tag or None, overwrite=True
    )


def task_named(name: str):
    """Return the (first) collected task with the given manifest name."""
    for task in tasks_registry.tasks:
        if task.name == name:
            return task
    raise KeyError(
        f"Task {name!r} not collected. "
        f"Available: {sorted(t.name for t in tasks_registry.tasks)}"
    )


def main() -> None:
    # Collect fractal-uzh-converters and fractal-tasks-core from the package index.
    collect_from_index("fractal-uzh-converters")
    collect_from_index("fractal-tasks-core")

    # The converter builds the dataset from the raw data, so we start empty --
    # only the (existing) zarr_dir into which the OME-Zarr plate is written.
    zarr_dir = Path("./scanr_zarr_").absolute()
    dataset = Dataset(name="scanr_demo", zarr_dir=str(zarr_dir))
    show(f"initial (empty) dataset, zarr_dir={zarr_dir}", dataset)

    # Build the three workflow steps, all set to overwrite so the workflow can
    # be re-run in place on the same zarr_dir.
    converter = task_named(CONVERTER_TASK).model_copy(
        update={
            "kwargs_non_parallel": {
                "acquisitions": [{"path": RAW_ACQUISITION}],
                "overwrite": "Overwrite",
            }
        }
    )
    projection = task_named(PROJECTION_TASK).model_copy(
        update={"kwargs_non_parallel": {"overwrite": True}}
    )
    threshold = task_named(THRESHOLD_TASK).model_copy(
        update={
            "kwargs_parallel": {
                # Segment on the first channel; overwrite an existing label.
                "channel": {"mode": "index", "identifier": "0"},
                "overwrite": True,
            }
        }
    )

    workflow = Workflow(
        name="ScanR -> Projection -> Threshold",
        task_list=[converter, projection, threshold],
    )

    result = workflow.run(dataset)
    show("final dataset", result)


if __name__ == "__main__":
    main()
