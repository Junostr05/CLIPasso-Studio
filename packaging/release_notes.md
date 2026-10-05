## CLIPasso Studio 3.1 – older graphics cards (GTX 9xx / 10xx)

**Older NVIDIA cards on the GPU edition**
- NVIDIA cards older than the GTX 16xx – e.g. a **GTX 1060** or GTX 970 – now compute on the graphics card instead of the processor. They are not in the app's PyTorch build (CUDA 12.8 starts with compute capability 7.5), so the GPU edition detects such a card at the start and offers an **add-on**: the official PyTorch 2.11 build with CUDA 12.6 (2.6 GB download, 4.1 GB on the disk, checked by SHA-256, downloaded from download.pytorch.org). After a restart the app uses it automatically, also in its worker processes. Newer cards need nothing and download nothing.
- Tried on a GTX 1060 6 GB: the card is detected, CLIPasso and SceneSketch run on it – much faster than on the processor.
- **Settings → System → Older graphics cards**: download the add-on, switch it on or off, remove it. An update to a version with another PyTorch asks to download the matching add-on again; add-ons of earlier versions are removed.

**SDXL on graphics cards below 8 GB** (ControlSketch's optional *SDXL cross-attention*)
- SDXL needs about 7 GB of graphics memory. On a smaller card the app asks when you choose it – *Compute on the processor* or *Use CLIP* – with *Remember my choice*; the answer can be changed under Settings → System.
- On the processor this one step uses all cores (measured: about 75 min on 4 cores, faster with more; about 15 GB of RAM), shows its progress in the status line, can be paused and cancelled, and is kept with the run, so continuing it does not compute it again. Everything after it runs on the graphics card.
- A bigger card that runs out of memory during SDXL hands the step to the processor by itself.

**Precision**
- **Always compute in fp32** (Settings → System): off by default – Stable Diffusion, ControlNet, BLIP and BiRefNet compute in fp16 on the graphics card as before (half the graphics memory, the same pictures). On: everything in fp32, to compare or if a card computes wrongly with fp16.

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
