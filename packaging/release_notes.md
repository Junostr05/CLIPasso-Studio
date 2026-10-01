## CLIPasso Studio 2.4 – a much better object mask

**BiRefNet finds the object.** Removing the background (CLIPasso, SwiftSketch, ControlSketch) and separating object and background (SceneSketch) now use **BiRefNet**, a state-of-the-art segmentation network, instead of U²-Net. It keeps fine parts (a sign's pole, a shower hose, thin legs), finds several objects (two teddy bears instead of one), and leaves no grey haze of background around the object – so the sketch shows what you wanted and nothing else.
- Downloaded once on the first run that removes the background (444 MB, Hugging Face) – or on the Models page.
- On a CPU it takes a few seconds per image (GPU: well under a second); the mask is cached, so the same image again – another seed, the parallel sketches, a re-run with other settings – does not compute it again.
- **Mask model** in the image settings: *BiRefNet* (best, the default), *BiRefNet lite* (faster, 89 MB) or *U²-Net* (included, the mask of the original CLIPasso).
- Jobs interrupted with 2.3 continue with U²-Net, so their sketches still match.

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
