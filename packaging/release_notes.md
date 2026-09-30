## CLIPasso Studio 2.0.1

**What's new in 2.0.1**
- The app now starts in the **language of Windows**: German on a German Windows, English everywhere else. *Settings → Language* still lets you pick German or English; the new default entry is *Automatic*. If you used 2.0.0 and never changed the language, the automatic setting applies to you as well.
- The installer falls back to English on Windows versions that are neither German nor English.

## CLIPasso Studio 2.0 – three methods in one app

Besides **[CLIPasso](https://github.com/yael-vinker/CLIPasso)** (SIGGRAPH 2022), the app draws with **[SwiftSketch](https://github.com/swiftsketch/SwiftSketch)** (SIGGRAPH 2025, a diffusion model – one sketch in seconds, even on a CPU) and **ControlSketch** (Stable Diffusion 1.5 + ControlNet – very natural sketches, needs an NVIDIA GPU). Pick the method at the top of the studio; the **Compare** page sketches an image with every method and highlights the best one.

| File | For whom? |
|---|---|
| **`CLIPassoStudio-CPU-Portable.exe`** | Just download and run – no installation. Works on any 64-bit Windows 10/11 PC. Starting takes about 15–40 s (unpacking). |
| **`CLIPassoStudio-CPU-Setup.exe`** | The same app as an installer (faster start, Start menu entry). |
| **`CLIPassoStudio-GPU-Setup.exe`** + **all `CLIPassoStudio-GPU-Setup-*.bin`** | NVIDIA GPU edition (CUDA 12.8: GeForce GTX 16xx / RTX 20xx or newer, driver ≥ 570): CLIPasso 10–50× faster, ControlSketch in minutes instead of hours. **Download all files into the same folder**, then run `CLIPassoStudio-GPU-Setup.exe`. |

**New in 2.0**
- Method switcher in the studio, with its own parameters, presets, tooltips and time estimate for each method; every option of SwiftSketch's `generate.py` and ControlSketch's `config.py` can be set.
- **Compare** page: one image, several methods, results side by side with CLIP score, compute time and stroke count.
- A uniform **CLIP score** for every sketch; SwiftSketch and ControlSketch use it to pick the best of several sketches.
- Live preview for the new methods as well (for SwiftSketch every denoising step, which can also be exported as GIF/MP4).
- The models for SwiftSketch (≈ 710 MB) and ControlSketch (≈ 3–4 GB) are downloaded the first time you use them – one click in the notice bar or on the **Models** page.
- Queue, gallery (with a method filter) and command line (`--method swiftsketch|controlsketch`) for all methods.

**Notes**
- Windows SmartScreen may warn on the first start (“Unknown publisher”) → *More info* → *Run anyway*.
- CPU times: SwiftSketch ~5 s per sketch; CLIPasso “Fast” 5–15 min, “Standard” 45–90 min; ControlSketch several hours (GPU: a few minutes).
- Updating: the installer versions install over the old version; downloaded models and settings are kept.
- Licence: CC BY-NC-SA 4.0 – **non-commercial use only**. The downloaded models have their own licences (see THIRD_PARTY_NOTICES.md).
- Checksums: `SHA256SUMS-CPU.txt` and `SHA256SUMS-GPU.txt`.
