## Neu in 3.3: Aussehen, Teilen, Ordnung

- **Sechs neue Pinselstile:** Kohle, Kreide, Kugelschreiber, Aquarell, Neon und Kalligrafie – in der Live-Vorschau (Paletten-Knopf im Studio) und in jedem Export.
- **Papier & Hintergrund:** Zeichenpapier, Aquarellpapier, Packpapier, Leinen und Tafel, in jeder Farbe und mit Vignette – in der Vorschau und in jedem Export. Auf dunklem Papier werden schwarze Striche hell.
- **Drucken & Druck-Layout:** A5 bis Poster, Ränder, eine Skizze pro Seite oder ein Kontaktbogen, Titel, Signatur und Namen – als PDF oder direkt auf den Drucker.
- **Lottie & Webseite:** die Skizze zeichnet sich selbst – als Lottie-Datei für Webseiten und Apps oder als eigene kleine Webseite.
- **Handy-Fernsteuerung (WLAN):** QR-Code scannen, Fortschritt und Vorschau sehen, anhalten, Fotos schicken (Einstellungen → *Handy & Nachrichten*).
- **Telegram-Nachricht:** dein eigener Bot schickt dir die fertige Skizze aufs Handy.
- **Alben** in der Galerie: Skizzen auf ein Album ziehen, Alben zeigen, exportieren und drucken.
- **Backup & Umzug:** alles in einer Datei sichern und auf einem neuen Computer zurückspielen (Einstellungen → System).

---

**Neu in 3.2: stabiler, schneller, kleinere Updates**

- **3.2.1 – SceneSketch auf der Grafikkarte:** Szenen mit Objekt brachen auf der Grafikkarte am Ende der ersten Zelle ab („Expected all tensors to be on the same device“). Behoben – gefunden mit dem neuen Selbsttest. Dieses Update ist das erste kleine: Es lädt nur die geänderten Dateien.
- **Kleine Updates:** Ab dem nächsten Update lädt die App nur noch die Dateien, die sich geändert haben – meist Megabytes statt 1 GB (CPU) bzw. 3,5 GB (GPU). Ändert sich PyTorch, kommt wie bisher das ganze Paket.
- **Selbsttest:** Einstellungen → System → *Selbsttest* prüft in wenigen Minuten alle Methoden, das Fortsetzen, das Freistellen und das Laden der Modelle.
- **Problem melden:** Bei einem Fehler (und in den Einstellungen) bereitet *Problem melden …* einen Bericht für GitHub vor – mit Diagnose, Pfade mit deinem Namen sind gekürzt, du siehst und änderst vorher alles.
- **Speicher-Wächter:** Vor dem Start prüft die App, ob Arbeits- und Grafikspeicher reichen, und schlägt sonst kleinere Einstellungen vor – statt nach Minuten abzubrechen.
- **SDXL stückweise auf der Grafikkarte:** Auf Karten unter 8 GB rechnet die SDXL-Aufmerksamkeit von ControlSketch jetzt stückweise auf der Grafikkarte (die Teile warten im Arbeitsspeicher) – viel schneller als auf dem Prozessor. Fortschritt in der Statuszeile; die gemessene Zeit fließt in die Schätzung ein.
- **Mehrere Grafikkarten:** Die Skizzen eines Jobs werden auf alle Karten verteilt (CLIPasso, SwiftSketch, ControlSketch).

---

**Neu in 3.1: ältere Grafikkarten**

- **GTX 9xx / 10xx auf der Grafikkarte:** NVIDIA-Karten vor der GTX 16xx (z. B. GTX 1060, GTX 970) rechnen jetzt auf der Grafikkarte statt auf dem Prozessor. Die App erkennt eine solche Karte selbst und bietet ein Zusatzpaket an: PyTorch mit CUDA 12.6, 2,6 GB Download. Neuere Karten brauchen es nicht.
- **Einstellungen → System:** das Zusatzpaket laden, ein- und ausschalten oder entfernen, dazu der Schalter *Immer mit fp32 rechnen* (Standard: fp16, halb so viel Grafikspeicher).
- **SDXL bei Karten unter 8 GB:** Wählst du bei ControlSketch die SDXL-Aufmerksamkeit, fragt die App, ob dieser eine Schritt auf dem Prozessor rechnen soll (mit allen Kernen, Fortschritt in der Statuszeile, Pause und Abbrechen gehen) oder ob CLIP genommen wird – auf Wunsch gemerkt, änderbar unter Einstellungen → System. Alles danach rechnet wieder auf der Grafikkarte; reicht der Grafikspeicher auch bei größeren Karten nicht, wechselt SDXL von selbst auf den Prozessor.

---

**Neu in 3.0**

## Zeichnen, weiterrechnen, eine Linie

- **Pinselstil live:** Tinte, Bleistift oder Marker direkt in der Vorschau – auch während die Skizze entsteht (Palette in der Leiste über der Skizze).
- **Selbst zeichnen und weiterrechnen:** Mit dem Stift eigene Striche in die Skizze setzen, dann *Mit CLIPasso weiterrechnen* – deine Striche bleiben fest, CLIPasso ergänzt den Rest.
- **Eine Linie:** CLIPasso zeichnet das Motiv in einem einzigen durchgehenden Strich (Einstellung *Eine Linie* bei den Strichen).
- **Turbo-Modus:** schneller, mit leicht anderem Ergebnis. Er rechnet nur die beste Skizze ganz zu Ende und hört auf, wenn sie sich nicht mehr verbessert; bei ControlSketch mit einem kleinen Bild-Decoder (TAESD).

## Schneller

- **Neuer Zeichen-Rasterizer:** ein Render-Schritt von CLIPasso dauert 47–62 statt 68–152 ms, eine lange einzelne Linie 40 statt 4059 ms (gemessen auf einer CPU). Gleicher Algorithmus und gleiche Qualität; die Ergebnisse sind aber nicht bitgleich mit 2.4.
- **Modelle bleiben geladen:** In der Warteschlange startet der nächste Job ohne Ladepause.
- **Mehrere Skizzen gleichzeitig** auf großen Prozessoren (CLIPasso, SwiftSketch).
- Schnellerer Start; die Oberfläche bleibt beim Exportieren bedienbar.

## Formate und Eingaben

- **Freies Seitenverhältnis:** Export im Format des Fotos oder auf den Inhalt zugeschnitten – für SVG, PNG, PDF, Animationen und *Alle exportieren*.
- **Mehr Bildformate:** HEIC/HEIF (iPhone), AVIF, TIFF, BMP und GIF; Fotos werden nach ihrer EXIF-Drehung aufgerichtet.
- **Webcam:** ein Foto direkt aus der App aufnehmen.
- **Zuletzt benutzt:** die letzten Bilder mit einem Klick wieder öffnen.

## Galerie, Warteschlange, überwachter Ordner

- **Galerie 2.0:** schnell auch mit Tausenden Skizzen, Mehrfachauswahl (Löschen, Exportieren, Favorit), Titel, Notizen und Tags, Sortieren nach Score, Dauer, Strichen und Name, Tastatursteuerung.
- **Warteschlange:** Reihenfolge per Ziehen ändern; Pause, Abbrechen und Wiederholen pro Zeile; Details mit *Ins Studio laden*; Gesamt-Restzeit. Fehlgeschlagene Jobs bleiben nach einem Neustart erhalten.
- **Überwachter Ordner:** Bilder, die du in einen Ordner legst, werden automatisch skizziert und exportiert (Einstellungen).

## Zuverlässiger

- **Grafikspeicher voll?** Die App bietet an, auf der CPU oder mit kleineren Einstellungen weiterzurechnen – fertige Skizzen bleiben erhalten.
- **Diagnose kopieren / speichern** (Einstellungen → System): alles, was eine Fehlermeldung braucht, in einem Text.
- **Speicherplatz** (Einstellungen): Zwischenspeicher und alte Updates sehen und leeren. Wechselst du den Ausgabeordner, ziehen die Ergebnisse auf Wunsch mit um.
- Downloads prüfen vorher den freien Platz und setzen nach einem Abbruch fort, auch über einen anderen Server.
- **Portable als ZIP:** startet schneller als die einzelne exe und aktualisiert sich selbst.
