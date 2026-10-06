# Third-party notices

CLIPasso Studio bundles or is derived from the following works.

| Component | Source | Licence | Used for |
|---|---|---|---|
| **CLIPasso** (code in `clipasso_studio/engine/painter.py`, `losses.py`, `pipeline.py`, `masking.py`) | https://github.com/yael-vinker/CLIPasso – Yael Vinker, Ehsan Pajouheshgar, Jessica Y. Bo, Roman Christian Bachmann, Amit Haim Bermano, Daniel Cohen-Or, Amir Zamir, Ariel Shamir | CC BY-NC-SA 4.0 | sketching method, optimisation loop, losses |
| **CLIP** (code in `clipasso_studio/engine/clip_/`, model weights RN101, ViT-B/32 and optional variants) | https://github.com/openai/CLIP – OpenAI | MIT | perceptual loss, saliency |
| **U²-Net** (code in `clipasso_studio/engine/u2net/`, weights `u2net.pth`) | https://github.com/xuebinqin/U-2-Net – Xuebin Qin et al. | Apache-2.0 | background mask |
| **BiRefNet** (network ported to `clipasso_studio/engine/birefnet.py`, including the Swin Transformer backbone; weights `ZhengPeng7/BiRefNet` and `ZhengPeng7/BiRefNet_lite`, not bundled – downloaded on first use and stored in float16) | https://github.com/ZhengPeng7/BiRefNet – Peng Zheng, Dehong Gao, Deng-Ping Fan, Li Liu, Jorma Laaksonen, Wanli Ouyang, Nicu Sebe; Swin Transformer: https://github.com/microsoft/Swin-Transformer – Microsoft | MIT (both) | object mask (background removal) |
| **DINO** (code in `clipasso_studio/engine/dino/`, weights ViT-S/8) | https://github.com/facebookresearch/dino – Meta AI | Apache-2.0 | alternative saliency |
| **OpenCLIP ViT-B/16, LAION-2B** weights `laion/CLIP-ViT-B-16-laion2B-s34B-b88K` (experimental, not bundled – downloaded only on request; only the image part is stored, in float16; run by the bundled CLIP code) | https://github.com/mlfoundations/open_clip – Gabriel Ilharco, Mitchell Wortsman, Ross Wightman et al.; training data LAION-2B | MIT | experimental “Semantic model” of CLIPasso |
| **SigLIP B/16** weights `google/siglip-base-patch16-224` (experimental, not bundled – downloaded only on request; only the image part is stored, in float16; run with transformers) | https://github.com/google-research/big_vision – Google | Apache-2.0 | experimental “Semantic model” of CLIPasso |
| **BlazeFace** front-camera face detector (network written anew in `clipasso_studio/engine/portrait.py`; weights `blazeface.pth` in the PyTorch conversion by Matthijs Hollemans) | https://github.com/google/mediapipe – Google; conversion: https://github.com/hollance/BlazeFace-PyTorch | Apache-2.0 (both) | portrait mode of the detail brush |
| **LAION-Aesthetics Predictor V1** (the linear head for CLIP ViT-B/32, `sa_0_4_vit_b_32_linear.pth`, stored as `resources/aesthetic/laion_vit_b_32.npz`) | https://github.com/LAION-AI/aesthetic-predictor – LAION | MIT (see below) | “Best sketch: Similar & beautiful” |
| **VGG16** feature weights (torchvision) | https://github.com/pytorch/vision | BSD-3-Clause (code); ImageNet-trained weights | LPIPS perceptual loss |
| **SwiftSketch** and **ControlSketch** (method; `clipasso_studio/engine/methods/swiftsketch/` and `controlsketch/` are independent re-implementations written from the paper and the public code, which has no licence file) | https://github.com/swiftsketch/SwiftSketch – Ellie Arar, Yarden Frenkel, Daniel Cohen-Or, Ariel Shamir, Yael Vinker: *SwiftSketch: A Diffusion Model for Image-to-Vector Sketch Generation*, SIGGRAPH 2025 | method description (paper) | SwiftSketch / ControlSketch sketching |
| **SwiftSketch model weights** (not bundled – downloaded by the user from the authors' Google Drive on first use) | https://github.com/swiftsketch/SwiftSketch | no explicit licence – research / personal use | SwiftSketch diffusion + refinement networks |
| **SceneSketch / CLIPascene** (code ported to `clipasso_studio/engine/methods/scenesketch/`; sample images `resources/samples/ballerina.jpg` and `house.jpg` from the repository) | https://github.com/yael-vinker/SceneSketch – Yael Vinker, Yuval Alaluf, Daniel Cohen-Or, Ariel Shamir: *CLIPascene: Scene Sketching with Different Types and Levels of Abstraction*, ICCV 2023 | MIT (see below) | SceneSketch sketching, sample scenes |
| **LaMa** big-lama inpainting network (generator ported to `scenesketch/lama.py`; weights not bundled – the TorchScript export distributed by IOPaint is downloaded on first use and converted) | https://github.com/advimman/lama – Roman Suvorov et al. (Samsung AI); export: https://github.com/Sanster/IOPaint | Apache-2.0 | SceneSketch background |
| **Stable Diffusion v1.5** (not bundled – downloaded on first use) | https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5 – Runway, CompVis, Stability AI | CreativeML OpenRAIL-M (use restrictions apply) | ControlSketch SDS loss |
| **TAESD** Tiny AutoEncoder for Stable Diffusion `madebyollin/taesd` (not bundled – downloaded when the turbo mode of ControlSketch is used) | https://github.com/madebyollin/taesd – Ollin Boer Bohan | MIT | ControlSketch turbo mode (encodes the sketch instead of the SD VAE) |
| **ControlNet 1.0** models `lllyasviel/sd-controlnet-*` (not bundled) and the **HED** annotator (`ControlNetHED_Apache2` network in `controlsketch/conditions.py`, weights `lllyasviel/Annotators/ControlNetHED.pth`, not bundled) | https://github.com/lllyasviel/ControlNet – Lvmin Zhang | OpenRAIL (models), Apache-2.0 (HED annotator) | ControlSketch conditions |
| **MiDaS DPT-Hybrid** `Intel/dpt-hybrid-midas` (not bundled) | https://huggingface.co/Intel/dpt-hybrid-midas – Intel ISL | Apache-2.0 | depth / normal condition |
| **UperNet ConvNeXt-small** `openmmlab/upernet-convnext-small` (not bundled) | https://huggingface.co/openmmlab/upernet-convnext-small | MIT | segmentation condition |
| **BLIP** `Salesforce/blip-image-captioning-large` (not bundled) | https://huggingface.co/Salesforce/blip-image-captioning-large – Salesforce | BSD-3-Clause | automatic caption |
| **Stable Diffusion XL 1.0** (optional, not bundled) | https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0 – Stability AI | CreativeML OpenRAIL++-M | ControlSketch attention initialisation |
| **DDIM inversion** (algorithm of `controlsketch/sdxl_attention.py`, following Google's Apache-2.0 reference used by ControlSketch) | https://github.com/google/style-aligned | Apache-2.0 | SDXL attention initialisation |
| **diffusers**, **transformers**, **tokenizers**, **safetensors**, **huggingface_hub**, **accelerate** | https://github.com/huggingface | Apache-2.0 | loading and running the diffusion / vision models |
| **diffvg** (algorithmic reference; the renderer in `engine/renderer.py` is an independent PyTorch re-implementation of the parts used by CLIPasso) | https://github.com/BachiLi/diffvg – Tzu-Mao Li et al. | Apache-2.0 | differentiable rasterisation |
| **PyTorch / torchvision** | https://pytorch.org | BSD-3-Clause | deep learning runtime |
| **NVIDIA CUDA runtime libraries** (GPU edition only, shipped inside the PyTorch wheels) | https://developer.nvidia.com/cuda-toolkit | NVIDIA EULA (redistributable components) | GPU acceleration |
| **Qt for Python (PySide6)** / **Qt 6** | https://www.qt.io/qt-for-python | LGPL-3.0 | user interface |
| **Qt Multimedia** (from PySide6-Addons; only this module is bundled) with its **FFmpeg** libraries | https://www.qt.io/qt-for-python, https://ffmpeg.org | LGPL-3.0 (Qt), LGPL-2.1+ (FFmpeg) | webcam photos |
| **pi-heif** with **libheif** and **libde265** (decoders only) | https://github.com/bigcat88/pillow_heif, https://github.com/strukturag/libheif, https://github.com/strukturag/libde265 | BSD-3-Clause (pi-heif), LGPL-3.0 (libheif, libde265) | opening HEIC / HEIF photos |
| **NumPy**, **Pillow**, **ftfy**, **regex**, **imageio**, **imageio-ffmpeg** (FFmpeg binary: LGPL/GPL) | PyPI | BSD / HPND / Apache-2.0 / MIT | utilities, video export |
| **segno** | https://github.com/heuer/segno | BSD-3-Clause | the QR code of the phone remote |
| **Inter** font | https://rsms.me/inter/ | SIL Open Font License 1.1 (`resources/fonts/LICENSE-Inter-OFL.txt`) | UI font |
| **Lucide** icons | https://lucide.dev | ISC (`resources/icons/LICENSE-lucide.txt`) | UI icons |
| **Benchmark photos** in `benchmarks/images/` (portraits, animals, scenes; listed with their NASA ID, title, photographer and link in `benchmarks/images/SOURCES.md`) – only in the source repository, not in the app | https://images.nasa.gov – NASA (Johnson and Kennedy Space Center) | public domain (works of the US federal government; NASA's media guidelines ask not to imply an endorsement by NASA or the people shown) | quality benchmark (`tools/benchmark.py --suite`) |
| **CLIP ViT-L/14** weights (not bundled, not offered in the app – downloaded only by the benchmark) | https://github.com/openai/CLIP – OpenAI | MIT | the benchmark's independent judge (`tools/judge.py`) |

Models marked “not bundled” are not part of the download; the app fetches them from the listed
sources when the corresponding method or option is used for the first time, and their licences apply
to their use.

## Licence of CLIPasso Studio

Because it is derived from CLIPasso, CLIPasso Studio is distributed under the
**Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International** licence
(see `LICENSE`). **Commercial use is not permitted.**

The LGPL-licensed Qt libraries are dynamically linked. In the installed (onedir) edition they
are separate DLL files that can be replaced; the complete source code of this application is
available in its public repository.

## SceneSketch licence

```
MIT License

Copyright (c) 2023 yael-vinker

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## BiRefNet licence

```
MIT License

Copyright (c) 2024 ZhengPeng

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Swin Transformer licence (backbone of BiRefNet)

```
MIT License

Copyright (c) Microsoft Corporation.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE
```

## LAION-Aesthetics Predictor licence

```
MIT License

Copyright (c) 2022 LAION AI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
