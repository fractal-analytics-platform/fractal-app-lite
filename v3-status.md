# Fractal Lite v3 — Status Report

> Branch: `v3` · Latest release: [`v3.0.7`](https://github.com/fractal-analytics-platform/fractal-app-lite/releases/tag/v3.0.7)

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

**End-to-end test:** see [End-to-end test](#end-to-end-test).

---

## macOS 26 — Apple Silicon (`macos-26`)

TODO

## macOS 15 — Intel (`macos-15-intel`)

TODO

## Linux (`ubuntu-22.04`)

TODO

## Windows (`windows-2025`)

**Test machine:** TODO

**Version tested:** `v3.0.7`

### Download

1. Open the [Releases page](https://github.com/fractal-analytics-platform/fractal-app-lite/releases?q=v3&expanded=true).
2. In the latest `v3.x.y` release, download `v3.x.y-FractalLite-windows-2025.exe`.

If Microsoft Edge (SmartScreen) blocks the download with *"v3.x.y-FractalLite-windows-2025.exe isn't commonly
downloaded. Make sure you trust v3.x.y-FractalLite-windows-2025.exe before you open it."*, open the downloads
panel (`Ctrl+J`), click **…** next to the file, then **Keep**. In the dialog that opens, click
**Show more** → **Keep anyway**.

### Install and launch

TODO

**End-to-end test:** see [End-to-end test](#end-to-end-test).

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
