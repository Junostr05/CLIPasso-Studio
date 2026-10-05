## CLIPasso Studio 3.3 – looks, sharing and order

**Looks**
- **Six new brush styles:** charcoal, chalk, ballpoint pen, watercolour, neon and calligraphy (a broad nib) – next to plain, ink, pencil and marker. In the live preview (palette button of the studio) and in every export. Plain SVG geometry, so browsers, PDF readers and the app show the same picture.
- **Paper & background:** drawing paper, watercolour paper, kraft paper, linen and a blackboard – textures the app makes itself – in any colour, with a vignette. In the preview and in PNG, PDF, GIF, MP4, WebP and SVG; on a dark paper black strokes become light.

**Sharing**
- **Print layout** (studio, gallery selection, albums): A5, A4, A3, US Letter or a 50 × 70 cm poster, portrait or landscape, margins, one sketch per page or a contact sheet of up to 20, a title, a signature and names under the sketches – as a multi-page PDF or straight to the printer, with a preview.
- **Lottie** (`.json`): the sketch drawing itself stroke by stroke for websites, apps and After Effects (lottie-web, LottieFiles); one layer per stroke, the background or paper below.
- **Web page** (`.html`): one file in which the sketch draws itself, in its brush style and on its paper, with a button to draw it again – to send or upload.
- **Phone remote (Wi-Fi):** Settings → *Phone & messages*: scan the QR code and see the status and a live preview on the phone, pause or cancel, or take a photo that is sketched right away. Only from the home network and only with the access code; off by default.
- **Telegram message:** your own bot sends the finished sketch with its name, method and duration (or the error) to your phone. Only the Telegram Bot API; the token stays on this computer.

**Order**
- **Albums** in the gallery: create them, drag sketches onto them or use the right-click menu, show one album, rename it, export or print it. A sketch knows its albums (in its own folder), so they move with it.
- **Backup & move** (Settings → System): the settings, the queue with its pictures, the gallery – and the models, if wanted – in one `.clipbackup` file, and back on this or a new computer: the folders of the new computer stay, results already there are skipped, nothing is overwritten. Tokens and access codes are never in a backup.

**Small update**
- An app on 3.2.1 downloads only the files that changed (`…-Patch-from-3.2.1.exe` / `…-Portable-Patch-from-3.2.1.zip`).

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
