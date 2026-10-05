## CLIPasso Studio 3.4 – better sketches

**Shape the result**
- **Saved steps as the result** (clock button above the canvas): slide through the steps a sketch saved while it was computed and take one as the result. *Undo* brings the final one back; the original stays.
- **Simplify** (slider button): the strokes that add the least go first. CLIP measures once per sketch (a few seconds) how far the likeness falls without each stroke; *Apply* keeps what you see (undo, the original stays).
- **Detail brush** (sparkle button next to the photo): paint where the sketch should get more detail (orange) and where less (blue). CLIPasso and ControlSketch put more starting strokes into the orange parts and draw the blue parts more loosely (the photo is softened there). The map belongs to the picture – in the queue, when continuing and in the job folder.
- **Portrait mode** (*Find face* in the detail brush): BlazeFace finds the face and marks the eyes, nose and mouth as “more detail”. It runs on this computer; the 0.4 MB model is included.

**Choose the best sketch**
- **Best sketch** (next to the number of sketches): *Most similar* – as before; *My taste* – rate sketches with thumbs up or down in the studio, and from 10 ratings on the app learns what you like (a small model on this computer, Settings → *My taste*); *Similar & beautiful (experimental)* – LAION’s aesthetic score counts as well. It was trained on photos: on sketches it reliably prefers clean lines over shaky ones, but it cannot tell a sketch from a scribble – so the look only ever decides among sketches at most 3 CLIP points behind the most similar one.
**Phone remote 2.0**
- **Pictures from anywhere:** *Take photo* opens the camera, *Choose picture* the gallery and files of the phone (before, only the camera opened); *From the PC* offers the recent pictures and the samples.
- **The studio on the phone:** method, presets, every parameter (with its help text, advanced ones on request), time budget, the detail brush (paint with your finger, *Find face*), start, add to queue, pause, cancel – questions such as “memory is short” are answered on the phone, never at the computer.
- **Watch and keep:** the live sketch with its numbers, all sketches of a job, thumbs up/down, brush style and paper, download as SVG or PNG; the recent results (open one to look at it again) and the queue.

- **Time budget** (input card): 5, 15 or 60 minutes or your own: the app picks iterations, number of sketches, turbo mode and augmentations so the job takes about that long on this computer – from the measured times.

**Small update**
- An app on 3.3.0 downloads only the files that changed (`…-Patch-from-3.3.0.exe` / `…-Portable-Patch-from-3.3.0.zip`). The program file now keeps its version number until its libraries change, so it no longer comes with every update (75 MB).

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
