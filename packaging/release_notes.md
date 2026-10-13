## CLIPasso Studio 4.2.4 – the phone over Tailscale by default

A small update from 4.2.3 – and from 4.2.2 and 3.8.1, too (also from the phone).

- **Tailscale is the default:** *Also over Tailscale* (the phone remote also lets in the devices of your tailnet,
  100.64.0.0/10) is on for new installations – and switched on once by this update (the settings file kept the old
  default "off" like a choice; switch it off again under *Phone* if you do not want it).
- **The Tailscale address first:** when Tailscale runs on this PC, the phone card's QR code and fixed address are
  the tailnet's; *Wi-Fi* next to it gives the home network's address.
- Signing in stays as it was: the access code of the QR code, or the PIN (five wrong tries from one address, then it
  has to wait).

## CLIPasso Studio 4.2.3 – select several results on the phone

A small update from 4.2.2 – and from 3.8.1, too (also from the phone).

- **Select in the phone's gallery:** *Select* next to the number of results turns a tap on a result into a tick
  (instead of opening it); *Select all* / *Select none*, and *Done* ends it. While selecting, the star and the bin of
  each result step aside. The keyboard works, too (Space or Enter on a result), and screen readers hear each result
  as a check box.
- **Into an album at once:** the bar below the results puts every selected result *Into an album …* – an existing
  one or a new one (*+ New album …*).
- **A slideshow of just them:** *Slideshow* in the same bar shows only the selected results, one after another
  (3 s each; *1 of 2* counts them); swiping stays among them, too.
- **Slideshows go round:** after the last result the slideshow starts again from the first one – the one of the
  selected results and the one of all shown results (it used to stop at the end).

## CLIPasso Studio 4.2.2 – the mouse wheel only scrolls

A small update from 4.2.1 – and, new, from 3.8.1, too (also from the phone).

- **The wheel scrolls the page, never a value:** over a slider, a number field or a drop-down the mouse wheel used to
  change it – scrolling down the parameters changed every slider on the way. Now the wheel scrolls the column around
  it (with nothing to scroll it does nothing); click or drag to change a value, or use the keyboard.
- **The time budget is gone** – the *5 / 15 / 60 min* menu in step 3 and its row on the phone.
- **A small update from 3.8.1:** who skipped the 4.x releases does not download the whole app again.

## CLIPasso Studio 4.2.1 – the left column can be drawn wider, the sketch has its tab again

A small update from 4.2.0 (also from the phone).

- **The phone: the sketch is a tab of its own again** – *Studio · Sketch · Gallery · Queue · App*. In 4.2.0 it sat
  at the top of the studio tab, which made the studio crowded on a phone. On a computer or a tablet held across it
  stays the studio's middle column.
- **A handle at the studio's left column:** three dots between the column and the sketch; under the mouse a line in
  the accent colour and the split cursor. Drag it to make the column wider (up to 560 px) or narrower – the app keeps
  the width for the next start. A double click on the handle gives the column its own width back.
- **Nothing cut off any more:** the column is never narrower than its content needs on this computer (the language
  and the fonts of Windows count). Before, it was 312 px whatever was in it – the parameter page under *Adjust*
  needed 315 px, and with slightly wider fonts the steps ran out on the right, too.
- **Step 1 in its order:** the image and its mask, then *Change …* with crop and the detail brush, then the switches
  *Remove background*, *Keep aspect ratio* and *Turbo mode* (they were in step 3), then the hints and the image's
  earlier sketches (they used to sit between the image and *Change …*). The guide scrolls the left column to the
  part it shows.

## CLIPasso Studio 4.2 – the phone in the style of 4.0

From 4.1 the app offers 4.2 as a small update (also from the phone). The phone page is renewed like the studio was
in 4.0 – every function stays.

- **One source for the colours:** the page takes its colours and corners from the app's design tokens (served as
  `/tokens.css`) – dark and light the same as the studio's, with the same measured contrasts (text at least 4.5 : 1,
  the edges of text fields and the focus ring at least 3 : 1); it has no colours of its own any more (a test keeps
  it so). The font is the studio's Inter (served by the app, cached for a week), the icons are the studio's Lucide
  icons. A visible focus ring shows where the keyboard is.
- **Four tabs** – *Studio · Gallery · Queue · App*, with icons. The sketch tab is gone: the sketch is the top of the
  studio as soon as a job draws there or a result is opened (its views, editing, rating, look and export).
- **On a computer or a tablet held across** the page is laid out like the 4.0 studio: a header with the areas, the
  steps on the left (image, method, preset, detail brush, parameters, compare), the sketch in the middle (look and
  export below it), the job's sketches on the right, and a footer with the job's status, *Create sketch*, *To
  queue*, *Pause* and *Cancel*.

## CLIPasso Studio 4.1 – Simplify keeps the shape

From 4.0 the app offers 4.1 as a small update (also from the phone).

- **Outlines before areas.** *Simplify* (the slider in the toolbar below the sketch) used to drop the strokes by
  CLIP alone – how far the likeness falls without each one. That often kept the strokes that fill a dark area and
  let the outline go, and the sketch lost its shape. Now three things decide for every stroke: its rank by CLIP,
  how much of it lies on an edge of the picture and runs along it (strongly preferred – it weighs one and a half
  times CLIP's whole range), and how much of it lies in a dark area that other strokes cover too (goes first). The
  crowding is counted again after every stroke that goes, so an area thins out evenly instead of being emptied.
- A sketch measured by 4.0 or earlier is measured again the first time you simplify it (a few seconds, once).
- The same order on the phone, when a sketch is edited there.

## CLIPasso Studio 4.0 – a calmer studio

4.0 renews the whole studio: a new look in dark and light, a clearer order from the image to the export, and
the keyboard everywhere. Every feature of 3.8 stays – a test walks through all of them. From 3.8.1 the app offers
4.0 as a small update (*Settings → Behaviour*, also from the phone).

- **A header instead of the sidebar:** the areas *Studio · Gallery · Queue* (the queue with the number of waiting
  jobs), the running job's progress (a click shows it in the studio), the hardware the app computes on, and the
  **App** menu: *Models, Settings, Compare methods, Phone & messages, Check for updates, About & help*.
  **Ctrl+1 … 7 in the order you see:** Studio, Gallery, Queue, Models, Settings, Compare, About (3.8: Studio,
  Compare, Queue, Gallery, …).
- **The studio in three columns.** *Left – three numbered steps:* *1 · Image* (the preview with name, size and
  mask; *Change …* opens an image, its arrow the samples, recent images, the webcam and the clipboard; crop and the
  detail brush next to it), *2 · Method* (the four method cards one below the other, *Compare …*) and
  *3 · Preset* (*Fast / Standard / Quality*, your own presets and what the job will draw: “16 strokes · 2001
  iterations · 3 sketches”); **Adjust** shows every parameter in the column, *Back* or Esc returns.
  *Middle – the sketch:* the views at the top, the job's ⋯ menu (its folder, use as a start, abstraction series,
  copy, print) and a floating toolbar below the sketch (eraser, pen, undo, redo, the original, saved steps,
  time-lapse, *Simplify*, continue with CLIPasso, rating, full screen). *Right – the job's sketches*, each with its
  state and CLIP score; the arrow keys choose. *Bottom – the job:* status, estimate or time left, *Details* (the
  numbers and the loss curve, remembered), *Create sketch* and *To queue*; while it runs *Pause* and *Cancel*.
- **Export …:** one dialog with every format in groups (*Image, Animation, Share*), the sketch and the options of
  the format; Ctrl+E opens it on the format used last.
- **Gallery:** a column on the left with the search, the methods, *Favourites*, the albums with their number of
  results (drop results on an album to add them) and the tags; below the title how many results there are – and
  how many are shown. Mark several and a bar floats at the bottom: *View large, Compare* (two), *Favourite,
  Export, Delete*.
- **Settings:** their parts on the left (*Appearance, Files, Behaviour, Watched folder, Phone & messages, Storage,
  System, Experimental*); a click scrolls there, and the column shows where you are.
- **Keyboard:** a visible focus ring (2 px in the focus colour) around the control the keyboard is on – while the
  keyboard is used, gone after a click. The method cards, every segmented choice and a job's sketches are one Tab
  stop each (arrows, Home, End, Space, Enter); the image area is reached by Tab. Tab runs from the header through
  the studio – left, middle, right, footer – and round to the header again.
- **The 4.0 colours** (direction “calm professional tool”): dark and light from one set of design tokens. Every
  text reaches at least 4.5 : 1 on its surfaces, the edges of text fields, tick boxes and switches and the focus
  colour at least 3 : 1 (in 3.8: 1.1–1.4 : 1). Corners and spacing follow one scale; every dialog has the same
  margins (24 / 16 px).
- **The same words everywhere:** *image*, *job*, *preset* – in German *Bild*, *Auftrag*, *Voreinstellung* – and
  numbers in German with a decimal comma (CLIP 29,4, 1,2 GB).
- **Beta versions:** the switch *Also offer beta versions* (Settings → Behaviour; on the phone under *App*) offers
  pre-releases as updates; off (the default), the app offers finished versions only. Betas are for Windows only.
- **Downloads:** every release page starts with *Which file do I need?* The portable single exe is gone – if you
  used it, download the portable ZIP once (it starts faster and updates itself).
- Fixed on the way: a “&” in a menu or a button is shown again; resetting the studio's view could fail after a
  while; the app could crash when a dialog closed while one of its buttons had the keyboard focus.

The betas 4.0.0b1 … b5 brought these parts one by one; their pages keep their notes.

## CLIPasso Studio 3.8.1 – fixes: the experimental sketch improvement, older graphics cards

- **Experimental sketch improvement:** switched on (Settings, at the bottom), a CLIPasso or SceneSketch job ended at once with “No module named 'scipy'” – its edge and hatching maps used a library the app does not include. The app computes them itself now (the same maps); a new test makes sure the app imports nothing its build leaves out.
- **“FIND was unable to find an engine to execute this computation”** (seen on a GTX 1060): when cuDNN finds no way to run a convolution – typically when the graphics memory is nearly full while it tries its algorithms – the job no longer ends. It goes on with a simpler way: first without cuDNN's search for the fastest algorithm, then, if needed, without cuDNN (a little slower). Finished sketches are kept, the others continue from their checkpoints, and a note in the studio says so.
- From the review for 4.0: nothing in the studio's centre is cut off in a small window any more (status line, buttons, numbers, earlier jobs); the text colours of the studio and the phone page meet the WCAG AA contrast (hints on the paper, the red button under the mouse, the dark phone page); on the phone, screen readers hear which tab and which option is chosen, and every slider and help button has a name.
- **Small update:** an app on 3.8.0 downloads only the files that changed (`…-Patch-from-3.8.0.exe` / `…-Portable-Patch-from-3.8.0.zip`).

## CLIPasso Studio 3.8 – the phone remote: almost the whole studio

**Update from the phone**
- The new *App* area of the phone page: *Check for updates*, what is new in it, and *Download & install*. After the 6-digit PIN once more, the app downloads and checks the update, stops a running job, installs, starts again – and goes on with the job and the queue where they were. The page shows the progress, waits while the app restarts, connects again by itself and loads the new version's page.
- When an update cannot be installed, the app still comes back (with the version that is there) and the phone says so.
- An installation for all users of the PC needs an administrator on the PC: from the phone the update is then only downloaded, and the PC's update bar installs it with one click.

**The studio on a computer or a tablet**
- On a wide screen held across (from about 1024 px), the page looks almost like the studio on the PC: the areas in a bar on the left, the studio in three columns – the picture and the result on the left, the method and the large sketch in the middle, presets and parameters on the right. Keys: Space pauses / goes on, ←/→ the previous / next sketch, F full screen, Ctrl+Z / Ctrl+Y undo and redo edits.
- *App → View*: automatic, phone or studio – kept by the browser.

**Editing the sketch on the phone** (as in the studio on the PC)
- Eraser (swipe over strokes), pen (strokes of your own that stay when CLIPasso continues), undo, redo, back to the original, and *Continue with CLIPasso*.
- *Simplify* with its slider, the saved steps (one of them as the result) and the time lapse at 0.5–4×.
- SceneSketch: compute one cell of the matrix again.

**Views and the picture**
- The views of a job: photo and sketch with a divider, the attention map, the mask, the condition (ControlSketch), and *All* – every sketch of the job side by side, one of them chosen as the result.
- The earlier jobs of the same photo, the hints about the photo (with *Crop* / *Check mask* and *don't show again*), and touching up the mask: tap a part to remove it (or add it), paint, magic wand – the same steps as the PC's mask editor.
- The paper's colour and vignette.

**Gallery and queue**
- Gallery: sort, filter by tag, title, tags and notes, albums (new, add, remove, rename, delete), two results compared with a divider, a slideshow, and *Continue* for an interrupted job.
- Queue: start the next job by itself or not, what the PC does when the queue is done, the time left, the settings a job changed, *Load into the studio* and *Run next*.

**Models and the app's settings**
- *App → Models*: every model by group with its size and what it is for – download it or delete it – and the models the studio's settings choose, by task, changed from there.
- Some of the app's settings: language, the experimental sketch improvement, the update check, keep awake, keep models loaded, notifications. Folders, backups, the phone's access and Telegram stay with the PC. The page's own colours: as the browser, as the app, light or dark.

**Behind the scenes**
- After an update from within the app, the installer starts the app again as the user who ran it – also when the update was refused; checked on Windows in the CI.
- ControlSketch in turbo mode on a CPU with bfloat16 (AVX512-BF16 / AMX): before the first sketch, the app runs the layers once in bfloat16 in a process of its own. Where that ends with an illegal instruction – seen on a Windows machine in the CI – the sketch is drawn in float32 instead of the job failing.
- New browser tests: the studio layout at 1440×900 and on a tablet, drawing on the sketch, and connecting again after a restart with a new version.

**Small update**
- An app on 3.7.0 downloads only the files that changed (`…-Patch-from-3.7.0.exe` / `…-Portable-Patch-from-3.7.0.zip`).

## CLIPasso Studio 3.7 – models and quality

**The studio's models in view**
- **On the Models page**, a card at the top shows the models the studio's current settings use, sorted by task: mask, shape (CLIP layers), meaning, starting points, condition (ControlNet), scoring. Changing one there changes the setting in the studio – and a change in the studio shows there at once. In the list, a badge *in the studio* marks those models.

**SceneSketch**
- **The object's own number of strokes** (*Object strokes*, 0 = the same as the background): more detail in the object without making the background denser – or fewer for a plainer object.
- **Computed levels:** compute only the simplicity levels you want – e.g. 4 and 8 instead of 1 to 8, which saves much time. Each chosen level starts from the chosen one before it.
- **Compute one cell again:** right click on a cell of the matrix → *Compute this cell again*, with a new start. The later levels of its layer build on it and are computed again; the job goes back into the queue.

**Simplify, easier to find**
- The *Simplify* button above the sketch now shows its name, and after the first finished sketch a hint says once where it is.

**Experimental sketch improvement** (Settings → *Experimental*, at the very bottom)
- CLIPasso and SceneSketch: the strokes follow the edges of the photo more closely, and dark areas get extra fine, straight strokes at 45° – an even hatching. The set number of strokes stays for edges and shape; the hatching comes on top.
- It applies to newly started jobs (continuing keeps a job's setting); a badge in the studio shows when it is on. Measured (below): neither a gain nor a loss in likeness that the measurement can tell apart – so it stays experimental and off by default.

**Measured, not guessed**
- New: quality is measured with an **independent judge** – CLIP ViT-L/14, a model the sketches are not optimised with. It grades the likeness to the photo and whether the subject is still recognised (zero-shot). The test set has 15 photos in four categories (objects, portraits, animals, scenes; NASA pictures in the public domain), each drawn with two seeds. Every change is measured against the defaults, in parallel in the CI; only a clear gain counts.
- What it decided for 3.7 (CLIPasso, 16 strokes, 301 steps):
  - **Face crops for portraits** (planned): recognisability −23 points (± 9). Not in 3.7.
  - **Learnt stroke widths** (planned): no clear difference (likeness +0.9 ± 0.8). Not in 3.7.
  - **A stroke count recommended from the photo's details** (planned): the measurement showed that more strokes help in every category, most of all with plain objects (8 → 16 strokes: likeness +8.7; 16 → 32: +4.4). The idea "few details, few strokes" does not hold – so there is no recommendation; more strokes are the better choice when there is time.
  - **Newer semantic models for CLIPasso** (*Semantic model*, experimental): **OpenCLIP ViT-B/16** made the sketches more similar and easier to recognise – likeness +2.0 (± 0.6), recognisability +12.6 points (± 4.9); clearly better for objects, portraits and animals, no clear difference for scenes. **SigLIP B/16** helped only animals (likeness +3.9, recognisability +26) and made no clear difference elsewhere. Both stay optional and marked *experimental* on the Models page (with what they were measured to help), are downloaded only on request (172 / 186 MB, only their image part) and take about 1.7 times as long; the default stays the original CLIP.

**Small update**
- An app on 3.6.0 downloads only the files that changed (`…-Patch-from-3.6.0.exe` / `…-Portable-Patch-from-3.6.0.zip`).

## CLIPasso Studio 3.6 – the studio on the PC

**Seeing the sketch**
- **Full screen / focus mode:** a new button above the canvas (or F11) hides the navigation, the input and the parameters – the canvas and its tools stay. Esc or the button end it.
- **Time lapse:** ▶ next to the step slider plays the saved steps of the sketch on the canvas as an animation (0.5×, 1×, 2× or 4× – in the button's menu), ending on the result.
- **Contact sheet:** the new canvas view *All* shows every sketch of a job (every seed) as large as the canvas allows, with its score; a click selects one, a double click opens it, right click → *Choose as the best* (the gallery, exports and the phone then use it).
- **History per photo:** a strip below the input picture with every earlier job of the same photo – any method, also jobs whose photo was moved (they keep a copy) – a click opens one.

**Gallery**
- **Large view:** Space, the context menu or *View large* opens a result as large as the window: ←/→ (or Page up/down) to browse, the mouse wheel zooms around the cursor, drag to move, double click or 0 to fit; *Open in the studio*.
- **Slideshow** (2–10 s per result) – also with the new *Slideshow* button in the gallery's header.
- **Compare two results:** mark two and click *Compare* – both on top of each other with a divider to drag (Shift+←/→ moves it step by step), zoom included.

**Before the run**
- **Hints about the photo:** measured in the background as soon as a photo is chosen – too small (below 224 px), too dark, too little contrast, blurred; and with the object mask: a very small object (*Crop*), no object found or an unsure mask (*Check mask*). The limits were set on the sample pictures and real photos so good photos get no hint. Each kind can be switched off (*don't show again*) and switched on again in Settings → Behaviour.

**Working on**
- **Nothing blocks any more:** moving the output folder or the model folder and unpacking an update (portable editions) run in the background with a progress strip at the top of the window instead of a window that blocks the app. Only what needs those files waits: a job started meanwhile waits in the queue and starts when the move is done; the gallery (and the phone's gallery) waits while the results move, model downloads while the models move. Closing the app waits for the move; an unpacked update asks *Restart now?* – or starts when the app closes.
- **Progress on the taskbar button** (Windows): green while a job runs, yellow when paused, red when it failed (until you look at the window again), and the background work above.

**Polish & accessibility**
- **Contrast:** every text colour of both themes now meets WCAG AA (4.5:1) on every surface it is shown on – captions, badges, links, warnings; checked by a test.
- **Screen readers:** every button without text (switches, icon buttons) has a name – the label of its row, which follows the language; checked by a test for every page and method.
- **Empty pages** (gallery, queue, compare) say what to do next and have a button for it; a search that finds nothing offers *Show all*.
- **Smaller windows:** the studio's three columns no longer overlap below about 1300 px – rows of buttons go to a second line; the smallest window is 1200 px wide (less on small screens).
- The same spacing on every page (theme tokens); Tab goes through the studio from left to right.

**Small update**
- An app on 3.5.0 downloads only the files that changed (`…-Patch-from-3.5.0.exe` / `…-Portable-Patch-from-3.5.0.zip`).

## CLIPasso Studio 3.5 – the phone as a second studio

**Live**
- **Up to date at once:** the phone page hears of every change on the PC as it happens (server-sent events) instead of asking every few seconds – the live sketch follows more smoothly and the phone's battery lasts longer. Where the connection blocks this, the page falls back to asking by itself.

**SceneSketch on the phone – and its layers**
- The *Sketch* tab has three views for a SceneSketch job: *Sketch*, *Background* – the background SceneSketch filled in behind the object (LaMa), there from the start of the job – and the whole *Matrix* (fidelity layers × simplicity levels, the best cell framed green; tap a cell to see it large). A line tells what is being drawn: the background or the object.
- A finished cell shows **whole, background only or object only** – on the phone below the sketch, on the PC with the new layers button above the canvas.
- New export **“SVG · separate layers”**: the cell with its background and its object as two layers that Inkscape and Illustrator open as layers (e.g. to recolour or hide only the background) – in the export dialog, as a button for SceneSketch in the studio, and on the phone.
- On the PC the matrix names its axes (fidelity, simplicity), and a reopened SceneSketch job shows its attention map again.

**Gallery, queue and compare on the phone**
- **Gallery:** every result instead of only the last 40 (*Load more*), search by name, note and tag, filters by method, album and favourite, set the star, and a large view to swipe through, zoom with two fingers and open in the studio.
- **Queue:** drag waiting jobs by their handle, pause or cancel the running job, start a failed or cancelled one *Again*, and put **several photos at once** into the queue (with the studio's settings).
- **Compare methods** (card in the studio tab): the studio's picture with several methods, standard preset or the studio's settings – the results side by side with score, time and strokes, the most similar starred; the questions the PC asks (a GPU missing) are asked on the phone.
- **Download models** that are missing, with progress (the method card, or when comparing).
- **Crop and turn** the photo (drag the corners, turn, mirror – saved as a new picture, as on the PC) and **look at the mask** the job will use.
- **Gestures:** swipe between the sketches of a job, zoom with two fingers, double tap to go back, pull down to refresh.

**Behind the scenes**
- The phone page is tested in a real browser (Chromium, phone size) with every build: signing in, exports, presets, the SceneSketch views, gallery, queue, compare and crop.
- The queue on the phone no longer rebuilds its rows while a job runs (only the bars move) – a tap on a button could get lost before.

**Small update**
- An app on 3.4.2 downloads only the files that changed (`…-Patch-from-3.4.2.exe` / `…-Portable-Patch-from-3.4.2.zip`).

## CLIPasso Studio 3.4.2 – export from the phone, own presets, a fixed address with a PIN

- **Every export on the phone:** the *Sketch* tab has an *Export* card with all formats of the app's export dialog – PNG, SVG, SVG · 1 layer, PDF, GIF, MP4, WebP, animated SVG, Lottie, web page (and the matrix ZIP for SceneSketch) – each with its settings: stroke colour and width, brush style, background colour or **No background (transparent)** where the format allows it, paper and vignette, frame and margin, size, PDF width, drawing process or stroke by stroke, length and pause. The phone shows the progress (and can cancel); then *Download* saves the file on the phone. The choices are the same as in the dialog on the PC – both remember them.
- **My presets – made on the PC or on the phone:** keep your settings under a name. In the studio: the bookmark button next to the presets (*Save the current settings …*, choose, delete). On the phone: set the method and the parameters, type a name in the *Preset* card and tap *Save* (or *Save as own preset …* below the parameters); choosing one fills in its name, so changing something and saving again updates it (after asking). Either way the preset is there on the other one at once; one of another method switches to it. Files of the computer (a start SVG) are not part of a preset.
- **A fixed address with a PIN:** Settings → *Phone & messages* shows the page's fixed address – keep it as a bookmark or on the home screen (*Add to Home Screen*). The sign-in now lasts about a year instead of ending when the browser forgets it; when the phone has forgotten it anyway (or after *New access code*), the page asks for a **6-digit PIN** instead of the QR code. The PIN is shown in the settings and can be changed; wrong PINs make the page wait longer and longer. Over Tailscale the address is the same at home and away; in the home network it can change when the router gives the PC a new one.
- An animation of the drawing process needs at least two saved steps – with only one, the export offers stroke by stroke (it made a still picture before).
- **Small update:** an app on 3.4.1 downloads only the files that changed (`…-Patch-from-3.4.1.exe` / `…-Portable-Patch-from-3.4.1.zip`).

## CLIPasso Studio 3.4.1 – phone remote: back to the running job, clean up, delete, Tailscale

- **Back to the running job:** when a result of the gallery is open on the phone while a job runs, a button at the top (with the job's name and progress) leads back to it.
- **Clean up the queue:** *Remove finished* on the phone takes the finished, cancelled and failed jobs out of the queue.
- **Delete from the gallery:** the bin on a result in the phone's gallery moves it to the PC's recycle bin (after asking; a job the queue still works on stays).
- **Over Tailscale:** Settings → *Phone & messages* → *Also over Tailscale* lets in the devices of your tailnet (their 100.x addresses were refused as “not the home network”) and shows a QR code with the PC's Tailscale address – the remote then works away from home, too. If the phone still cannot connect, the Windows firewall usually blocks the Tailscale network (Windows counts it as a public network) – the hint in the settings says where to allow it.
- The progress bars in the phone's queue show again (they stayed empty).
- **Small updates, now for real:** the 3.4.0 notes said the program file no longer comes with every update – it still did (74 MB): the build wrote a new time stamp into it and put the splash screen's file list in another order each time. Fixed – from 3.4.1 on it stays byte for byte the same; this update carries it one last time.

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
- An app on 3.4.0 downloads only the files that changed (`…-Patch-from-3.4.0.exe` / `…-Portable-Patch-from-3.4.0.zip`).

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
