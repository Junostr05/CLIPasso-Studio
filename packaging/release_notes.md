## CLIPasso Studio 2.4 – a much better mask, and you can fix it

**BiRefNet finds the object.** Removing the background (CLIPasso, SwiftSketch, ControlSketch) and separating object and background (SceneSketch) now use **BiRefNet**, a state-of-the-art segmentation network, instead of U²-Net. It keeps fine parts (a sign's pole, a shower hose, thin legs), finds several objects (two teddy bears instead of one) and leaves no grey haze of background around the object.
- Downloaded once on the first run that removes the background (444 MB) – a few seconds per image on a CPU, well under one on a GPU. Masks are cached, so the same image is never computed twice.
- **Mask model** in the image settings: *BiRefNet* (best, the default), *BiRefNet lite* (faster, 89 MB) or *U²-Net* (included, the original).

**See and fix the mask before you start**
- The studio shows the object on your photo as soon as you pick one (the eye button hides it).
- **Edit mask** (brush icon): click a part to remove it, click next to the object to add an area of similar colour (magic wand), or paint with the brush; undo / redo. Every method uses your mask – also in the queue and when a job is continued.
- **Fit the object** (CLIPasso, SwiftSketch): a small object in a large photo is cropped so it fills the canvas – a full-size sketch instead of a tiny one.

**Export**
- **Stroke by stroke**: GIF, MP4 and WebP can show the finished strokes being drawn one after another, like by hand (or the drawing process as before).
- **SVG · animated**: an SVG that draws itself in the browser – for websites and presentations.
- **PDF** for printing (vector, any size) – also in “Export all”.
- **Copy** (Ctrl+C, or the gallery card menu): the sketch goes to the clipboard – paste it into Word, PowerPoint, Figma, Photoshop …

**Workflow**
- **Drag & drop** several images or whole folders onto the studio or the queue.
- **When the queue is done**: sleep or shut down the PC after the last job (with a 60-second countdown) – for runs overnight.
- **Model folder**: keep the downloaded models (up to ~10 GB) on another drive (Settings → Files).
- A short **guide** on the first start (again via “Show the guide” on the About page).

| File | For whom? |
|---|---|
| **`CLIPassoStudio-CPU-Portable.exe`** | Just download and run – no installation. Works on any 64-bit Windows 10/11 PC. Starting takes about 15–40 s (unpacking). |
| **`CLIPassoStudio-CPU-Setup.exe`** | The same app as an installer (faster start, Start menu entry). |
| **`CLIPassoStudio-GPU-Setup.exe`** + **all `CLIPassoStudio-GPU-Setup-*.bin`** | NVIDIA GPU edition (CUDA 12.8: GeForce GTX 16xx / RTX 20xx or newer, driver ≥ 570): CLIPasso and SceneSketch 10–50× faster, ControlSketch in minutes instead of hours. **Download all files into the same folder**, then run `CLIPassoStudio-GPU-Setup.exe`. |

**Notes**
- Windows SmartScreen may warn on the first start (“Unknown publisher”) → *More info* → *Run anyway*.
- CPU times: SwiftSketch ~5 s per sketch; CLIPasso “Fast” 5–15 min; SceneSketch “Fast” ≈ 20 min, “Standard” ≈ 2 h; ControlSketch several hours (GPU: a few minutes).
- Updating: the installer versions install over the old version; downloaded models and settings are kept. From 2.3 on, *Install* in the update notice updates the app with one click.
- Licence: CC BY-NC-SA 4.0 – **non-commercial use only**. The downloaded models have their own licences (see THIRD_PARTY_NOTICES.md).
- Checksums: `SHA256SUMS-CPU.txt` and `SHA256SUMS-GPU.txt`.
