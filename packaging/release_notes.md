## CLIPasso Studio 3.1 beta 1 – older graphics cards (GTX 9xx / 10xx)

**A pre-release for testing** – the app does not offer it as an update; 3.0.0 stays the current version until 3.1.0.

**Older NVIDIA cards on the GPU edition**
- NVIDIA cards older than the GTX 16xx – e.g. a **GTX 1060** or GTX 970 – now compute on the graphics card instead of the processor. They are not in the app's PyTorch build (CUDA 12.8 starts with compute capability 7.5), so the GPU edition detects such a card at the start and offers an **add-on**: the official PyTorch 2.11 build with CUDA 12.6 (2.6 GB download, 4.1 GB on the disk, checked by SHA-256, downloaded from download.pytorch.org). After a restart the app uses it automatically, also in its worker processes. Newer cards need nothing and download nothing.
- **Settings → System → Older graphics cards**: download the add-on, switch it on or off, remove it. **Graphics card precision**: *Automatic* (float16 for Stable Diffusion, ControlNet, BLIP and BiRefNet, as before) or *Always fp32* – to compare speed and memory on an older card.
- An update to a version with another PyTorch asks to download the matching add-on again; add-ons of earlier versions are removed.

**Please test (GTX 1060 6 GB)**
1. Install the GPU edition below (`CLIPassoStudio-GPU-Setup.exe` + both `.bin` files in one folder).
2. At the first start the app offers the add-on for your card – *Download now*, then restart.
3. Settings → System should show *Active: PyTorch 2.11.0 with CUDA 12.6*, the card without “not supported”, and the studio *Device: GPU*.
4. CLIPasso and SceneSketch with the *Fast* preset; ControlSketch once with *Automatic* and once with *Always fp32* precision (it may run out of the 6 GB with fp32 – the app then offers to continue on the CPU).
5. *Copy diagnostics* (Settings → System) and send it together with the times.

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
