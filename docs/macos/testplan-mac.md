# CLIPasso Studio für macOS – Test auf einem echten Mac

Stand: 17. November 2026 · Branch: `claude/zealous-einstein-6vb48i`

Dieser Plan ist für den Test am Ende, auf einem echten Mac mit Apple Silicon und macOS 26. Er enthält nur, was
die automatischen Tests nicht prüfen können: was du siehst, hörst und anfasst, echte Geräte (Drucker, Trackpad,
Bildschirm), andere Programme und die Dauer echter Aufträge.

**Was die automatischen Tests schon prüfen (GitHub-Runner `macos-26`, bei jedem Push)**

- Swift-Paket: rund 200 Tests. Dazu gehören Auftragsordner, Galerie, Warteschlange, Modell-Download (mit Abbruch,
  Fortsetzen und SHA-256), Engine-Protokoll und SVG lesen und zeichnen. Außerdem Rahmung, Papier (Pixel für
  Pixel wie die Windows-App), Druckseiten sowie GIF, MP4 und WebP. Die übrigen Exportformate werden Zeichen für
  Zeichen mit der Python-App verglichen.
- Die App wird gebaut, als `.app` gepackt und als DMG abgelegt (Artefakt `CLIPasso-Studio-mac`).
- Ein Selbsttest startet die App ohne Fenster und rechnet einen kleinen CLIPasso-Auftrag mit der eingebauten Engine.
  Danach liest Python die Ergebnisse wieder.
- Bildschirmfotos aller Seiten (Artefakt `screenshots-mac`).
- Die Engine-Tests auf dem Apple-Grafikprozessor (`mps`), mit einer Messung CPU gegen GPU.

**Noch nicht in der Mac-App, also nicht testen:** Masken und Detailpinsel, Handy-Fernbedienung, Updates,
der Pinselstil der Zeichenfläche im Studio (in Exporten und beim Drucken gibt es die Pinselstile schon).

---

## So meldest du einen Fehler

Für jeden Punkt, der nicht stimmt, genügen:

1. die Nummer aus diesem Plan (zum Beispiel **E4**),
2. was du getan hast, was du erwartet hast und was passiert ist,
3. ein Bildschirmfoto (⇧⌘4) oder eine Bildschirmaufnahme (⇧⌘5),
4. bei einer Fehlermeldung ihren vollen Text (er enthält die letzten Zeilen der Engine), bei einem Absturz den
   Bericht aus der App **Konsole** → **Absturzberichte** → „CLIPassoStudio“.

Telegram-Token, Fernbedienungs-Token und PIN gehören nicht in einen Bericht. Prüfe Texte vor dem Senden.

---

## A. Installieren und erster Start

| Nr. | Schritt | Erwartet |
|-----|---------|----------|
| A1 | Lade das DMG aus dem letzten grünen Lauf von „macOS“ (Artefakt `CLIPasso-Studio-mac`) und öffne es. | Das Fenster zeigt die App, den Ordner „Programme“ und die Datei „Bitte zuerst lesen“. |
| A2 | Ziehe die App nach „Programme“ und starte sie. | macOS hält den Start an, weil die App nicht signiert ist. |
| A3 | Folge „Bitte zuerst lesen“: Systemeinstellungen → Datenschutz & Sicherheit → „Dennoch öffnen“. | Die App startet. Danach startet sie wie jede andere App. |
| A4 | Schau auf die Statusanzeige der Engine. | Nach wenigen Sekunden steht dort „bereit“, ohne Fehlermeldung. |
| A5 | Öffne im Finder `~/Library/Application Support/CLIPassoStudio` und `~/Documents/CLIPasso Studio`. | Beide Ordner existieren. Es gibt keine Dateien außerhalb dieser Orte (außer den Einstellungen). |

## B. Modelle

| Nr. | Schritt | Erwartet |
|-----|---------|----------|
| B1 | Starte einen CLIPasso-Auftrag, solange noch kein Modell geladen ist. | Die App fragt vorher, zeigt die Größe und lädt erst nach deiner Zustimmung. |
| B2 | Trenne während des Downloads das WLAN für 30 Sekunden und verbinde es wieder. | Der Download macht weiter, wo er war, und beginnt nicht von vorn. |
| B3 | Seite „Modelle“: Lösche ein Modell und lade es wieder. | Der belegte Platz stimmt mit dem Finder überein (Informationen, ⌘I). |

## C. Studio: Aufträge rechnen

| Nr. | Schritt | Erwartet |
|-----|---------|----------|
| C1 | Starte je einen Auftrag mit CLIPasso, SwiftSketch, ControlSketch und SceneSketch (Beispielbild Kamel). | Die Skizze wächst live. Fortschritt und Restzeit laufen. Das Ergebnis erscheint in der Galerie. |
| C2 | Öffne während eines Auftrags die Aktivitätsanzeige → Fenster → GPU-Verlauf. | Die GPU arbeitet (`mps`). Die CPU ist nicht dauerhaft auf allen Kernen voll. |
| C3 | Pausiere einen Auftrag, warte eine Minute und setze ihn fort. | Er rechnet an derselben Stelle weiter. |
| C4 | Brich einen Auftrag ab. | Er endet sofort. Die Galerie zeigt ihn als abgebrochen und nicht als fertig. |
| C5 | Beende die App während eines Auftrags (⌘Q) und starte sie neu. | Die Galerie zeigt den Auftrag als unterbrochen. „Fortsetzen“ rechnet ihn weiter. Die Zwischenschritte sind noch da. |
| C6 | Klappe das MacBook während eines Auftrags zu, warte und klappe es wieder auf. | Der Auftrag läuft weiter oder meldet klar, was passiert ist. Die Engine ist wieder „bereit“. |
| C7 | Beende in der Aktivitätsanzeige den Prozess `python3` der App, während sie nichts rechnet. | Die App startet die Engine von selbst neu und zeigt einen kurzen Hinweis. |
| C8 | Ändere in der Seitenleiste eine Voreinstellung und einzelne Parameter. | Abhängige Felder werden passend aktiv oder grau, wie in der Windows-App. |

## D. Warteschlange und Galerie

| Nr. | Schritt | Erwartet |
|-----|---------|----------|
| D1 | Ziehe drei Bilder und einen Ordner aus dem Finder in die Warteschlange. | Alle Bilder erscheinen, der Ordner auf Wunsch mit Unterordnern. HEIC-Bilder vom iPhone gehen auch. |
| D2 | Ändere die Reihenfolge mit der Maus und lass die Warteschlange laufen. | Die Aufträge laufen in der neuen Reihenfolge. |
| D3 | Wähle „Wenn fertig“ → „Ruhezustand“ und lass eine kurze Warteschlange laufen. Danach dasselbe mit „Herunterfahren“. | Nach dem letzten Auftrag zählt die App 60 s herunter (abbrechbar), dann schläft der Mac oder fährt herunter. Beim Herunterfahren fragt macOS einmal, ob die App „System Events“ steuern darf. |
| D4 | Kopiere einen Auftragsordner aus der Windows-App (USB-Stick oder Cloud) in den Ergebnisordner. | Er erscheint in der Galerie mit Bild, Skizze, Score und Datum, obwohl er Windows-Pfade enthält. |
| D5 | Suche, filtere und sortiere in der Galerie. Setze einen Favoriten und einen Titel. | Ergebnisse stimmen. Favorit und Titel sind nach einem Neustart noch da. |
| D6 | Kopiere einen auf dem Mac gerechneten Auftrag nach Windows und öffne ihn dort. | Die Windows-App zeigt ihn vollständig, auch Favorit, Titel und nachbearbeitete Skizze. |

## E. Skizze nachbearbeiten

| Nr. | Schritt | Erwartet |
|-----|---------|----------|
| E1 | Radiere mit dem Trackpad einige Striche weg. | Die Striche verschwinden dort, wo du streichst. Es gibt keinen Versatz zur Zeigerposition. |
| E2 | Zeichne mit dem Stift. Teste Trackpad, Maus und, falls vorhanden, ein Grafiktablett. | Die Striche folgen der Hand. Ein Klick allein erzeugt keinen Strich. |
| E3 | ⌘Z und ⇧⌘Z mehrmals, dann „Zurücksetzen“. | Rückgängig und Wiederholen laufen Schritt für Schritt. „Zurücksetzen“ stellt das Original wieder her. |
| E4 | Öffne bei SceneSketch die Matrix und wähle eine andere Zelle. | Die Zelle erscheint groß und lässt sich bearbeiten. Die Matrix zeigt die Änderung. |

## F. Exportieren (⌘E)

Exportiere dieselbe Skizze in jedes Format und öffne die Datei im genannten Programm.

| Nr. | Format | Öffnen mit | Erwartet |
|-----|--------|------------|----------|
| F1 | SVG | Safari, Inkscape oder Illustrator | Gleiche Striche wie in der App, Hintergrund wie gewählt |
| F2 | PNG mit 4096 px | Vorschau | Scharf, richtige Größe, transparent, wenn gewählt |
| F3 | PDF mit 21 cm | Vorschau → Werkzeuge → Informationen | Seitenbreite 21 cm, Linien als Vektoren (beim Zoomen scharf) |
| F4 | SVG · 1 Ebene | Inkscape oder Software des Plotters | Ein einziger Pfad in einer Ebene, ohne Hintergrund |
| F5 | SVG · Ebenen getrennt (SceneSketch) | Inkscape oder Illustrator | Zwei Ebenen, „Hintergrund“ und „Objekt“ |
| F6 | Ganze Matrix (ZIP, SceneSketch) | Finder (Doppelklick) | Für jede Zelle SVG und PNG sowie `matrix.svg` und `matrix.png` als Übersicht |
| F7 | GIF, Strich für Strich und Zeichenprozess | Safari, Vorschau | Läuft in der eingestellten Dauer und wiederholt sich |
| F8 | MP4 | QuickTime Player | Läuft flüssig mit 30 fps, die Dauer stimmt |
| F9 | WebP mit transparentem Hintergrund | Safari | Animiert, Hintergrund durchsichtig |
| F10 | SVG · animiert | Safari, Chrome | Zeichnet sich Strich für Strich und beginnt nach der Pause von vorn |
| F11 | Lottie | lottiefiles.com/preview oder After Effects mit Bodymovin | Zeichnet sich wie F10 |
| F12 | Webseite | Safari | Die Skizze zeichnet sich. Der Knopf „Neu zeichnen“ startet sie von vorn |
| F13 | Papier „Aquarell“ mit Vignette, als PNG und als SVG | Vorschau, Safari | Die Papierstruktur ist sichtbar und sieht aus wie in der Windows-App |
| F14 | Ein langes GIF (60 s, 1024 px) mitten im Export abbrechen | Finder | Es bleibt keine halbe Datei zurück |
| F15 | Pinselstil „Kohle“, dann „Neon“: als SVG, PNG, GIF und Webseite | Safari, Vorschau | Sieht aus wie derselbe Export aus der Windows-App. Neon leuchtet auch im GIF farbig |

Prüfe dabei auch: Die Dateinamen haben die Endungen aus der Windows-App (`_1layer`, `_layers`, `_matrix`,
`_animated`). Beim nächsten Export sind die zuletzt gewählten Einstellungen schon eingestellt.

## G. Drucken (⌘P)

| Nr. | Schritt | Erwartet |
|-----|---------|----------|
| G1 | Drucke eine Skizze auf A4 hoch und quer, mit Titel und Signatur. | Die Vorschau entspricht dem Ausdruck. Ränder und Text sind nicht abgeschnitten. |
| G2 | Drucke vier Skizzen auf eine Seite mit Bildunterschriften. | Raster 2 × 2, Unterschriften unter den richtigen Skizzen |
| G3 | Druckdialog → „Als PDF sichern“ und Papier „Kraft“. | Das PDF hat die Papierstruktur, ohne Kanten und Streifen. |
| G4 | Letter statt A4 (Druckdialog → Papierformat). | Die Seite passt, nichts ist verschoben. |
| G5 | Pinselstil „Bleistift“ im Druckblatt wählen. | Vorschau und Ausdruck zeigen den Stil. Das Druckblatt beginnt immer mit dem Stil des letzten Exports. |

## H. Aussehen, Sprache, Bedienung

| Nr. | Schritt | Erwartet |
|-----|---------|----------|
| H1 | Wechsle zwischen hellem und dunklem Erscheinungsbild (Einstellungen der App und des Systems). | Alles bleibt lesbar. Keine Fläche bleibt in der alten Farbe stehen. |
| H2 | Ziehe das Fenster auf die kleinste Größe und auf Vollbild. | Nichts überlappt oder wird abgeschnitten. Die Seitenleiste lässt sich einklappen. |
| H3 | Stelle Deutsch und Englisch um. | Alle Texte wechseln. Es bleiben keine Schlüssel wie `ui.mac.…` sichtbar. |
| H4 | Prüfe die Schrift der Überschriften und der Druckseiten. | Sie ist „Inter“ wie in der Windows-App und nicht die Systemschrift. |
| H5 | Bediene die App nur mit der Tastatur (Systemeinstellungen → Tastatur → Tastaturnavigation an). | Mit Tab und Leertaste erreichst du jeden Knopf. Der Fokus ist immer sichtbar. |
| H6 | Schalte VoiceOver ein (⌘F5) und geh durch Studio, Galerie und Export. | Jeder Knopf hat einen verständlichen Namen. Bilder haben eine Beschreibung. |
| H7 | Systemeinstellungen → Bedienungshilfen → Anzeige: „Kontrast erhöhen“ und „Bewegung reduzieren“. | Die App bleibt lesbar und verzichtet auf unnötige Animationen. |

## I. Dauer und Last

| Nr. | Schritt | Erwartet |
|-----|---------|----------|
| I1 | Lass eine Warteschlange mit 10 Bildern über Nacht laufen. | Alle Aufträge sind fertig. Der Speicher der App wächst nicht immer weiter (Aktivitätsanzeige → Speicher). |
| I2 | Exportiere ein PNG mit 8192 px auf Papier. | Fertig in unter einer Minute. Die App bleibt dabei bedienbar. |
| I3 | Galerie mit mehr als 200 Aufträgen öffnen und scrollen. | Sie öffnet sich in wenigen Sekunden und scrollt ohne Ruckeln. |
| I4 | Startvolume fast voll (unter 2 GB frei) und ein Modell laden. | Die App warnt vorher und bricht nicht mit einem unklaren Fehler ab. |
