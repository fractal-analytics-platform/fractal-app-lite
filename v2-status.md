# Fractal Lite v2 — Status Report

> Branch: `v2` · Latest release: [`v2.0.4`](https://github.com/fractal-analytics-platform/fractal-app-lite/releases/tag/v2.0.4)

## macOS 26 — Intel (`macos-26-intel`)

TODO

---

## macOS 26 — Apple Silicon (`macos-26`)

TODO

---

## macOS 15 — Intel (`macos-15-intel`)

TODO

---

## Linux (`ubuntu-22.04`)

**Test machine:** Lenovo 83JK, Intel Core Ultra 5 225H (14 cores / 14 threads), 32 GB RAM, Ubuntu 24.04.5 LTS.

**Version tested:** `v2.0.4`

### Download

1. Open the [Releases page](https://github.com/fractal-analytics-platform/fractal-app-lite/releases?q=v2&expanded=true).
2. In the latest `v2.x.y` release, download `v2.x.y-fractal-ubuntu-22.04` (~410 MB).

### Install and launch

There is nothing to install: the file is a self-contained executable.

1. **Make it executable.** From the folder where you downloaded the file:

   ```bash
   chmod +x v2.x.y-fractal-ubuntu-22.04
   ```

2. **Launch.** Run it from the same folder:

   ```bash
   ./v2.x.y-fractal-ubuntu-22.04
   ```

   The terminal shows the backend logs.

---

## Windows (`windows-2025`)

TODO

---

## End-to-end test

The same test applies to every platform; platform-specific differences are noted inline.

1. **Create a project.** Click **New project** and fill in the modal.
2. **Register the task packages.** Go to **Task Management** and register these two packages with
   **Register git release**:

   - `fractal-tasks-core`: use the latest version.
   - `fractal-uzh-converters`: use the latest version.
3. **Build the workflow.** Go to **Workflow** and add these three tasks, in this order:

   | Order | Task                                    | Arguments                                                                                                                                                        |
   | :---: | --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
   |   1   | Convert Evident ScanR Plate to OME-Zarr | `Acquisitions.ScanRAcquisitionModel.Path`: a folder with valid ScanR images, e.g. `fractal-app-lite/tests/data/hcs_1w1p1c1z1t/data`<br>`Overwrite`: `Overwrite` |
   |   2   | Project Image (HCS Plate)               | `Overwrite`: `true`                                                                                                                                              |
   |   3   | Threshold Segmentation                  | `Mode`: `Index`<br>`Identifier`: `0`<br>`Overwrite`: `true`                                                                                                      |
4. **Run.** Click **Run** and wait for the workflow to finish.
