## CLIPasso Studio 3.0 – faster, draw along, one line, free format

**Turbo mode** (CLIPasso, ControlSketch, SceneSketch) – a switch in the input card: faster, with a slightly different result.
- The CLIP features of a fixed set of 64 augmentations are computed once instead of every step; with several sketches all run to a quarter and only the best one is finished; a sketch stops once it no longer improves.
- ControlSketch encodes with the small **TAESD** decoder (10 MB, downloaded on first use), works on a 384 px canvas and, on CPUs with AVX512-BF16/AMX, in bfloat16.
- Measured on 4 CPU cores: CLIPasso 1.02 → 0.70 s per iteration (a standard job with 3 sketches about 3× faster with the pruning), ControlSketch 15.1 → 2.3 s per iteration.

**Draw, continue, one line**
- **Brush style live**: ink, pencil or marker right in the studio, also while the sketch is being computed (palette in the bar above the sketch).
- **Pen + Continue with CLIPasso**: draw your own strokes into a finished sketch; CLIPasso adds new strokes around them and keeps yours fixed.
- **One line**: CLIPasso draws the subject in one single continuous stroke.

**Faster without turbo** – the same algorithms and the same quality as 2.4:
- New stroke rasterizer: a CLIPasso render step takes 47–62 instead of 68–152 ms, one line of 48 segments 40 instead of 4059 ms, ControlSketch 639 instead of 1752 ms (measured on a CPU).
- The models stay loaded between the jobs of a queue; on a CPU with at least 6 cores and enough memory the sketches of a CLIPasso or SwiftSketch job run in parallel.
- The app starts without loading PyTorch; exports run in the background.
- Note: the results are not bit-identical to 2.4 – tiny rounding differences of the new renderer grow over thousands of optimisation steps.

**Formats and inputs**
- **Free aspect ratio**: export in the shape of the photo or cropped to the strokes (with a margin) – SVG, PNG, PDF, animations, copy and *Export all*.
- **HEIC/HEIF** (iPhone), **AVIF**, TIFF, BMP, GIF; photos are turned upright by their EXIF rotation.
- **Webcam** photo and a **Recent images** menu in the studio.

**Gallery, queue, watched folder**
- **Gallery 2.0**: fast with thousands of sketches; multi-select (delete, export, favourite), title / notes / tags with a filter, sorting by score, duration, strokes or name, keyboard.
- **Queue**: reorder by dragging; pause, cancel, retry per row; details with *Load into the studio* and *Replace by the studio settings*; total time left. Failed and cancelled jobs stay after a restart.
- **Watched folder** (Settings): images saved into a folder are sketched and exported by themselves.

**Reliability**
- Graphics memory full → continue on the CPU or with smaller settings; finished sketches are kept.
- **Copy / save diagnostics** (Settings → System); rotated app log; the crash log of a crashed worker process is shown with the error.
- **Storage** (Settings): clear the mask cache, thumbnails, old updates and pasted images; when the output folder changes, the results can move along.
- Downloads check the free space first, verify every model by checksum and continue after an interruption, also from another mirror.
- The installer removes the libraries of the old version when updating, names the shortcuts per edition (CPU and GPU side by side) and, when uninstalling, asks whether to remove the models and app data too.
- *What's new?* in the update notice, *Check now* in the settings.

| File | For whom? |
|---|---|
| **`CLIPassoStudio-CPU-Portable.zip`** | **New:** portable without installation – unpack anywhere, start `CLIPassoStudio.exe`. Starts as fast as the installed app and updates itself. |
| **`CLIPassoStudio-CPU-Portable.exe`** | A single file – no installation. Starting takes about 15–40 s (unpacking). |
| **`CLIPassoStudio-CPU-Setup.exe`** | The app as an installer (fast start, Start menu entry). |
| **`CLIPassoStudio-GPU-Setup.exe`** + **all `CLIPassoStudio-GPU-Setup-*.bin`** | NVIDIA GPU edition (CUDA 12.8: GeForce GTX 16xx / RTX 20xx or newer, driver ≥ 570): CLIPasso and SceneSketch 10–50× faster, ControlSketch in minutes instead of hours. **Download all files into the same folder**, then run `CLIPassoStudio-GPU-Setup.exe`. |

**Notes**
- Windows SmartScreen may warn on the first start (“Unknown publisher”) → *More info* → *Run anyway*.
- CPU times: SwiftSketch ~5 s per sketch; CLIPasso “Fast” 5–15 min; SceneSketch “Fast” ≈ 20 min, “Standard” ≈ 2 h; ControlSketch several hours (GPU: a few minutes) – turbo mode shortens CLIPasso, ControlSketch and SceneSketch.
- Updating: *Install* in the update notice updates the app with one click; the installer versions install over the old version. Downloaded models, settings, the queue and the gallery are kept.
- Licence: CC BY-NC-SA 4.0 – **non-commercial use only**. The downloaded models have their own licences (see THIRD_PARTY_NOTICES.md).
- Checksums: `SHA256SUMS-CPU.txt` and `SHA256SUMS-GPU.txt`.
