<p align="center">
  <img src="clipasso_studio/resources/app_icon.png" width="96" alt="CLIPasso Studio">
</p>

<h1 align="center">CLIPasso Studio</h1>

<p align="center">
  A desktop app that turns photos into vector line drawings – with three methods in one interface:<br>
  <a href="https://github.com/yael-vinker/CLIPasso"><b>CLIPasso</b></a> (SIGGRAPH 2022) ·
  <a href="https://github.com/swiftsketch/SwiftSketch"><b>SwiftSketch</b></a> (SIGGRAPH 2025) ·
  <a href="https://github.com/swiftsketch/SwiftSketch"><b>ControlSketch</b></a><br>
  Every option adjustable, live preview, method comparison – all in a single exe.
</p>

<p align="center">
  <a href="https://github.com/Junostr05/CLIPasso-Studio/releases/latest"><b>⬇ Download (Windows)</b></a> ·
  <a href="#the-three-methods">Methods</a> ·
  <a href="#features">Features</a> ·
  <a href="#usage">Usage</a> ·
  <a href="#building-from-source">Build</a>
</p>

<p align="center">
  <img src="docs/screenshots/methods_camel.png" width="820" alt="One photo, three methods">
</p>
<p align="center"><sub>Made with this app on a CPU: CLIPasso (16 strokes, “Fast” preset, 11 min), SwiftSketch (32 strokes, 4 s per sketch), ControlSketch (32 strokes – only 250 of the 2000 iterations, 67 min; with an NVIDIA GPU the full run takes a few minutes).</sub></p>

![Studio](docs/screenshots/studio_dark_en.png)

## Download

The [releases page](https://github.com/Junostr05/CLIPasso-Studio/releases/latest) has three variants:

| File | Description |
|---|---|
| **`CLIPassoStudio-CPU-Portable.exe`** (≈ 1 GB) | A single file: download, double-click, done. No installation and no Python needed. Everything CLIPasso needs is included; SwiftSketch and ControlSketch download their models the first time you use them (see below). It unpacks itself on start (15–40 s, with a splash screen). |
| **`CLIPassoStudio-CPU-Setup.exe`** (≈ 1 GB) | The same app as an installer: install once, then it starts quickly and gets Start menu and desktop shortcuts. No admin rights needed. |
| **`CLIPassoStudio-GPU-Setup.exe`** + `…-GPU-Setup-*.bin` (≈ 3.5 GB) | Edition for NVIDIA graphics cards (CUDA 12.8: GeForce GTX 16xx / RTX 20xx or newer, driver ≥ 570). CLIPasso runs 10–50× faster, and **ControlSketch is only practical with this edition**. Because it is larger than 2 GB, it is split into several files: **download all of them into the same folder** and run the `Setup.exe`. Without a suitable GPU it automatically falls back to the CPU. |

> Windows SmartScreen may warn about an “unknown publisher” (the exe is not signed) → *More info* → *Run anyway*.

## The three methods

Pick the method at the top of the studio with one click. Parameters, presets, time estimate and hints adapt to it, and the settings of each method are remembered.

| | **CLIPasso** | **SwiftSketch** | **ControlSketch** |
|---|---|---|---|
| How it works | Optimises Bézier strokes until CLIP “sees” the sketch like the photo | A diffusion model generates 32 strokes in 50 denoising steps, a refinement network polishes them | Optimises strokes with an SDS loss from Stable Diffusion 1.5, steered by a ControlNet (depth, edges …) |
| Speed | CPU: minutes · GPU: seconds to minutes | **CPU: ~5 s per sketch** | GPU: ~5–10 min · CPU: ~10 hours |
| Strokes | any number (1–256), multi-stage training | fixed at 32 (as trained) | any number (default 32) |
| Models | included | ≈ 710 MB, downloaded on first use | ≈ 3–4 GB (SD 1.5, ControlNet, detector, BLIP), downloaded on first use |
| Strengths | very configurable, level of abstraction, text guidance | lightning fast, clean “artist” strokes | very natural, detailed sketches |

<p align="center">
  <img src="docs/screenshots/camel_drawing.gif" width="260" alt="CLIPasso optimising the strokes">
  <img src="docs/screenshots/swiftsketch_camel.gif" width="260" alt="SwiftSketch denoising the strokes">
</p>
<p align="center"><sub>Left: CLIPasso optimises the strokes. Right: SwiftSketch forms them out of noise in 50 denoising steps (GIF export of the app).</sub></p>

**Which one suits my picture?** The **Compare** page sketches the current image with all selected methods (standard preset or your studio settings) and shows the results side by side – with CLIP score, compute time and stroke count – and highlights the method with the highest CLIP score. Earlier results for the same image are shown automatically.

![Compare](docs/screenshots/compare_dark_en.png)

## Features

- **Every option of the originals** in the interface, each with a tooltip, a reset button and search:
  - *CLIPasso*: every argument of `run_object_sketching.py` and `config.py` (strokes, iterations, seeds, mask, working resolution, stroke width, segments, curve type, initial SVG, CLIP/DINO saliency, XDoG, softmax temperature, text target, CLIP model, conv loss, layer weights, FC weight, CLIP/text guidance, L2/LPIPS, learning rates, scheduler, opacity, multi-stage training, augmentations …).
  - *SwiftSketch*: all options of `generate.py` – guidance strength, refinement on/off, also saving the diffusion sketch, aspect ratio, seed, plus background mask and stroke width.
  - *ControlSketch*: all options of `config.py` – strokes, iterations, prompt (or automatic via BLIP), ControlNet condition (depth, Canny, HED, scribble, segmentation, normals), ControlNet and guidance strength, timesteps, object size, working and output resolution, attention initialisation (CLIP, or SDXL with an object name), stroke sorting, learning rate …
  - Checked by a test (`tests/test_settings.py`): every original argument has a setting with the same default value.
- **Live preview** for all methods: you watch the sketch being drawn (for SwiftSketch every denoising step). Plus a photo/sketch slider, the attention map with the stroke start points, the mask, the ControlNet condition image for ControlSketch, a loss or CLIP score curve, the remaining time and thumbnails of all seeds. **Several sketches per image – the best one is picked automatically** (CLIPasso: lowest loss; SwiftSketch and ControlSketch: highest CLIP score).
- **Presets** (Fast / Standard / Quality) per method, import/export of the settings as JSON, “copy command line”.
- **Export**: SVG (stroke colour, width, background), PNG at any resolution, **GIF/MP4 of the drawing process** – for SwiftSketch, how the strokes emerge from noise. Abstraction series with one click (CLIPasso, ControlSketch).
- **Queue** for many images, also with mixed methods, with pause/cancel, a notification when done and protection against sleep mode. **Gallery** of all results with a method filter.
- **Models** page grouped by method: download with progress, delete, manual import of the SwiftSketch weights (in case Google Drive hits its daily quota).
- **Dark/light theme**, **English/German** interface (switchable at runtime), and a command-line mode that is compatible with the original arguments of all three methods.

<p>
  <img src="docs/screenshots/studio_controlsketch_dark_en.png" width="49%" alt="ControlSketch in the studio">
  <img src="docs/screenshots/studio_light_en.png" width="49%" alt="Light theme">
</p>

## Usage

1. Choose the method at the top. If models are missing, one click on **Download** in the notice bar is enough.
2. Drag an image onto **Input image** (or use *Open* / *Samples*). For non-square images, turn on **Keep aspect ratio**.
3. Pick a preset, adjust parameters if you like, and click **Create sketch**.
4. Export the best sketch (★) as SVG/PNG/GIF/MP4. The results are also saved in the output folder (default: `Documents\CLIPasso Studio`) – for every run `best_iter.svg`, `svg_logs/`, `config.json` (including the CLIP score) and `<run>_best.svg`.

**Compute time (CPU):** SwiftSketch ~5 s per sketch. CLIPasso: *Fast* preset 5–15 min, *Standard* 45–90 min. ControlSketch needs about 10 hours per sketch on a CPU – a few minutes with an NVIDIA GPU.

**CLIP score:** the cosine similarity (in %) of the CLIP ViT-B/32 image features of the sketch and the (masked) input image. It is computed the same way for every method, which makes them comparable – in the end, go with your taste.

### Command line

```bat
CLIPassoStudio.exe --cli --target_file camel.png --num_strokes 16 --mask_object 1 --num_sketches 3
CLIPassoStudio.exe --cli --method swiftsketch --input_data camel.png --guidance_param 2.5 --num_sketches 4
CLIPassoStudio.exe --cli --method controlsketch --target camel.png --condition depth --caption "a camel"
CLIPassoStudio.exe --cli --method swiftsketch --help
```

In CLI mode, missing models are downloaded automatically (`--no_download` prevents that).

## How it works / differences from the originals

**CLIPasso** – the original code (painter, loss, optimisation, selection of the best sketch), ported to Python 3.11 / PyTorch 2.11:
- **Renderer:** instead of the C++/CUDA rasteriser *diffvg*, which is hard to build on Windows, the app uses a **differentiable Bézier renderer in pure PyTorch** (`clipasso_studio/engine/renderer.py`, gradients tested against finite differences). All three methods use it.
- **Bugs of the original fixed**, so that every option works: `percep_loss` (L2/LPIPS) and `clip_text_guide` were not wired up, `lr_scheduler` called a missing function, the “Cos” conv loss crashed for ResNets, `num_stages` was not implemented in the main loop, and `mask_object_attention`, `augment_both`, `include_target_in_aug` and `aug_scale_min` had no effect.

**SwiftSketch** – an independent implementation of the transformer decoder, the DDPM sampler (cosine schedule, x₀ prediction, classifier-free guidance) and the refinement step; the original repository has no licence file, so no code is copied. It loads the **authors' official weights** unchanged and was checked against the original code: identical network outputs (max. difference 0.0) and sampler steps (≤ 1.4·10⁻⁶). One difference: the background mask comes from U²-Net instead of BRIA RMBG-1.4, whose licence is non-commercial and whose download is gated.

**ControlSketch** – also an independent implementation, built on 🤗 diffusers. Differences from the original:
- By default the stroke initialisation uses **CLIP attention** (bundled) instead of SDXL cross-attention; SDXL (≈ 7 GB) can be selected as soon as an object name is given.
- Automatic captions with **BLIP** (0.9 GB) instead of BLIP-2 OPT-2.7b (15 GB); entering your own prompt skips this.
- Condition images without OpenCV/controlnet_aux: depth with MiDaS DPT-Hybrid (the same network), Canny as a NumPy port of `cv2.Canny` (compared with OpenCV in a test), HED as a port of the Apache-2.0 network, segmentation with UperNet. **Normals** are computed from the depth as described in the ControlNet 1.0 model card (the original uses NormalBae + ControlNet 1.1).
- U²-Net instead of RMBG-1.4, K-means in NumPy instead of scikit-learn, the PyTorch renderer instead of diffvg; there is no `lr_scheduler` option because the original never uses it.

The SwiftSketch and ControlSketch models are not bundled: they are downloaded from the official sources on first use (the authors' Google Drive, and Hugging Face with pinned revisions) and stored locally (ControlSketch models in float16).

## Building from source

```bash
python -m venv .venv && .venv\Scripts\activate           # Python 3.11
pip install -r requirements/torch-cpu.txt                 # or torch-gpu.txt
pip install -r requirements/dev.txt -r requirements/build.txt
python tools/fetch_models.py                              # ~800 MB of bundled models into ./models
python -m clipasso_studio                                 # run the app from source
python -m pytest -q                                       # tests (SwiftSketch/ControlSketch with tiny models)
python -m clipasso_studio --selftest out                  # short run of all three methods
set MODE=onefile&& pyinstaller packaging\clipasso_studio.spec   # portable exe
```

The complete Windows build (both editions, installers, self-test of the exe and the release) runs in [`.github/workflows/build.yml`](.github/workflows/build.yml). A manual run (*Run workflow* with a `release_tag`) creates a release; the `cpu` and `gpu` switches build the editions separately.

## Licence & credits

- **CLIPasso** – Yael Vinker, Ehsan Pajouheshgar, Jessica Y. Bo, Roman Christian Bachmann, Amit Haim Bermano, Daniel Cohen-Or, Amir Zamir, Ariel Shamir: *CLIPasso: Semantically-Aware Object Sketching*, ACM TOG (SIGGRAPH 2022) – [Paper](https://arxiv.org/abs/2202.05822) · [Project](https://clipasso.github.io/clipasso/) · [Code](https://github.com/yael-vinker/CLIPasso).
- **SwiftSketch / ControlSketch** – Ellie Arar, Yarden Frenkel, Daniel Cohen-Or, Ariel Shamir, Yael Vinker: *SwiftSketch: A Diffusion Model for Image-to-Vector Sketch Generation*, SIGGRAPH 2025 – [Paper](https://arxiv.org/abs/2502.08642) · [Project](https://swiftsketch.github.io/) · [Code](https://github.com/swiftsketch/SwiftSketch).

Like CLIPasso, this app is licensed under **[CC BY-NC-SA 4.0](LICENSE)** – **non-commercial use only**. The SwiftSketch weights are provided by the authors without an explicit licence (research/personal use); Stable Diffusion 1.5 and ControlNet are licensed under CreativeML OpenRAIL-M, which comes with use restrictions. All components and licences: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
