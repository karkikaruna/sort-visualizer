# Sorting Visualizer

An animated, block-world sorting visualizer with a synthesized soundtrack. Watch **bubble**, **insertion**, **selection**, **merge** and **quick** sort work through your data step by step, with pointers, a live comparison caption, a running count of comparisons and moves, and a crane that carries blocks as they swap.

Play it live in a window, or export it as an **MP4 with sound** or a silent **GIF**.

## Features

- **Five algorithms**: bubble, insertion, selection, merge and quick sort.
- **Step-by-step narration**: every comparison, swap and placement gets a plain-English caption, so it works as a teaching aid and not only as eye candy.
- **Colour-coded legend** for each algorithm (pivot, scan pointer, boundary, sorted prefix, left/right halves and so on).
- **Merge sort aux panel**: an auxiliary-array view shows the merge buffer, since merge sort uses O(n) extra space.
- **Generated sound**: each value maps to a pitch, and compares, swaps and the final victory sweep get their own sounds. Audio is synthesized from the recorded steps, with no sound files to download.
- **Live playback** with space-bar pause/resume, and audio kept in sync.
- **Export** to `.mp4` (H.264 plus AAC audio) or `.gif`.
- **Your own data**: type numbers in (negatives allowed, up to 60), or generate random, sorted, reversed, few-unique or mixed-sign datasets.
- **Quick sort pivot strategies**: `last`, `random` or `median` (median of three).
- **Batch renderer**: `render_all.py` renders every algorithm on the same dataset, in parallel.
- **Complexity summary** for each algorithm shown on screen.

## Demo videos

Pre-rendered examples (25 shuffled bars, seed 7) live in [`videos/`](videos/):

| Algorithm | File |
|---|---|
| Bubble sort | [`videos/bubble.mp4`](videos/bubble.mp4) |
| Insertion sort | [`videos/insertion.mp4`](videos/insertion.mp4) |
| Selection sort | [`videos/selection.mp4`](videos/selection.mp4) |
| Merge sort | [`videos/merge.mp4`](videos/merge.mp4) |
| Quick sort | [`videos/quick.mp4`](videos/quick.mp4) |

## Setup

Requires **Python 3.8+**.

### 1. Get the project

```bash
git clone https://github.com/karkikaruna/sort-visualizer
cd sort-visualizer
```

### 2. Create an environment 

**Option A: venv**

```bash
python -m venv .venv
```

Activate it:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# Windows (cmd)
.venv\Scripts\activate.bat
```

**Option B: conda**

```bash
conda create -n sort-visualizer python=3.11
conda activate sort-visualizer
```

### 3. Install dependencies

```bash
pip install matplotlib numpy pillow sounddevice imageio-ffmpeg
```

| Package | Purpose |
|---|---|
| `matplotlib`, `numpy` | Required: drawing and audio synthesis |
| `pillow` | GIF export |
| `sounddevice` | Live audio playback |
| `imageio-ffmpeg` | Bundled ffmpeg for MP4 export (not needed if ffmpeg is already installed) |

### 4. Verify

```bash
python sorting_visualizer.py --algo bubble --numbers "5 3 8 1 9 2"
```

A window should open and start the animation. 

## Quick start

Run it with no arguments and it will ask you what to do:

```bash
python sorting_visualizer.py
```

You'll be prompted for an algorithm and a list of numbers. Press **Enter** at the numbers prompt to use random data.

Or skip the prompts:

```bash
python sorting_visualizer.py --algo quick --numbers "42 -7 19 3 -88 25 0"
```

**Controls:** `Space` pauses and resumes (audio included).

## Usage

```
python sorting_visualizer.py [options]
```

| Option | Description | Default |
|---|---|---|
| `--algo {bubble,insertion,selection,merge,quick}` | Algorithm to show (asked interactively if omitted) | ask |
| `--numbers "LIST"` | Numbers to sort, separated by spaces, commas or semicolons, e.g. `"5 -3 8 1"` | ask |
| `--size N` | Number of bars for random data | `25` |
| `--mode {random,sorted,reversed,few-unique,mixed}` | Pattern for generated data (`mixed` includes negatives) | `random` |
| `--pivot {last,random,median}` | Pivot strategy (quick sort only) | `last` |
| `--speed X` | Playback speed multiplier (`0.5` = half speed) | `1.0` |
| `--tween N` | In-between frames for swap animations (`0` disables) | `8` |
| `--seed N` | Random seed for reproducible runs | `7` |
| `--mute` | Turn sound off | off |
| `--save FILE` | Export to `FILE.mp4` (with sound) or `FILE.gif` (silent) | none |
| `--wav FILE.wav` | Export just the soundtrack | none |
| `--fps N` | MP4 frame rate | `30` |
| `--dpi N` | Export resolution | `110` (MP4), `72` (GIF) |
| `--show` | Also open a window while exporting | off |

Input limits: between 2 and 60 whole numbers.

### Examples

```bash
# Watch merge sort on 30 random bars at half speed
python sorting_visualizer.py --algo merge --size 30 --speed 0.5

# See quick sort's worst case on already-sorted data
python sorting_visualizer.py --algo quick --mode sorted --pivot last

# ...and how a median-of-three pivot copes with it
python sorting_visualizer.py --algo quick --mode sorted --pivot median

# Mixed positive and negative values
python sorting_visualizer.py --algo selection --mode mixed --size 20

# Export a video with sound
python sorting_visualizer.py --algo bubble --size 20 --save bubble.mp4

# Export a silent GIF (good for READMEs and slides)
python sorting_visualizer.py --algo insertion --numbers "9 4 7 1 8 2" --save insertion.gif

# Just the soundtrack
python sorting_visualizer.py --algo merge --wav merge.wav
```

## Rendering every algorithm at once

`render_all.py` renders all five algorithms to MP4 using one shared dataset, so the videos are directly comparable.

```bash
python render_all.py
```

| Option | Description | Default |
|---|---|---|
| `--algos A [A ...]` | Subset of `bubble insertion selection merge quick` | all |
| `--size N` | Random bars | `25` |
| `--seed N` | Random seed | `7` |
| `--numbers "LIST"` | Your own numbers instead of random | none |
| `--speed X` | Playback speed | `1.0` |
| `--fps N` | Frame rate | `30` |
| `--dpi N` | Video resolution | `110` |
| `--pivot {last,random,median}` | Quick sort pivot | `last` |
| `--out DIR` | Output folder | `videos` |
| `--jobs N` | Videos rendered in parallel | `2` |
| `--script PATH` | Path to the visualizer script | `sorting_visualizer.py` |

```bash
# Re-render only merge and quick sort, 40 bars, 4 at a time
python render_all.py --algos merge quick --size 40 --jobs 4
```

Rendering is CPU-heavy: expect a minute or two per video, and keep `--jobs` at or below your core count.


## Project structure

```
sort-visualizer/
├── sorting_visualizer.py   # Algorithms, animation, audio synthesis, CLI
├── render_all.py           # Batch-render all algorithms to MP4
└── videos/                 # Pre-rendered demos
    ├── bubble.mp4
    ├── insertion.mp4
    ├── selection.mp4
    ├── merge.mp4
    └── quick.mp4
```


## Contributing

Ideas for extensions, Issues and pull requests are welcome.

