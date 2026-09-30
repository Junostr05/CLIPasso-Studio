## CLIPasso Studio 2.3 – continue where it stopped, touch up, export in style

**Continue interrupted jobs.** A long run – SceneSketch “Standard” takes about 2 hours on a CPU, ControlSketch hours – no longer starts from zero when the app or the PC is closed, the app crashes or you cancel: the running sketch saves a checkpoint every 30 seconds, finished sketches are kept, and **Continue** (in the gallery, in the studio, or when the app starts) picks up exactly where it stopped.

**Touch-ups**
- **Eraser** in the sketch view: click or drag over strokes to remove them (the stroke under the cursor turns red), with undo / redo (Ctrl+Z / Ctrl+Y). The original sketch stays; exports and the gallery use the touched-up one.
- **Crop, rotate, flip** the input image (“Edit” next to Open): free, square, 4:3 or 3:4 – saved as a copy, the original file is not changed.
- **ControlSketch: “Remove background” can be switched off** to sketch the whole picture (like the original, it is on by default).

**Export**
- **Brush styles**: plain lines, **ink** (tapered brush-pen strokes), **pencil** (soft graphite lines) or **marker** – for SVG, PNG, the animations and the SceneSketch matrix.
- **Folder import**: add a whole folder of images to the queue.
- **Export many at once**: all finished results of the queue, or everything the gallery shows (e.g. your favourites) – SVG, SVG · 1 layer or PNG into one folder.

**App**
- **Updates with one click**: *Install* in the update notice downloads the new version, checks it and installs it (installed app: it restarts by itself; portable: the new exe is saved next to the old one).
- **Interface size** 90–150 % (Settings → Appearance), for small laptop screens or large monitors.

| File | For whom? |
|---|---|
| **`CLIPassoStudio-CPU-Portable.exe`** | Just download and run – no installation. Works on any 64-bit Windows 10/11 PC. Starting takes about 15–40 s (unpacking). |
| **`CLIPassoStudio-CPU-Setup.exe`** | The same app as an installer (faster start, Start menu entry). |
| **`CLIPassoStudio-GPU-Setup.exe`** + **all `CLIPassoStudio-GPU-Setup-*.bin`** | NVIDIA GPU edition (CUDA 12.8: GeForce GTX 16xx / RTX 20xx or newer, driver ≥ 570): CLIPasso and SceneSketch 10–50× faster, ControlSketch in minutes instead of hours. **Download all files into the same folder**, then run `CLIPassoStudio-GPU-Setup.exe`. |

**Notes**
- Windows SmartScreen may warn on the first start (“Unknown publisher”) → *More info* → *Run anyway*.
- CPU times: SwiftSketch ~5 s per sketch; CLIPasso “Fast” 5–15 min; SceneSketch “Fast” ≈ 20 min, “Standard” ≈ 2 h; ControlSketch several hours (GPU: a few minutes).
- Updating: the installer versions install over the old version; downloaded models and settings are kept. One-click updates start with this version – 2.3 itself is downloaded once more by hand.
- Licence: CC BY-NC-SA 4.0 – **non-commercial use only**. The downloaded models have their own licences (see THIRD_PARTY_NOTICES.md).
- Checksums: `SHA256SUMS-CPU.txt` and `SHA256SUMS-GPU.txt`.
