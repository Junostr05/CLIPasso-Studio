## New in 3.1: older graphics cards

- **GTX 9xx / 10xx on the graphics card:** NVIDIA cards older than the GTX 16xx (e.g. GTX 1060, GTX 970) now compute on the graphics card instead of the processor. The app detects such a card by itself and offers an add-on: PyTorch with CUDA 12.6, 2.6 GB download. Newer cards do not need it.
- **Settings → System:** download, switch on and off or remove the add-on, and the *graphics card precision* (fp16, or always fp32 to compare).

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
