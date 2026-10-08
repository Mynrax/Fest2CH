#!/usr/bin/env python3
"""
fest2ch.py

This tool allows you to export Fortnite Festival songs into Clone Hero / YARG / your favourite 5-fret rhythm game.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

import requests
import mido
from tqdm import tqdm

# URLs

SPARK_TRACKS_URL = (
    "https://fortnitecontent-website-prod07.ol.epicgames.com/"
    "content/api/pages/fortnite-game/spark-tracks"
)

ARCHIVE_README_RAW = (
    "https://raw.githubusercontent.com/BeastFNCreative/"
    "fortnite-blurl-archive/refs/heads/main/spark-tracks/README.md"
)

AKAMAI_MASTER_BLURL_FMT = "https://fortnite-vod.akamaized.net/{vuid}/master.blurl"

EXCLUDE_KEYWORDS = ("instrumental", "preview", "stereo", "(v2)")

# AES Key for Festival MIDI Decryption
FNF_AES_KEY = bytes.fromhex("29B4AC18D090166559244E15548BD4C11B98D33AD57F7B0D9BFFF6CEB7CF6145")

# General helpers

def sanitize_folder_name(name: str, max_len: int = 140) -> str:
    name = (name or "").strip()
    name = re.sub(r"[<>:\"/\\|?*\x00-\x1F]", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return (name[:max_len].rstrip(" .") or "Unknown Song")


def download_file(url: str, out_path: Path, timeout: int = 60) -> None:
    """
    Downloads to a .part file first, then renames on success.
    This prevents corrupt/partial files from tricking the script later.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_suffix(out_path.suffix + ".part")
    
    try:
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            with open(temp_path, "wb") as f:
                for chunk in r.iter_content(1024 * 256):
                    if chunk:
                        f.write(chunk)
        # this should be reanmed ONLY if the download and write were successful
        temp_path.rename(out_path)
    except Exception:
        # if it failed for whatever reason, just clean it up
        if temp_path.exists():
            temp_path.unlink()
        raise


def download_text(url: str, timeout: int = 60) -> str:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def iter_track_entries(data: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    for key, val in data.items():
        if isinstance(val, dict) and isinstance(val.get("track"), dict):
            yield key, val["track"]


def first_str(track_info: Dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    for k in keys:
        v = track_info.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def norm_title_for_match(s: str) -> str:
    s = (s or "").lower().strip()
    s = s.replace("feat.", "ft.").replace("featuring", "ft").replace("feat", "ft")
    s = s.replace("—", "-").replace("–", "-")
    s = re.sub(r"[^a-z0-9\s\-\.&,]", "", s)  # keep commas/& for artist lists
    s = re.sub(r"\s+", " ", s).strip()
    return s


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg was not found in PATH. Please install ffmpeg and try again.")


def build_vuid_maps() -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    readme = download_text(ARCHIVE_README_RAW)

    full_lookup: Dict[str, str] = {}
    vuid_to_desc: Dict[str, str] = {}

    for line in readme.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if "VUID" in line or "---" in line:
            continue

        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 2:
            continue

        vuid_cell, desc = parts[0], parts[1]
        if any(k in desc.lower() for k in EXCLUDE_KEYWORDS):
            continue

        m = re.search(r"\[([A-Za-z0-9]+)\]", vuid_cell)
        vuid = m.group(1) if m else vuid_cell

        key = norm_title_for_match(desc)
        full_lookup.setdefault(key, vuid)
        vuid_to_desc.setdefault(vuid, desc)

    # title-only index (unique only)
    title_to_vuid: Dict[str, str] = {}
    collisions = set()

    for full_key, vuid in full_lookup.items():
        if " - " in full_key:
            title_key = full_key.split(" - ", 1)[1].strip()
        else:
            title_key = full_key.strip()

        if title_key in title_to_vuid and title_to_vuid[title_key] != vuid:
            collisions.add(title_key)
        else:
            title_to_vuid[title_key] = vuid

    for t in collisions:
        title_to_vuid.pop(t, None)

    return full_lookup, title_to_vuid, vuid_to_desc

# MIDI processing: deletes the pad vocals/drums/guitar/bass tracks, and renames the pro tracks to part tracks for use in CH/YARG.
# Feel free to remove this if you're wanting to use these tracks in Encore, for instance. Shoutout Encore btw, y'all are cool.

DELETE_TRACKS = {"PART VOCALS", "PART DRUMS", "PART GUITAR", "PART BASS"}
RENAME_TRACKS = {
    "PRO VOCALS": "PART VOCALS",
    "PLASTIC DRUMS": "PART DRUMS",
    "PLASTIC BASS": "PART BASS",
    "PLASTIC GUITAR": "PART GUITAR",
    "PLASTIC KEYS": "PART KEYS",
}

def get_track_name(track: mido.MidiTrack) -> str:
    for msg in track:
        if msg.type == "track_name":
            return (msg.name or "").strip()
    return ""

def set_track_name(track: mido.MidiTrack, name: str) -> None:
    for msg in track:
        if msg.type == "track_name":
            msg.name = name
            return
    track.insert(0, mido.MetaMessage("track_name", name=name, time=0))

def fix_midi(in_mid: Path, out_mid: Path) -> None:
    mid = mido.MidiFile(in_mid)
    new_mid = mido.MidiFile(type=mid.type, ticks_per_beat=mid.ticks_per_beat)

    for t in mid.tracks:
        name = get_track_name(t)
        if name in DELETE_TRACKS:
            continue

        nt = mido.MidiTrack(t)
        if name in RENAME_TRACKS:
            set_track_name(nt, RENAME_TRACKS[name])

        new_mid.tracks.append(nt)

    out_mid.parent.mkdir(parents=True, exist_ok=True)
    new_mid.save(out_mid)

# Native decryption (Replaces fnf.py subprocess)

def decrypt_dat_to_mid(dat_path: Path) -> Path:
    """Decrypts a Fortnite Festival .dat file to a .mid file using AES ECB."""
    try:
        from Crypto.Cipher import AES
    except ImportError:
        raise RuntimeError(
            "The 'pycryptodome' library is missing. "
            "Please install it by running: pip install pycryptodome"
        )
        
    mid_path = dat_path.with_suffix(".mid")
    cipher = AES.new(FNF_AES_KEY, AES.MODE_ECB)

    with open(dat_path, "rb") as encfile, open(mid_path, "wb") as decfile:
        while True:
            block = encfile.read(16)
            if not block:
                break
            
            # If the final block is shorter than 16 bytes, pad it with null bytes
            if len(block) < 16:
                block = block.ljust(16, b'\x00')
                
            ptxt = cipher.decrypt(block)
            decfile.write(ptxt)

    if not mid_path.exists():
        raise RuntimeError("Failed to output decrypted .mid file.")
        
    return mid_path

# song.ini generation
# Edited the difficulty mapping here to match the correct instrument.
def write_song_ini(song_dir: Path, title: str, artist: str, year: str, diffs: Dict[str, Any]) -> None:
    """
    Writes song.ini with Year and Difficulties.
    Mappings (I think?):
      pg -> Guitar
      pb -> Bass
      pd -> Drums
      vl -> Vocals
    """
    d_guitar = diffs.get("pg", -1)
    d_bass   = diffs.get("pb", -1)
    d_drums  = diffs.get("pd", -1)
    d_vocals = diffs.get("vl", -1)

    ini = (
        "[Song]\n"
        f"name = {title or 'Unknown Title'}\n" # you *should* be able to get the title, but juuuust in case... maybe Epic forgets to add a title?
        f"artist = {artist or 'Unknown Artist'}\n" # same goes here, Epic, if you forget this, you're a bunch of tools.
        "album = \n" # we don't get this info from the API, so not much I can do here... though I was thinking of maybe looking it up somehow via an API? idk, too much work for rn
        "genre = \n" # same thing here, not provided by the API and I don't have an easy way to look it up, so leaving blank for now
        f"year = {year}\n"
        "charter = Fortnite Festival Export\n"
        "delay = 0\n"
        "song_length = 0\n"
        "preview_start_time = 0\n"
        f"diff_guitar = {d_guitar}\n"
        f"diff_bass = {d_bass}\n"
        f"diff_drums = {d_drums}\n"
        f"diff_vocals = {d_vocals}\n"
    )
    (song_dir / "song.ini").write_text(ini, encoding="utf-8")

# blurlconvert + audio

def run_blurlconvert(exe: Path, song_dir: Path) -> None:
    """
    Runs blurlconvert with cwd=exe_dir.
    Moves the resulting 'master_audio.mp4' from exe_dir to song_dir.
    """
    exe_dir = exe.parent
    master_blurl = song_dir / "master.blurl"
    
    # Clean slate in exe dir
    generated_audio = exe_dir / "master_audio.mp4"
    if generated_audio.exists():
        generated_audio.unlink()

    if not master_blurl.exists():
        raise FileNotFoundError(f"master.blurl not found in {song_dir}")

    # Run the tool
    cmd = [str(exe), str(master_blurl.resolve()), str(master_blurl.resolve())]
    p = subprocess.run(cmd, cwd=str(exe_dir), text=True, capture_output=True)

    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    
    if out: tqdm.write(out)
    if err: tqdm.write(err)

    if p.returncode != 0:
        raise RuntimeError(f"blurlconvert exited with {p.returncode}")
        
    # Move file
    target_audio = song_dir / "master_audio.mp4"
    if generated_audio.exists():
        shutil.move(str(generated_audio), str(target_audio))
    else:
        raise RuntimeError("blurlconvert ran but 'master_audio.mp4' was not created.")


def find_audio(song_dir: Path) -> Path:
    master_audio = song_dir / "master_audio.mp4"
    if master_audio.exists():
        return master_audio

    candidates = []
    for ext in (".mp4", ".m4a", ".wav", ".ogg", ".aac"):
        candidates.extend(song_dir.glob(f"*{ext}"))

    if not candidates:
        raise RuntimeError("No audio output found")

    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def split_10ch(audio: Path, out_dir: Path, q: str = "6") -> None:
    require_ffmpeg()

    # FFmpeg filter_complex to split 10 channels into 5 stereo pairs:
    fc = (
        "[0:a]asplit=5[in1][in2][in3][in4][in5];"
        "[in1]pan=stereo|c0=c0|c1=c1[drums];"
        "[in2]pan=stereo|c0=c2|c1=c3[bass];"
        "[in3]pan=stereo|c0=c4|c1=c5[lead];"
        "[in4]pan=stereo|c0=c6|c1=c7[vocals];"
        "[in5]pan=stereo|c0=c8|c1=c9[song]"
    )

    # Note: stdout/stderr was suppressed to keep tqdm bar clean.
    # On error, check=True raises CalledProcessError.
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(audio),
        "-filter_complex", fc,
        "-map", "[drums]",  "-c:a", "libvorbis", "-q:a", q, str(out_dir / "drums.ogg"),
        "-map", "[bass]",   "-c:a", "libvorbis", "-q:a", q, str(out_dir / "bass.ogg"),
        "-map", "[lead]",   "-c:a", "libvorbis", "-q:a", q, str(out_dir / "guitar.ogg"),
        "-map", "[vocals]", "-c:a", "libvorbis", "-q:a", q, str(out_dir / "vocals.ogg"),
        "-map", "[song]",   "-c:a", "libvorbis", "-q:a", q, str(out_dir / "song.ogg"),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ----------------------------
# Main
# ----------------------------

def is_song_complete(song_dir: Path) -> bool:
    """
    Returns True if the folder has song.ini, notes.mid, 
    and all 5 audio stems (ogg).
    """
    required_files = [
        "song.ini",
        "notes.mid",
        "drums.ogg",
        "bass.ogg",
        "guitar.ogg",
        "vocals.ogg",
        "song.ogg"
    ]
    for fname in required_files:
        if not (song_dir / fname).exists():
            return False
    return True


def main():
    ap = argparse.ArgumentParser(description="Export Fortnite Festival -> Clone Hero/YARG folders")
    ap.add_argument("--blurl-exe", required=True, type=Path, help="Path to blurlconvert.exe")
    ap.add_argument("--out", type=Path, default=Path("FestivalExport"))
    ap.add_argument("--limit", type=int, default=0, help="Process only N songs (0 = all)")
    ap.add_argument("--skip-audio", action="store_true", help="Only do MIDI/song.ini (no audio)")
    ap.add_argument("--oggq", default="6", help="Vorbis quality 0-10 (default 6)")
    ap.add_argument("--keep-intermediates", action="store_true",
                    help="Keep master.blurl + master_audio.mp4 (and decrypted .mid/.dat)")
    args = ap.parse_args()

    args.blurl_exe = args.blurl_exe.resolve()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)

    full_lookup: Dict[str, str] = {}
    title_only_lookup: Dict[str, str] = {}
    vuid_to_desc: Dict[str, str] = {}

    if not args.skip_audio:
        print("Loading blurl archive README…")
        full_lookup, title_only_lookup, vuid_to_desc = build_vuid_maps()
        print(f"Loaded {len(full_lookup)} main song entries; {len(title_only_lookup)} unique title-only entries.")

    print("Fetching spark-tracks…")
    data = requests.get(SPARK_TRACKS_URL, timeout=60).json()

    all_entries = list(iter_track_entries(data))
    if args.limit and args.limit > 0:
        all_entries = all_entries[:args.limit]

    failures = 0
    skipped = 0

    pbar = tqdm(all_entries, unit="song")
    
    for song_key, track in pbar:
        artist = first_str(track, ("an", "artist", "artistName", "artist_name", "ar"))
        title  = first_str(track, ("tt", "title", "name", "sn"))
        if not title:
            title = song_key

        display = f"{artist} - {title}" if artist else title
        pbar.set_description(f"Processing: {display[:30]}")

        song_dir = args.out / sanitize_folder_name(display)
        
        #  -- Skip check function --
        # Skips song from being downloaded if the folder is 100% complete (MIDI + 5 stems + INI + image).
        if song_dir.exists() and is_song_complete(song_dir):
            tqdm.write(f"Skipping (already complete): {display}")
            skipped += 1
            continue

        song_dir.mkdir(parents=True, exist_ok=True)
        tqdm.write(f"\n=== {display} ===")
        if song_dir.exists() and any(song_dir.iterdir()):
             tqdm.write("  Partial folder detected. Resuming...")

        try:
            # Metadata
            year = str(track.get("ry", ""))
            diffs = track.get("in", {})
            art_url = track.get("au", "")

            write_song_ini(song_dir, title=title, artist=artist or "", year=year, diffs=diffs)

            if art_url:
                art_path = song_dir / "album.jpg"
                if not art_path.exists():
                    tqdm.write("  Downloading album art -> album.jpg")
                    download_file(art_url, art_path)

            # MIDI
            dat_url = track.get("mu")
            if not dat_url:
                raise RuntimeError("No 'mu' (MIDI DAT URL) in track JSON")

            dat_path = song_dir / Path(dat_url.split("?")[0]).name
            if not dat_path.exists():
                tqdm.write(f"  Downloading MIDI DAT -> {dat_path.name}")
                download_file(dat_url, dat_path)

            mid_path = dat_path.with_suffix(".mid")
            if not mid_path.exists():
                tqdm.write("  Decrypting DAT -> MID natively")
                mid_path = decrypt_dat_to_mid(dat_path)

            if not (song_dir / "notes.mid").exists():
                tqdm.write("  Fixing MIDI -> notes.mid")
                fix_midi(mid_path, song_dir / "notes.mid")

            if not args.keep_intermediates:
                dat_path.unlink(missing_ok=True)
                mid_path.unlink(missing_ok=True)

            # AUDIO
            if args.skip_audio:
                continue

            vuid = None
            full_key = norm_title_for_match(display)
            if full_key in full_lookup:
                vuid = full_lookup[full_key]
            else:
                title_key = norm_title_for_match(title)
                vuid = title_only_lookup.get(title_key)

            if not vuid:
                tqdm.write("  No blurl VUID match found (skipping audio).")
                continue

            akamai_url = AKAMAI_MASTER_BLURL_FMT.format(vuid=vuid)
            master_blurl = song_dir / "master.blurl"
            
            # If master.blurl exists, we assume it's good because download_file
            # now uses a .part file. If the previous run crashed, .part was deleted, so we
            # will safely redownload it now.
            if not master_blurl.exists():
                tqdm.write(f"  Downloading master.blurl via VUID {vuid}")
                download_file(akamai_url, master_blurl)

            tqdm.write("  Running blurlconvert.exe")
            run_blurlconvert(args.blurl_exe, song_dir)

            audio_out = find_audio(song_dir)
            tqdm.write("  Splitting 10ch audio -> stems (ffmpeg)")
            split_10ch(audio_out, song_dir, q=args.oggq)

            # Cleanup
            if not args.keep_intermediates:
                for p in (master_blurl, song_dir / "master_audio.mp4"):
                    if p.exists():
                        p.unlink()

        except Exception as e:
            failures += 1
            tqdm.write(f"FAILED: {e}")

    print(f"\nDone. Processed: {len(all_entries)}, Skipped: {skipped}, Failures: {failures}")
    print(f"Output: {args.out}")

if __name__ == "__main__":
    main()
