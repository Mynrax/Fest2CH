<div align="center">

  <img src="/festlogo.png" alt="Fest2CH" width="140" />

  <br />
  <br />

  # Fest2CH

  **Converts your favourite Festival songs into your favourite 5-fret rhythm game.**<br />
  *Built with spite and envy :3*
  
  [![Python](https://img.shields.io/badge/language-Python-blue?logo=python)](https://www.python.org/)
  [![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
</div>

**Fest2CH** is an automated export tool that downloads and converts Fortnite Festival songs into fully playable charts for your favourite 5-fret rhythm games like [Clone Hero](https://clonehero.net/) and [YARG.](https://yarg.in/)

This script handles everything from fetching the latest data from the API to decrypting MIDI files, downloading album art, converting the audio, and splitting the 10-channel audio that Festival has into stems that normal 5-fret games actually use.

---

## Features
* **Automated downloading:** Pulls the latest tracks directly from Fortnite's API.
* **Audio stem splitting:** Uses `ffmpeg` to automatically split 10-channel audio into isolated `.ogg` stems.
* **Cleanup:** Removes pad tracks and automatically renames Pro/Plastic tracks to standard `PART` names compatible with CH/YARG.
* **Automatic metadata creation:** Automatically generates a standard `song.ini` with track name, artist, year, and difficulty metadata, plus downloads the album artwork.
* **Only downloads what you need:** Skips fully downloaded and processed songs so you don't waste time or bandwidth re-downloading your library.

---

## Prerequisites

Before running the script, you will need a few external tools and libraries:

1. **[Python 3.x](https://www.python.org/downloads/)**
2. **[FFmpeg](https://ffmpeg.org/download.html):** Must be installed and added to your system's `PATH`.
3. **`blurlconvert.exe`:** Required to convert the downloaded `master.blurl` files into readable 10-track stems, this can be built [here.](https://github.com/spiritascend/blurlconvert)

### Python Dependencies
Install the required Python packages using pip:
```bash
pip install requests mido tqdm pycryptodome
```
## Usage

Run the script from your terminal. You **must** provide the path to `blurlconvert.exe`, or Fest2CH cannot convert audio stems.

### Basic usage

```bash
python fest2ch.py --blurl-exe path/to/blurlconvert.exe
```

---

### Optional arguments

| Argument              | Default             | Description |
|----------------------|---------------------|------------|
| `--out`              | `FestivalExport/`   | Output directory for converted songs |
| `--limit`            | `0 (All)`           | Process only a specific number of songs |
| `--skip-audio`       | `False`             | Skip audio processing; generate only MIDI + `song.ini` |
| `--oggq`             | `6`                 | Vorbis quality (0–10) |
| `--keep-intermediates` | `False`           | Keep intermediate files (e.g. `.blurl`, decrypted `.dat`) |

---

### Example

Export 5 songs to a custom folder at quality level 8:

```bash
python fest2ch.py ^
  --blurl-exe "C:\Users\UrUser\Downloads\blurlconvert.exe" ^
  --out "D:\Games\Clone Hero\Songs" ^
  --limit 5 ^
  --oggq 8
```
---
## Credits

Many thanks to the people in the FN Festival Hub Discord, and thank you to BeastFNCreative for providing the list of VUIDs, which can be found [here.](https://github.com/BeastFNCreative/fortnite-blurl-archive)

## Notice!

⚠️ This tool is **strictly for educational and archival purposes only**. All assets, songs, and related properties belong to Epic Games, Harmonix, and all their respective artists/labels. 
