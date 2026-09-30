## CLIPasso Studio 2.2 – no more freezes, a better gallery and export

**Fixed: the app froze and crashed at the end of an export or a model download.** The file was complete, the progress bar full – and then the app hung and closed. Two bugs in the background work were behind it (the finished work was handed back to the interface from the wrong thread, and cleaning up after one export could crash the next one); both are fixed. The last step is now visible as well: “Encoding the GIF …” / “Checking and preparing …” instead of a full bar that seems stuck, and *Cancel* works during exports and downloads.

**Gallery**
- Click a result to **continue working on it** in the studio – with its image and all settings. Every job now keeps a copy of its input image, so this also works after the original file was moved or deleted.
- **Delete** results (to the recycle bin), **Show folder**, **favourites** (★) with a favourites filter, sorting by date or best CLIP score, search by image name and method. Right-click a card for the same actions.

**Export**
- GIF, MP4 and the new **animated WebP**: set **how long the drawing takes** (and how long the finished sketch stays) – the frame rate adapts.
- **GIFs about 2× smaller and 3× faster** to create (a small palette made for line drawings).
- **Animated WebP**: smaller than GIF, with a transparent background if you like.
- SceneSketch: **export the whole matrix** as one ZIP – every sketch as SVG and PNG plus an overview sheet.

**Also new**
- **Keyboard shortcuts**: Ctrl+V pastes an image from the clipboard, Ctrl+O opens one, Ctrl+Enter starts, Ctrl+Shift+Enter adds to the queue, Ctrl+E exports the SVG, Ctrl+1 … 7 switch pages (list on the About page).
- **Interrupted model downloads continue** where they stopped (also after closing the app); a dropped connection is resumed automatically.
- **Update notice** when a new version is available (Settings → switch off).
- **Crash log**: an unexpected error is shown and saved to a log file (Settings → *Open log folder*); after a hard crash the next start tells you where the log is. Please attach it when you report a problem.

| File | For whom? |
|---|---|
| **`CLIPassoStudio-CPU-Portable.exe`** | Just download and run – no installation. Works on any 64-bit Windows 10/11 PC. Starting takes about 15–40 s (unpacking). |
| **`CLIPassoStudio-CPU-Setup.exe`** | The same app as an installer (faster start, Start menu entry). |
| **`CLIPassoStudio-GPU-Setup.exe`** + **all `CLIPassoStudio-GPU-Setup-*.bin`** | NVIDIA GPU edition (CUDA 12.8: GeForce GTX 16xx / RTX 20xx or newer, driver ≥ 570): CLIPasso and SceneSketch 10–50× faster, ControlSketch in minutes instead of hours. **Download all files into the same folder**, then run `CLIPassoStudio-GPU-Setup.exe`. |

**Notes**
- Windows SmartScreen may warn on the first start (“Unknown publisher”) → *More info* → *Run anyway*.
- CPU times: SwiftSketch ~5 s per sketch; CLIPasso “Fast” 5–15 min; SceneSketch “Fast” ≈ 20 min, “Standard” ≈ 2 h; ControlSketch several hours (GPU: a few minutes).
- Updating: the installer versions install over the old version; downloaded models and settings are kept.
- Licence: CC BY-NC-SA 4.0 – **non-commercial use only**. The downloaded models have their own licences (see THIRD_PARTY_NOTICES.md).
- Checksums: `SHA256SUMS-CPU.txt` and `SHA256SUMS-GPU.txt`.
