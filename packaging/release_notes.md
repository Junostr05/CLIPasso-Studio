## CLIPasso Studio 2.0 – drei Methoden in einer App

Neu: Neben **[CLIPasso](https://github.com/yael-vinker/CLIPasso)** (SIGGRAPH 2022) zeichnet die App jetzt auch mit **[SwiftSketch](https://github.com/swiftsketch/SwiftSketch)** (SIGGRAPH 2025, Diffusionsmodell – eine Skizze in Sekunden, auch auf der CPU) und **ControlSketch** (Stable Diffusion 1.5 + ControlNet – sehr natürliche Skizzen, braucht eine NVIDIA-GPU). Oben im Studio wählst du die Methode, die Seite **Vergleich** zeichnet ein Bild mit allen Methoden und markiert die beste.

| Datei | Für wen? |
|---|---|
| **`CLIPassoStudio-CPU-Portable.exe`** | Einfach herunterladen und starten – keine Installation. Läuft auf jedem Windows-10/11-PC (64 Bit). Der Start dauert ca. 15–40 s (Entpacken). |
| **`CLIPassoStudio-CPU-Setup.exe`** | Gleiche App als Installer (schnellerer Start, Startmenü-Eintrag). |
| **`CLIPassoStudio-GPU-Setup.exe`** + **alle `CLIPassoStudio-GPU-Setup-*.bin`** | NVIDIA-GPU-Edition (CUDA 12.8: GeForce GTX 16xx / RTX 20xx oder neuer, Treiber ≥ 570): CLIPasso 10–50× schneller, ControlSketch in Minuten statt Stunden. **Alle Dateien in denselben Ordner herunterladen**, dann `CLIPassoStudio-GPU-Setup.exe` starten. |

**Neu in 2.0**
- Methodenwahl im Studio mit eigenen Parametern, Presets, Tooltips und Zeitschätzung pro Methode; alle Optionen von SwiftSketch `generate.py` und ControlSketch `config.py` sind einstellbar.
- Seite **Vergleich**: ein Bild, mehrere Methoden, Ergebnisse nebeneinander mit CLIP-Score, Rechenzeit und Strichzahl.
- Einheitlicher **CLIP-Score** für jede Skizze; bei SwiftSketch/ControlSketch wird damit die beste von mehreren Skizzen gewählt.
- Live-Vorschau auch für die neuen Methoden (bei SwiftSketch jeder Entrauschungsschritt, auch als GIF/MP4 exportierbar).
- Modelle für SwiftSketch (≈ 710 MB) und ControlSketch (≈ 3–4 GB) werden beim ersten Einsatz geladen – ein Klick im Hinweisbalken oder auf der Seite **Modelle**.
- Warteschlange, Galerie (mit Methoden-Filter) und Kommandozeile (`--method swiftsketch|controlsketch`) für alle Methoden.

**Hinweise**
- Windows SmartScreen kann beim ersten Start warnen („Unbekannter Herausgeber“) → *Weitere Informationen* → *Trotzdem ausführen*.
- CPU-Dauer: SwiftSketch ~5 s pro Skizze; CLIPasso „Schnell“ 5–15 Min., „Standard“ 45–90 Min.; ControlSketch mehrere Stunden (GPU: wenige Minuten).
- Lizenz: CC BY-NC-SA 4.0 – **nur nicht-kommerzielle Nutzung**. Die nachgeladenen Modelle haben eigene Lizenzen (siehe THIRD_PARTY_NOTICES.md).
- Prüfsummen: `SHA256SUMS.txt`.

---

**CLIPasso Studio 2.0** adds **SwiftSketch** (diffusion model, a sketch in seconds even on a CPU) and **ControlSketch** (Stable Diffusion 1.5 + ControlNet, needs an NVIDIA GPU) next to CLIPasso, with a method switcher in the studio, a **Compare** page, CLIP scores for every sketch, and models downloaded on first use. Download the portable CPU exe (no installation), the CPU installer, or the NVIDIA GPU installer (download *all* GPU files into one folder, then run the Setup.exe). Non-commercial use only (CC BY-NC-SA 4.0).
