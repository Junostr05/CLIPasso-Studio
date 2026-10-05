## CLIPasso Studio 3.2.1 – SceneSketch on the graphics card

**Fixed in 3.2.1**
- SceneSketch on an NVIDIA card: a scene with an object stopped at the end of its first cell with “Expected all tensors to be on the same device” – the background strokes cut at the object were made on the processor while the others stayed on the graphics card. Found with the new self-test; the renderer now also brings strokes from different devices together.
- The first small update: an app on 3.2.0 downloads only the files that changed (`…-Patch-from-3.2.0.exe` / `…-Portable-Patch-from-3.2.0.zip`).

**New in 3.2**

**Small updates**
- Every release now carries the file list of each edition. From the next update on, the app downloads only the files that changed: a small patch for the installed app (`…-Patch-from-<version>.exe`, the same silent one-click install) and for the portable ZIP. A release with a new PyTorch has no patch – then the full files come as before. The single portable exe is always replaced as a whole.
- The CI installs every CPU build, applies a test patch to it (it must delete a removed file and refuse another version), runs the self-test of the patched app and uninstalls it again.

**Steadier**
- **Self-test** (Settings → System): short runs of every method, continuing a job, the background removal, the warm worker – with a result per part and its log.
- **Report a problem …** (error dialogs, crash notice, Settings → System): a prepared GitHub issue with the error, its traceback and the diagnostics – paths with the user name shortened to `~`, shown and editable before anything is sent; a text too long for the address goes to the clipboard in full.
- **Memory guard:** before a job starts or is queued, the app compares what it needs (measured per method) with the free RAM and the graphics memory, and offers smaller settings (or the processor) instead of failing after minutes.
- **Quality benchmark in the CI:** fixed short runs of CLIPasso, SwiftSketch and SceneSketch on every release; a CLIP score that drops by more than 5 points fails the release; a drop of more than 2 points, slower runs or more memory are reported (times are scaled by a calibration of the CI machine; processors round a little differently, so small score changes only warn).

**Faster**
- **SDXL piece by piece on small graphics cards:** on cards below 8 GB, ControlSketch's optional SDXL attention now runs piece by piece on the card (the weights wait in the RAM, about 9 GB, the card needs about 2 GB) instead of only on the processor. The question when SDXL is chosen offers *Graphics card, piece by piece (recommended)*, *Processor* or *CLIP*; a full card falls back by itself: whole card → piece by piece → processor. The measured time per step goes into the estimates.
- **Several graphics cards:** the sketches of a CLIPasso, SwiftSketch or ControlSketch job are spread over all usable cards, one worker per card (Settings → *Use several graphics cards*, on by default).
- Measured and left out: int8 networks for ControlSketch on the processor were only about 10 % faster – not worth a change in the pictures.

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
