# Third-party notices

CLIPasso Studio bundles or is derived from the following works.

| Component | Source | Licence | Used for |
|---|---|---|---|
| **CLIPasso** (code in `clipasso_studio/engine/painter.py`, `losses.py`, `pipeline.py`, `masking.py`) | https://github.com/yael-vinker/CLIPasso – Yael Vinker, Ehsan Pajouheshgar, Jessica Y. Bo, Roman Christian Bachmann, Amit Haim Bermano, Daniel Cohen-Or, Amir Zamir, Ariel Shamir | CC BY-NC-SA 4.0 | sketching method, optimisation loop, losses |
| **CLIP** (code in `clipasso_studio/engine/clip_/`, model weights RN101, ViT-B/32 and optional variants) | https://github.com/openai/CLIP – OpenAI | MIT | perceptual loss, saliency |
| **U²-Net** (code in `clipasso_studio/engine/u2net/`, weights `u2net.pth`) | https://github.com/xuebinqin/U-2-Net – Xuebin Qin et al. | Apache-2.0 | background mask |
| **DINO** (code in `clipasso_studio/engine/dino/`, weights ViT-S/8) | https://github.com/facebookresearch/dino – Meta AI | Apache-2.0 | alternative saliency |
| **VGG16** feature weights (torchvision) | https://github.com/pytorch/vision | BSD-3-Clause (code); ImageNet-trained weights | LPIPS perceptual loss |
| **diffvg** (algorithmic reference; the renderer in `engine/renderer.py` is an independent PyTorch re-implementation of the parts used by CLIPasso) | https://github.com/BachiLi/diffvg – Tzu-Mao Li et al. | Apache-2.0 | differentiable rasterisation |
| **PyTorch / torchvision** | https://pytorch.org | BSD-3-Clause | deep learning runtime |
| **NVIDIA CUDA runtime libraries** (GPU edition only, shipped inside the PyTorch wheels) | https://developer.nvidia.com/cuda-toolkit | NVIDIA EULA (redistributable components) | GPU acceleration |
| **Qt for Python (PySide6)** / **Qt 6** | https://www.qt.io/qt-for-python | LGPL-3.0 | user interface |
| **NumPy**, **Pillow**, **ftfy**, **regex**, **imageio**, **imageio-ffmpeg** (FFmpeg binary: LGPL/GPL) | PyPI | BSD / HPND / Apache-2.0 / MIT | utilities, video export |
| **Inter** font | https://rsms.me/inter/ | SIL Open Font License 1.1 (`resources/fonts/LICENSE-Inter-OFL.txt`) | UI font |
| **Lucide** icons | https://lucide.dev | ISC (`resources/icons/LICENSE-lucide.txt`) | UI icons |

## Licence of CLIPasso Studio

Because it is derived from CLIPasso, CLIPasso Studio is distributed under the
**Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International** licence
(see `LICENSE`). **Commercial use is not permitted.**

The LGPL-licensed Qt libraries are dynamically linked. In the installed (onedir) edition they
are separate DLL files that can be replaced; the complete source code of this application is
available in its public repository.
