# Fractal Lite v3 — Status Report

> Branch: `v3` · Latest release: [`v3.0.8`](https://github.com/fractal-analytics-platform/fractal-app-lite/releases/tag/v3.0.8)

## macOS 26 — Intel (`macos-26-intel`)

**Test machine:** MacBook Pro, Intel Core i9-9980HK @ 2.40 GHz (8 cores / 16 threads), 64 GB RAM, macOS 26.6.2 (build 25G83).

**Version tested:** `v3.0.7`

### Download

1. Open the [Releases page](https://github.com/fractal-analytics-platform/fractal-app-lite/releases?q=v3&expanded=true).
2. In the latest `v3.x.y` release, download `v3.x.y-FractalLite-macos-26-intel.dmg` (~290 MB).

### Install and launch

1. **Install.** Double-click the `.dmg`. In the window that opens, drag **Fractal Lite** onto the
   **Applications** folder.
2. **First launch.** Open **Fractal Lite** from Applications. Gatekeeper blocks it with a
   *"Fractal Lite" Not Opened* dialog. Click **Done**. Do **not** click **Move to Trash**.
3. **Allow the app.** Open **System Settings → Privacy & Security**. In the **Security** section, next to
   *"Fractal Lite" was blocked to protect your Mac*, click **Open Anyway**. Then authenticate with your
   password or Touch ID.
4. **Confirm.** In the *Open "Fractal Lite"?* dialog, click **Open Anyway**. From now on the app opens
   normally.

If macOS says the app "is damaged and can't be opened", remove the quarantine attribute:

```bash
xattr -cr "/Applications/Fractal Lite.app"
```

To see the backend logs while debugging, start the app from a terminal:

```bash
"/Applications/Fractal Lite.app/Contents/MacOS/Fractal Lite"

[TIMING] loading screen shown: 409ms
[TIMING] port found: 420ms
[TIMING] python spawned: 423ms
[fractal-app-lite] INFO:     Started server process [22989]
INFO:     Waiting for application startup.
[fractal-app-lite] INFO:     Application startup complete.
[fractal-app-lite] INFO:     Uvicorn running on http://127.0.0.1:51531 (Press CTRL+C to quit)
[TIMING] backend ready: 4489ms
fractal-app-lite ready on :51531
[TIMING] navigation started: 4489ms
[fractal-app-lite] INFO:     127.0.0.1:51542 - "GET / HTTP/1.1" 200 OK
...
```

---

## macOS 26 — Apple Silicon (`macos-26`)

TODO

---

## macOS 15 — Intel (`macos-15-intel`)

TODO

---

## Linux (`ubuntu-22.04`)

**Test machine:** Lenovo 83JK, Intel Core Ultra 5 225H (14 cores / 14 threads), 32 GB RAM, Ubuntu 24.04.5 LTS.

**Version tested:** `v3.0.8`

### Download

1. Open the [Releases page](https://github.com/fractal-analytics-platform/fractal-app-lite/releases?q=v3&expanded=true).
2. In the latest `v3.x.y` release, download `v3.x.y-FractalLite-ubuntu-22.04.AppImage` (~320 MB).

### Install and launch

There is nothing to install: the `.AppImage` is a self-contained executable.

1. **Make it executable.** From the folder where you downloaded the file:

   ```bash
   chmod +x v3.x.y-FractalLite-ubuntu-22.04.AppImage
   ```

2. **Launch.** Run it from the same folder:

   ```bash
   ./v3.x.y-FractalLite-ubuntu-22.04.AppImage
   ```

   Launching from a terminal also shows the backend logs.

If the AppImage fails with `dlopen(): error loading libfuse.so.2`, install FUSE 2
(`sudo apt install libfuse2t64` on Ubuntu 24.04, `sudo apt install libfuse2` on Ubuntu 22.04).

---

## Windows (`windows-2025`)

**Test machine:** Lenovo 83JK, Intel Core Ultra 5 225H (14 cores / 14 threads), 32 GB RAM, Windows 11 Home 25H2 (build 26200).

**Version tested:** `v3.0.8`

### Download

1. Open the [Releases page](https://github.com/fractal-analytics-platform/fractal-app-lite/releases?q=v3&expanded=true).
2. In the latest `v3.x.y` release, download `v3.x.y-FractalLite-windows-2025.exe` (~195 MB).

If Microsoft Edge (SmartScreen) blocks the download with *"v3.x.y-FractalLite-windows-2025.exe isn't commonly
downloaded. Make sure you trust v3.x.y-FractalLite-windows-2025.exe before you open it."*, open the downloads
panel (`Ctrl+J`), click **…** next to the file, then **Keep**. In the dialog that opens, click
**Show more** → **Keep anyway**.

### Install and launch

1. **Install.** Double-click the `.exe`. The installer runs without asking anything and opens
   **Fractal Lite** when it finishes.
2. **Launch.** Afterwards, open **Fractal Lite** from the Start menu.
    > The first run is slower than the following ones.

---

## End-to-end test

The same test applies to every platform; platform-specific differences are noted inline.

1. **Create a project.** Click **New project** and fill in the modal.
2. **Register the task packages.** Go to **Task Management** and register these two packages with
   **Register git release**:

   - `fractal-tasks-core`: use the latest version.
   - `fractal-uzh-converters`: use the latest version.
     - **macOS Intel:** use a version newer than `v0.7.1`. Currently the only working one is the
       pre-release `v0.8.0b1`.
3. **Build the workflow.** Go to **Workflow** and add these three tasks, in this order:

   | Order | Task                                    | Arguments                                                                                                                                                        |
   | :---: | --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
   |   1   | Convert Evident ScanR Plate to OME-Zarr | `Acquisitions.ScanRAcquisitionModel.Path`: a folder with valid ScanR images, e.g. `fractal-app-lite/tests/data/hcs_1w1p1c1z1t/data`<br>`Overwrite`: `Overwrite` |
   |   2   | Project Image (HCS Plate)               | `Overwrite`: `true`                                                                                                                                              |
   |   3   | Threshold Segmentation                  | `Mode`: `Index`<br>`Identifier`: `0`<br>`Overwrite`: `true`                                                                                                      |
4. **Run.** Click **Run** and wait for the workflow to finish.
   - **Windows:** the run fails. The run page shows this error:

     ```text
     Workflow run failed: Task executable scanr/convert_scanr_init_task.py failed with exit code 1.
     --- output ---
     2026-10-19 21:23:23,110; run_fractal_task; INFO; START convert_scanr_init_task task
     Traceback (most recent call last):
       File "C:\Users\yuric\fractal_lite\collected_tasks\fractal_uzh_converters-0.8.0b1\src\fractal_uzh_converters\scanr\_utils.py", line 333, in parse_scanr_metadata
         with fs.open(metadata_path) as f:
              ~~~~~~~^^^^^^^^^^^^^^^
       File "C:\Users\yuric\fractal_lite\collected_tasks\fractal_uzh_converters-0.8.0b1\.pixi\envs\default\Lib\site-packages\fsspec\spec.py", line 1417, in open
         f = self._open(
             path,
         ...<4 lines>...
             **kwargs,
         )
       File "C:\Users\yuric\fractal_lite\collected_tasks\fractal_uzh_converters-0.8.0b1\.pixi\envs\default\Lib\site-packages\fsspec\implementations\local.py", line 216, in _open
         return LocalFileOpener(path, mode, fs=self, **kwargs)
       File "C:\Users\yuric\fractal_lite\collected_tasks\fractal_uzh_converters-0.8.0b1\.pixi\envs\default\Lib\site-packages\fsspec\implementations\local.py", line 393, in __init__
         self._open()
         ~~~~~~~~~~^^
       File "C:\Users\yuric\fractal_lite\collected_tasks\fractal_uzh_converters-0.8.0b1\.pixi\envs\default\Lib\site-packages\fsspec\implementations\local.py", line 398, in _open
         self.f = open(self.path, mode=self.mode)
                  ~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^
     FileNotFoundError: [Errno 2] No such file or directory: 'C:/Users/yuric/Desktop/fractal-app-lite/tests/data/hcs_1w1p1c1z1t/data/data/metadata.ome.xml'

     The above exception was the direct cause of the following exception:

     Traceback (most recent call last):
       File "C:\Users\yuric\fractal_lite\collected_tasks\fractal_uzh_converters-0.8.0b1\src\fractal_uzh_converters\scanr\convert_scanr_init_task.py", line 74, in <module>
         run_fractal_task(task_function=convert_scanr_init_task)
         ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
       File "C:\Users\yuric\fractal_lite\collected_tasks\fractal_uzh_converters-0.8.0b1\.pixi\envs\default\Lib\site-packages\fractal_task_tools\task_wrapper.py", line 103, in run_fractal_task
         metadata_update = task_function(**pars)
       File "C:\Users\yuric\fractal_lite\collected_tasks\fractal_uzh_converters-0.8.0b1\.pixi\envs\default\Lib\site-packages\pydantic\_internal\_validate_call.py", line 40, in wrapper_function
         return wrapper(*args, **kwargs)
       File "C:\Users\yuric\fractal_lite\collected_tasks\fractal_uzh_converters-0.8.0b1\.pixi\envs\default\Lib\site-packages\pydantic\_internal\_validate_call.py", line 137, in __call__
         res = self.__pydantic_validator__.validate_python(pydantic_core.ArgsKwargs(args, kwargs))
       File "C:\Users\yuric\fractal_lite\collected_tasks\fractal_uzh_converters-0.8.0b1\src\fractal_uzh_converters\scanr\convert_scanr_init_task.py", line 52, in convert_scanr_init_task
         tiled_images = parse_acquisitions(
             parse_function=parse_scanr_metadata,
             acquisitions=acquisitions,
             converter_options=converter_options,
         )
       File "C:\Users\yuric\fractal_lite\collected_tasks\fractal_uzh_converters-0.8.0b1\src\fractal_uzh_converters\common\_utils.py", line 232, in parse_acquisitions
         grouped = parse_acquisitions_grouped(
             parse_function=parse_function,
             acquisitions=acquisitions,
             converter_options=converter_options,
         )
       File "C:\Users\yuric\fractal_lite\collected_tasks\fractal_uzh_converters-0.8.0b1\src\fractal_uzh_converters\common\_utils.py", line 192, in parse_acquisitions_grouped
         _tiled_images = parse_function(
             acquisition_model=acq,
             converter_options=converter_options,
         )
       File "C:\Users\yuric\fractal_lite\collected_tasks\fractal_uzh_converters-0.8.0b1\src\fractal_uzh_converters\scanr\_utils.py", line 336, in parse_scanr_metadata
         raise ValueError(
             f"Could not parse OME-XML metadata file: {metadata_path}"
         ) from e
     ValueError: Could not parse OME-XML metadata file: C:/Users/yuric/Desktop/fractal-app-lite/tests/data/hcs_1w1p1c1z1t/data/data/metadata.ome.xml
     ```
