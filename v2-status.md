# Fractal Lite v2 — Status Report

> Branch: `v2` · Latest release: [`v2.0.4`](https://github.com/fractal-analytics-platform/fractal-app-lite/releases/tag/v2.0.4)

## macOS 26 — Intel (`macos-26-intel`)

**Test machine:** MacBook Pro 16" 2019 (MacBookPro16,1), Intel Core i9-9980HK (8 cores / 16 threads), 64 GB RAM,
macOS 26.6.2 (build 25G83).

**Version tested:** `v2.0.5`

> [!NOTE]
> `v2.0.4` crashed at startup with `AttributeError: module 'icu' has no attribute 'Locale'` (raised by `natsort`).
> On Intel macOS the conda `icu` package creates `.pixi/envs/default/lib/icu/`, which PyInstaller bundled as an
> empty `icu` namespace package because `lib` is in `pathex`. `v2.0.5` excludes `icu` in `fractal.spec`. The
> same crash affected `v2.0.4` on `macos-15-intel`; the CI "Test artifact" step did not catch it because it has
> `continue-on-error: true`.

### Download

1. Open the [Releases page](https://github.com/fractal-analytics-platform/fractal-app-lite/releases?q=v2&expanded=true).
2. In the latest `v2.x.y` release, download `v2.x.y-fractal-macos-26-intel` (~200 MB).

### Install and launch

There is nothing to install: the file is a self-contained executable.

1. **Make it executable.** From the folder where you downloaded the file:

   ```bash
   chmod +x v2.x.y-fractal-macos-26-intel
   ```

2. **Launch.** Run it from the same folder:

   ```bash
   ./v2.x.y-fractal-macos-26-intel
   ```

   The first time, Gatekeeper blocks it because the executable is not signed or notarized.

3. **Allow it.** Open **System Settings → Privacy & Security**, scroll down to the message about the blocked
   executable, and click **Open Anyway**. Then run the command from step 2 again and confirm. The terminal
   shows the backend logs, and the **Fractal Lite** window opens.

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

**Test machine:** Lenovo 83JK, Intel Core Ultra 5 225H (14 cores / 14 threads), 32 GB RAM, Windows 11 Home 25H2 (build 26200).

**Version tested:** `v2.0.4`

### Download

1. Open the [Releases page](https://github.com/fractal-analytics-platform/fractal-app-lite/releases?q=v2&expanded=true).
2. In the latest `v2.x.y` release, download `v2.x.y-fractal-windows-2025.exe` (~175 MB).

If Microsoft Edge (SmartScreen) blocks the download with *"v2.x.y-fractal-windows-2025.exe isn't commonly
downloaded. Make sure you trust v2.x.y-fractal-windows-2025.exe before you open it."*, open the downloads
panel (`Ctrl+J`), click **…** next to the file, then **Keep**. In the dialog that opens, click
**Show more** → **Keep anyway**.

### Install and launch

> [!WARNING]
> **Blocked by Smart App Control.** On the test machine Smart App Control is **On**. Double-clicking the `.exe`
> shows *"Smart App Control blocked an app that may be unsafe"*, and there is no option to run it anyway. The
> executable is not code-signed, and Smart App Control blocks unsigned apps with no reputation.
>
> The workaround is to turn Smart App Control off (**Windows Security → App & browser control →
> Smart App Control settings → Off**). This is system-wide and, depending on the Windows version, may not be
> reversible without reinstalling Windows. The real fix is to sign the executable.

There is nothing to install: the file is a self-contained executable.

1. **Turn off Smart App Control** (see the warning above).
2. **Launch.** Double-click `v2.x.y-fractal-windows-2025.exe`. A terminal window opens and shows the backend
   logs; after a few seconds the **Fractal Lite** window opens.

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
   - **Windows:** the run fails at the first task (`Convert Evident ScanR Plate to OME-Zarr`,
     `fractal-uzh-converters@v0.8.0b1`). The task's Python environment cannot load the compiled `lz4`
     extension of `numcodecs`: Windows blocks the DLL with *"An Application Control policy has blocked this
     file"* (on the Italian test machine: *"Un criterio di controllo dell'applicazione ha bloccato il file"*).
     The run page shows this error (repeated `site-packages` frames shortened):

     ```text
     [step 0] Running task 'Convert Evident ScanR Plate to OME-Zarr [fractal-uzh-converters@v0.8.0b1]'
     Traceback (most recent call last):
       File "C:\Users\yuric\fractal_lite\collected_tasks\fractal_uzh_converters-0.8.0b1\src\fractal_uzh_converters\scanr\convert_scanr_init_task.py", line 5, in <module>
         from ome_zarr_converters_tools import (
         ...<3 lines>...
         )
       File "...\site-packages\ome_zarr_converters_tools\__init__.py", line 5, in <module>
         from ome_zarr_converters_tools.core import (
       File "...\site-packages\ome_zarr_converters_tools\core\__init__.py", line 3, in <module>
         from ome_zarr_converters_tools.core._dummy_tiles import build_dummy_tile
       File "...\site-packages\ome_zarr_converters_tools\core\_dummy_tiles.py", line 8, in <module>
         from ome_zarr_converters_tools.core._tile import Tile
       File "...\site-packages\ome_zarr_converters_tools\core\_tile.py", line 5, in <module>
         from ngio import Roi, RoiSlice
       ...  (ngio -> ngio.utils._store)
       File "...\site-packages\ngio\utils\_store.py", line 21, in <module>
         from zarr.abc.store import ByteRequest, Store
       ...  (zarr -> zarr.codecs.blosc)
       File "...\site-packages\zarr\codecs\blosc.py", line 8, in <module>
         import numcodecs
       File "...\site-packages\numcodecs\__init__.py", line 63, in <module>
         from numcodecs import lz4 as lz4
     ImportError: DLL load failed while importing lz4: Un criterio di controllo dell'applicazione ha bloccato il file.
     ```

     `...\site-packages` is
     `C:\Users\yuric\fractal_lite\collected_tasks\fractal_uzh_converters-0.8.0b1\.pixi\envs\default\Lib\site-packages`.
     This happens with Smart App Control turned off.
