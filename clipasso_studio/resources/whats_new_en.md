## New in 3.3: looks, sharing, order

- **Six new brush styles:** charcoal, chalk, ballpoint pen, watercolour, neon and calligraphy – in the live preview (palette button of the studio) and in every export.
- **Paper & background:** drawing paper, watercolour paper, kraft paper, linen and a blackboard, in any colour and with a vignette – in the preview and in every export. On a dark paper black strokes become light.
- **Print & print layout:** A5 up to a poster, margins, one sketch per page or a contact sheet, a title, a signature and names – as a PDF or straight to the printer.
- **Lottie & web page:** the sketch draws itself – as a Lottie file for websites and apps or as a little web page of its own.
- **Phone remote (Wi-Fi):** scan the QR code, see the progress and the preview, pause, send photos (Settings → *Phone & messages*).
- **Telegram message:** your own bot sends you the finished sketch on your phone.
- **Albums** in the gallery: drag sketches onto an album, show, export and print albums.
- **Backup & move:** save everything in one file and put it back on a new computer (Settings → System).

---

**New in 3.2: steadier, faster, smaller updates**

- **3.2.1 – SceneSketch on the graphics card:** scenes with an object stopped on the graphics card at the end of the first cell (“Expected all tensors to be on the same device”). Fixed – found with the new self-test. This is the first small update: it downloads only the files that changed.
- **Small updates:** from the next update on, the app downloads only the files that changed – usually megabytes instead of 1 GB (CPU) or 3.5 GB (GPU). When PyTorch changes, the whole package comes as before.
- **Self-test:** Settings → System → *Self-test* checks every method, continuing, the background removal and loading the models in a few minutes.
- **Report a problem:** on an error (and in the settings) *Report a problem …* prepares a report for GitHub – with the diagnostics, paths with your name shortened, and you see and can change everything first.
- **Memory guard:** before the start the app checks whether the RAM and the graphics memory are enough, and otherwise suggests smaller settings – instead of failing after minutes.
- **SDXL piece by piece on the graphics card:** on cards below 8 GB ControlSketch's SDXL attention now computes piece by piece on the graphics card (the pieces wait in the RAM) – much faster than on the processor. Progress in the status line; the measured time goes into the estimate.
- **Several graphics cards:** the sketches of a job are spread over all cards (CLIPasso, SwiftSketch, ControlSketch).

---

**New in 3.1: older graphics cards**

- **GTX 9xx / 10xx on the graphics card:** NVIDIA cards older than the GTX 16xx (e.g. GTX 1060, GTX 970) now compute on the graphics card instead of the processor. The app detects such a card by itself and offers an add-on: PyTorch with CUDA 12.6, 2.6 GB download. Newer cards do not need it.
- **Settings → System:** download, switch on and off or remove the add-on, and the switch *Always compute in fp32* (default: fp16, half the graphics memory).
- **SDXL on cards below 8 GB:** when you choose the SDXL attention for ControlSketch, the app asks whether this one step computes on the processor (with all its cores, progress in the status line, pause and cancel work) or CLIP is used – remembered if you like, changeable under Settings → System. Everything after it computes on the graphics card again; if the graphics memory runs out on a bigger card too, SDXL moves to the processor by itself.

---

**New in 3.0**

## Draw, continue, one line

- **Brush style live:** ink, pencil or marker right in the preview – also while the sketch is being made (palette in the bar above the sketch).
- **Draw yourself and continue:** add your own strokes with the pen, then *Continue with CLIPasso* – your strokes stay fixed, CLIPasso adds the rest.
- **One line:** CLIPasso draws the subject in one single continuous stroke (setting *One line* under strokes).
- **Turbo mode:** faster, with a slightly different result. It only finishes the best sketch and stops once it no longer improves; for ControlSketch it uses a small image decoder (TAESD).

## Faster

- **New stroke rasterizer:** a render step of CLIPasso takes 47–62 instead of 68–152 ms, one long single line 40 instead of 4059 ms (measured on a CPU). Same algorithm and same quality; the results are not bit-identical to 2.4, though.
- **Models stay loaded:** in the queue the next job starts without a loading pause.
- **Several sketches at the same time** on big processors (CLIPasso, SwiftSketch).
- Faster start; the window stays usable while exporting.

## Formats and inputs

- **Free aspect ratio:** export in the shape of the photo or cropped to the content – for SVG, PNG, PDF, animations and *Export all*.
- **More image formats:** HEIC/HEIF (iPhone), AVIF, TIFF, BMP and GIF; photos are turned upright by their EXIF rotation.
- **Webcam:** take a photo right in the app.
- **Recent:** open your last images again with one click.

## Gallery, queue, watched folder

- **Gallery 2.0:** fast even with thousands of sketches, multi-select (delete, export, favourite), titles, notes and tags, sorting by score, duration, strokes and name, keyboard control.
- **Queue:** reorder by dragging; pause, cancel and retry per row; details with *Load into the studio*; total time left. Failed jobs stay after a restart.
- **Watched folder:** images you put into a folder are sketched and exported by themselves (Settings).

## More reliable

- **Graphics memory full?** The app offers to continue on the CPU or with smaller settings – finished sketches are kept.
- **Copy / save diagnostics** (Settings → System): everything a bug report needs in one text.
- **Storage** (Settings): see and clear caches and old updates. When you change the output folder, your results can move along.
- Downloads check the free space first and continue after an interruption, also from another server.
- **Portable as ZIP:** starts faster than the single exe and updates itself.
