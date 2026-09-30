> **Experimental build (beta).** SceneSketch is new; this build is for trying it out while the last quality checks run. The final 2.1.0 follows shortly – it installs over this one.

## CLIPasso Studio 2.1 – SceneSketch: whole scenes

**New: SceneSketch** ([CLIPascene](https://clipascene.github.io/CLIPascene/), ICCV 2023) as the fourth method. It sketches a whole scene with its background: the object in the foreground (U²-Net) and the background (filled in behind the object with LaMa) are sketched separately and combined. The result is a **matrix of sketches**: from precise to loose (fidelity: one column per CLIP layer) and from detailed to sparse (simplicity: strokes are removed step by step).

- The new **Matrix** view in the studio shows every sketch of the matrix; click one to select it for export, double-click to open it.
- Presets: *Fast* (one scene sketch), *Standard* (one column with 4 simplification levels), *Quality* (the full 3 × 9 matrix of the paper – hours, even on a GPU).
- All options of the original scripts are available (fidelity layers, simplification steps, iterations, …), and the command line accepts the original arguments (`--method scenesketch --im_name … --layers 2,8,11`).
- Two sample scenes from the SceneSketch repository (ballerina, house).
- The LaMa inpainting model (≈ 200 MB) is downloaded the first time you use SceneSketch.
- Objects on a plain background are sketched without a (pointless) background sketch.

**Also new**
- **SVG · 1 layer** export: all strokes as one path in a single layer – for plotters, cutting machines (Cricut, Silhouette) and laser software, which otherwise import every stroke as its own layer.
- The app starts in the language of Windows (German or English) – since 2.0.1.

| File | For whom? |
|---|---|
| **`CLIPassoStudio-CPU-Portable.exe`** | Just download and run – no installation. Works on any 64-bit Windows 10/11 PC. Starting takes about 15–40 s (unpacking). |
| **`CLIPassoStudio-CPU-Setup.exe`** | The same app as an installer (faster start, Start menu entry). |
| **`CLIPassoStudio-GPU-Setup.exe`** + **all `CLIPassoStudio-GPU-Setup-*.bin`** | NVIDIA GPU edition (CUDA 12.8: GeForce GTX 16xx / RTX 20xx or newer, driver ≥ 570): CLIPasso and SceneSketch 10–50× faster, ControlSketch in minutes instead of hours. **Download all files into the same folder**, then run `CLIPassoStudio-GPU-Setup.exe`. |

**Notes**
- Windows SmartScreen may warn on the first start (“Unknown publisher”) → *More info* → *Run anyway*.
- CPU times: SwiftSketch ~5 s per sketch; CLIPasso “Fast” 5–15 min; SceneSketch “Fast” ≈ 20 min; ControlSketch several hours (GPU: a few minutes).
- Updating: the installer versions install over the old version; downloaded models and settings are kept.
- Licence: CC BY-NC-SA 4.0 – **non-commercial use only**. The downloaded models have their own licences (see THIRD_PARTY_NOTICES.md).
- Checksums: `SHA256SUMS-CPU.txt` and `SHA256SUMS-GPU.txt`.
