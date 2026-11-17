import argparse
import atexit
import bisect
import itertools
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave

import matplotlib


if ("--save" in sys.argv or "--wav" in sys.argv) and "--show" not in sys.argv:
    matplotlib.use("Agg")

import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.colors import LinearSegmentedColormap, to_rgb
from matplotlib.patches import Patch, Rectangle

sys.setrecursionlimit(10_000)


BG = "#0b1020"
PANEL = "#10172e"
TEXT = "#e5e7f0"
MUTED = "#8b93b0"
CAPTION_BG = "#1b2550"

C_PIVOT = "#ef4444"
C_SCAN = "#fde047"
C_BOUNDARY = "#fb923c"
C_SWAP = "#22d3ee"
C_WAVE = "#f0fdfa"
C_SPARK = "#6ee7b7"
C_LEFT = "#34d399"
C_RIGHT = "#d946ef"
C_RUN = "#60a5fa"
C_NO = "#f472b6"
CONFETTI = ["#f472b6", "#a78bfa", "#38bdf8", "#34d399", "#fde047", "#fb923c"]

CMAP_ACTIVE = LinearSegmentedColormap.from_list(
    "active", ["#4f46e5", "#8b5cf6", "#d946ef", "#f472b6"])
CMAP_SORTED = LinearSegmentedColormap.from_list(
    "sorted", ["#059669", "#34d399", "#a7f3d0"])

BAR_W = 0.78
GLOW_W = 1.12
HOP_HI = 0.10
HOP_LO = 0.03

FIG_W, FIG_H, FIG_H_AUX = 11, 6.6, 9.0
AX_L, AX_R, AX_T, AX_B = 0.03, 0.97, 0.86, 0.09


BASE_MS = 260
TWEEN_MS = 75
FX_STEPS, FX_MS = 7, 60
CONF_STEPS, CONF_MS = 26, 40

MAX_BARS = 60
AUXS = 0.40


def mix(c1, c2, t):
    """Blend two RGB tuples: t=0 -> c1, t=1 -> c2."""
    return tuple((1 - t) * a + t * b for a, b in zip(c1, c2))


def ease(t):
    """Smoothstep easing."""
    return t * t * (3 - 2 * t)


def make_data(n, mode, seed):
    rng = random.Random(seed)
    if mode == "random":
        data = list(range(1, n + 1))
        rng.shuffle(data)
    elif mode == "sorted":
        data = list(range(1, n + 1))
    elif mode == "reversed":
        data = list(range(n, 0, -1))
    elif mode == "few-unique":
        choices = [max(1, n // 5), max(1, n // 2), n]
        data = [rng.choice(choices) for _ in range(n)]
    elif mode == "mixed":
        data = list(range(-(n // 2), n - n // 2))
        rng.shuffle(data)
    else:
        raise ValueError(f"unknown mode: {mode}")
    return data


def parse_numbers(text):
    """Turn '5, -3 8; 1' into [5, -3, 8, 1]. Raises ValueError with a clear message."""
    tokens = [t for t in re.split(r"[,\s;]+", text.strip()) if t]
    nums = []
    for tok in tokens:
        try:
            value = int(tok)
        except ValueError:
            raise ValueError(f"'{tok}' is not a whole number")
        nums.append(value)
    if len(nums) < 2:
        raise ValueError("enter at least 2 numbers")
    if len(nums) > MAX_BARS:
        raise ValueError(f"too many numbers ({len(nums)}); the maximum is {MAX_BARS}")
    return nums


def ask_user_numbers():
    print("Enter the numbers to sort, separated by spaces or commas.")
    print(f"Example: 42 -7 19 3 -88 25 0   ({MAX_BARS} numbers max, negatives allowed)")
    print("Press Enter with nothing typed to use random numbers instead.")
    while True:
        try:
            text = input("Numbers: ")
        except (EOFError, KeyboardInterrupt):
            sys.exit("\nCancelled.")
        if not text.strip():
            return None
        try:
            return parse_numbers(text)
        except ValueError as exc:
            print(f"  Invalid input: {exc}. Try again.")


def ask_user_algo():
    names = list(ALGOS)
    print("Which algorithm do you want to watch?")
    for k, nm in enumerate(names, 1):
        print(f"  {k}) {ALGOS[nm]['title']}")
    while True:
        try:
            text = input(f"Choice (1-{len(names)} or a name): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            sys.exit("\nCancelled.")
        if text in ALGOS:
            return text
        if text.isdigit() and 1 <= int(text) <= len(names):
            return names[int(text) - 1]
        print("  Not a valid choice. Try again.")


def mk(idx, color, label, row, top=False):
    return (idx, color, label, row, top)


def cmp_info(a, b, op, nop, yes, yes_txt, no_txt, space="main"):
    return {"a": a, "b": b, "op": op, "nop": nop, "yes": yes,
            "yes_txt": yes_txt, "no_txt": no_txt, "space": space}


class Recorder:

    def __init__(self, data):
        self.a = list(data)
        self.n = len(data)
        self.frames = []
        self.sorted = set()
        self.comparisons = 0
        self.moves = 0
        self.depth = 0

    def snap(self, msg, kind, lo=None, hi=None, marks=(), amarks=(), swapped=(),
             hold=1.0, wave=None, cmp=None, focus=None, pline=None, tint=None,
             aux=None, hidden=None, amid=None, fly=None):
        self.frames.append({
            "arr": self.a[:],
            "lo": lo, "hi": hi,
            "marks": tuple(marks),
            "amarks": tuple(amarks),
            "swapped": tuple(swapped),
            "sorted": set(self.sorted),
            "comparisons": self.comparisons,
            "moves": self.moves,
            "depth": self.depth,
            "msg": msg, "kind": kind, "hold": hold, "wave": wave,
            "cmp": cmp, "focus": focus, "pline": pline,
            "tint": dict(tint) if tint else {},
            "aux": dict(aux) if aux is not None else None,
            "hidden": set(hidden) if hidden else set(),
            "amid": amid, "fly": fly,
        })

    def swap(self, x, y):
        if x != y:
            self.a[x], self.a[y] = self.a[y], self.a[x]
            self.moves += 1

    def finish(self):
        self.sorted = set(range(self.n))
        self.snap("Sorted!", "sorted", hold=2.0)
        for k in range(self.n):          # victory sweep
            self.snap("Sorted!", "wave", wave=k)
        self.snap("Sorted!", "final", hold=25.0)
        return self.frames


def record_bubble(data):
    r = Recorder(data)
    a, n = r.a, r.n
    r.snap("Initial array. Press space to pause.", "start", hold=6.0)
    for p in range(n - 1):
        hi = n - 1 - p
        r.snap(f"Pass {p + 1}: bubble the largest of 0..{hi} up to index {hi}",
               "partition", 0, hi, focus=hi, hold=2.0)
        swapped_any = False
        for j in range(hi):
            r.comparisons += 1
            yes = a[j] > a[j + 1]
            marks = [mk(j, C_SCAN, "j", 0), mk(j + 1, C_BOUNDARY, "j+1", 1)]
            r.snap("", "compare", 0, hi, marks=marks, focus=j,
                   cmp=cmp_info(j, j + 1, ">", "<=", yes,
                                "swap them", "already in order"))
            if yes:
                r.swap(j, j + 1)
                swapped_any = True
                r.snap(f"Swapped: the larger {a[j + 1]} moves one step right",
                       "swap", 0, hi, marks=marks, swapped=(j, j + 1), focus=j)
        r.sorted.add(hi)
        r.snap(f"{a[hi]} bubbled up to index {hi}: its final position",
               "place", 0, hi, focus=hi)
        if not swapped_any:
            r.sorted.update(range(0, hi))
            r.snap("No swaps in that pass, so everything left is already sorted",
                   "recurse", 0, hi, hold=2.0)
            break
    else:
        r.sorted.add(0)
        r.snap(f"Last element {a[0]} is already in place", "single", 0, 0, focus=0)
    return r.finish()


# ---- Insertion sort ------------------------------------------------------
def record_insertion(data):
    r = Recorder(data)
    a, n = r.a, r.n
    r.snap("Initial array. Press space to pause.", "start", hold=6.0)
    for i in range(1, n):
        key, j = a[i], i

        def prefix(skip):
            return {k: C_LEFT for k in range(i + 1) if k != skip}

        r.snap(f"Take {key} (index {i}) as the key. Indices 0..{i - 1} are sorted",
               "pick", 0, i, marks=[mk(i, C_PIVOT, "key", 2, True)], focus=i,
               pline=i, tint=prefix(i), hold=2.0)
        while j > 0:
            r.comparisons += 1
            yes = a[j - 1] > a[j]
            r.snap("", "compare", 0, i,
                   marks=[mk(j - 1, C_SCAN, "j", 0), mk(j, C_PIVOT, "key", 2, True)],
                   focus=j - 1, pline=j, tint=prefix(j),
                   cmp=cmp_info(j - 1, j, ">", "<=", yes,
                                "shift: swap the key left", "key is in place"))
            if not yes:
                break
            r.swap(j - 1, j)
            j -= 1
            r.snap(f"{a[j + 1]} > {key}: the key hops one step left", "swap", 0, i,
                   marks=[mk(j, C_PIVOT, "key", 2, True)], swapped=(j, j + 1),
                   focus=j, pline=j, tint=prefix(j))
        r.snap(f"Key {key} lands at index {j}. Indices 0..{i} are now sorted",
               "single", 0, i, marks=[mk(j, C_PIVOT, "key", 2, True)], focus=j,
               tint=prefix(j))
    return r.finish()


# ---- Selection sort ------------------------------------------------------
def record_selection(data):
    r = Recorder(data)
    a, n = r.a, r.n
    r.snap("Initial array. Press space to pause.", "start", hold=6.0)
    for i in range(n - 1):
        m = i
        r.snap(f"Pass {i + 1}: find the smallest value in {i}..{n - 1}",
               "partition", i, n - 1,
               marks=[mk(i, C_BOUNDARY, "i", 1), mk(m, C_PIVOT, "min", 2, True)],
               focus=i, pline=m, hold=2.0)
        for j in range(i + 1, n):
            r.comparisons += 1
            yes = a[j] < a[m]
            r.snap("", "compare", i, n - 1,
                   marks=[mk(i, C_BOUNDARY, "i", 1), mk(j, C_SCAN, "j", 0),
                          mk(m, C_PIVOT, "min", 2, True)],
                   focus=j, pline=m,
                   cmp=cmp_info(j, m, "<", ">=", yes,
                                "new minimum found", "minimum stays"))
            if yes:
                m = j
                r.snap(f"New minimum: {a[m]} at index {m}", "pick", i, n - 1,
                       marks=[mk(i, C_BOUNDARY, "i", 1), mk(j, C_SCAN, "j", 0),
                              mk(m, C_PIVOT, "min", 2, True)],
                       focus=m, pline=m)
        swapped = (i, m) if m != i else ()
        r.swap(i, m)
        r.sorted.add(i)
        note = "swap it to the front" if m != i else "it is already at the front"
        r.snap(f"Minimum {a[i]}: {note}. Index {i} is final", "place", i, n - 1,
               marks=[mk(i, C_PIVOT, "min", 2, True)], swapped=swapped, focus=i)
    r.sorted.add(n - 1)
    r.snap(f"Last element {a[n - 1]} is already in place", "single", n - 1, n - 1,
           focus=n - 1)
    return r.finish()


# ---- Merge sort ----------------------------------------------------------
def record_merge(data):
    r = Recorder(data)
    a, n = r.a, r.n
    runs = set()
    r.snap("Initial array. Press space to pause.", "start", hold=6.0)

    def merge(lo, mid, hi):
        aux = {k: a[k] for k in range(lo, hi + 1)}
        hidden = set(range(lo, hi + 1))
        top = lo == 0 and hi == n - 1
        p, q, k = lo, mid + 1, lo

        def written():
            return {s: C_RUN for s in range(lo, hi + 1) if s not in hidden}

        def pointers():
            out = []
            if p <= mid:
                out.append((p, C_SCAN, "p"))
            if q <= hi:
                out.append((q, C_PIVOT, "q"))
            return out

        r.snap(f"Merge {lo}..{mid} with {mid + 1}..{hi}: copy both halves "
               f"into the helper buffer", "copy", lo, hi, amarks=pointers(),
               aux=aux, hidden=hidden, amid=mid, focus=lo, hold=2.2)
        while p <= mid or q <= hi:
            if p <= mid and q <= hi:
                r.comparisons += 1
                yes = aux[p] <= aux[q]
                r.snap("", "compare", lo, hi, marks=[mk(k, C_BOUNDARY, "k", 0)],
                       amarks=pointers(), aux=aux, hidden=hidden, amid=mid,
                       tint=written(), focus=p,
                       cmp=cmp_info(p, q, "<=", ">", yes, "take from the left half",
                                    "take from the right half", space="aux"))
                from_left = yes
                why = ("smaller or equal, from the left half" if yes
                       else "smaller, from the right half")
            elif p <= mid:
                from_left = True
                why = "the right half is empty, copy the rest"
            else:
                from_left = False
                why = "the left half is empty, copy the rest"

            # Track the side explicitly: once the left half is exhausted, p can
            # equal q, so comparing indices would advance the wrong pointer.
            take = p if from_left else q
            val = aux.pop(take)
            a[k] = val
            r.moves += 1
            hidden.discard(k)
            if top:
                r.sorted.add(k)
            if from_left:
                p += 1
            else:
                q += 1
            r.snap(f"Write {val} to index {k}: {why}", "write", lo, hi,
                   marks=[mk(k, C_BOUNDARY, "k", 0)], amarks=pointers(), aux=aux,
                   hidden=hidden, amid=mid, tint=written(), focus=k,
                   fly=(take, k, val))
            k += 1
        runs.update(range(lo, hi + 1))
        r.snap(f"Indices {lo}..{hi} are now one sorted run", "recurse", lo, hi,
               tint={s: C_RUN for s in runs}, hold=1.6)

    def sort(lo, hi):
        r.depth += 1
        if lo < hi:
            mid = (lo + hi) // 2
            tint = {s: C_RUN for s in runs}
            tint.update({s: C_LEFT for s in range(lo, mid + 1)})
            tint.update({s: C_RIGHT for s in range(mid + 1, hi + 1)})
            r.snap(f"Split {lo}..{hi} into {lo}..{mid} and {mid + 1}..{hi}",
                   "partition", lo, hi, focus=mid, tint=tint, hold=1.8)
            sort(lo, mid)
            sort(mid + 1, hi)
            merge(lo, mid, hi)
        r.depth -= 1

    sort(0, n - 1)
    return r.finish()


# ---- Quick sort ----------------------------------------------------------
def record_quick(data, pivot_strategy="last"):
    r = Recorder(data)
    a, n = r.a, r.n
    r.snap("Initial array. Press space to pause.", "start", hold=6.0)

    def choose_pivot(lo, hi):
        if pivot_strategy == "random":
            return random.randint(lo, hi)
        if pivot_strategy == "median":
            mid = (lo + hi) // 2
            trio = sorted([(a[lo], lo), (a[mid], mid), (a[hi], hi)])
            return trio[1][1]
        return hi  # "last"

    def regions(lo, i, upto):
        """Tint: checked <= pivot (left) and checked > pivot (right)."""
        t = {k: C_LEFT for k in range(lo, i + 1)}
        t.update({k: C_RIGHT for k in range(i + 1, upto + 1)})
        return t

    def partition(lo, hi):
        p = choose_pivot(lo, hi)
        if p != hi:
            r.snap(f"Pivot strategy '{pivot_strategy}' picked {a[p]}; "
                   f"moving it to the end", "pick", lo, hi,
                   marks=[mk(p, C_PIVOT, "pivot", 2, True)], focus=p, pline=p,
                   hold=2.0)
            r.swap(p, hi)
            r.snap("Pivot moved to the end of the range", "swap", lo, hi,
                   marks=[mk(hi, C_PIVOT, "pivot", 2, True)], swapped=(p, hi),
                   focus=hi, pline=hi, hold=1.6)
        pv = a[hi]
        pm = mk(hi, C_PIVOT, "pivot", 2, True)
        r.snap(f"Partition indices {lo}..{hi} around pivot {pv}", "partition",
               lo, hi, marks=[pm], focus=hi, pline=hi, hold=2.2)

        i = lo - 1
        for j in range(lo, hi):
            r.comparisons += 1
            yes = a[j] <= pv
            marks = [mk(j, C_SCAN, "j", 0), pm]
            if i >= lo:
                marks.insert(1, mk(i, C_BOUNDARY, "i", 1))
            r.snap("", "compare", lo, hi, marks=marks, focus=j, pline=hi,
                   tint=regions(lo, i, j - 1),
                   cmp=cmp_info(j, hi, "<=", ">", yes, "joins the left region",
                                "stays in the right region"))
            if yes:
                i += 1
                if i != j:
                    r.swap(i, j)
                    r.snap(f"{a[i]} <= {pv}: swap it into the left region", "swap",
                           lo, hi,
                           marks=[mk(j, C_SCAN, "j", 0), mk(i, C_BOUNDARY, "i", 1), pm],
                           swapped=(i, j), focus=j, pline=hi,
                           tint=regions(lo, i, j))
                else:
                    r.snap(f"{a[i]} <= {pv}: already in the left region", "keep",
                           lo, hi, marks=[mk(j, C_SCAN, "i = j", 0), pm],
                           focus=j, pline=hi, tint=regions(lo, i, j))

        r.swap(i + 1, hi)
        r.sorted.add(i + 1)
        r.snap(f"Place pivot {pv} at index {i + 1}: its final position", "place",
               lo, hi, marks=[mk(i + 1, C_PIVOT, "pivot", 2, True)],
               swapped=(i + 1, hi), focus=i + 1)
        return i + 1

    def quicksort(lo, hi):
        r.depth += 1
        if lo < hi:
            p = partition(lo, hi)
            r.snap(f"Pivot {a[p]} is sorted. Now recurse on the left and right parts",
                   "recurse", lo, hi, marks=[mk(p, C_PIVOT, "pivot", 2, True)],
                   focus=p, hold=2.0)
            quicksort(lo, p - 1)
            quicksort(p + 1, hi)
        elif lo == hi:
            r.sorted.add(lo)
            r.snap(f"Single element {a[lo]} is already sorted", "single", lo, hi,
                   focus=lo)
        r.depth -= 1

    quicksort(0, n - 1)
    return r.finish()


GRASS, DIRT, STONE = "#5fa332", "#8a5a36", "#868686"
EMERALD, MOSS = "#21c25a", "#56795a"
WAITING = mix(to_rgb(GRASS), to_rgb(PANEL), 0.7)

ALGOS = {
    "bubble": dict(
        title="Bubble Sort", record=record_bubble, move="swaps", aux=False,
        complexity="best O(n)   average O(n^2)   worst O(n^2)   space O(1)",
        legend=[(C_SCAN, "Comparing (j)"), (C_BOUNDARY, "Neighbour (j+1)"),
                (C_SWAP, "Swapping (crane)"), (EMERALD, "Final position"),
                (GRASS, "Unsorted range")]),
    "insertion": dict(
        title="Insertion Sort", record=record_insertion, move="swaps", aux=False,
        complexity="best O(n)   average O(n^2)   worst O(n^2)   space O(1)",
        legend=[(C_PIVOT, "Key"), (C_SCAN, "Compared (j)"),
                (C_SWAP, "Swapping (crane)"), (C_LEFT, "Sorted prefix"),
                (WAITING, "Not inserted yet"), (EMERALD, "Final position")]),
    "selection": dict(
        title="Selection Sort", record=record_selection, move="swaps", aux=False,
        complexity="always O(n^2) compares   only O(n) swaps   space O(1)",
        legend=[(C_PIVOT, "Current minimum"), (C_SCAN, "Scanning (j)"),
                (C_BOUNDARY, "Start of unsorted (i)"), (C_SWAP, "Swapping (crane)"),
                (EMERALD, "Final position"), (GRASS, "Unsorted range")]),
    "merge": dict(
        title="Merge Sort", record=record_merge, move="writes", aux=True,
        complexity="always O(n log n)   space O(n)",
        legend=[(C_LEFT, "Left half"), (C_RIGHT, "Right half"),
                (C_SCAN, "Left pointer (p)"), (C_PIVOT, "Right pointer (q)"),
                (C_BOUNDARY, "Write index (k)"), (C_RUN, "Merged run"),
                (EMERALD, "Final position")]),
    "quick": dict(
        title="Quick Sort", record=record_quick, move="swaps", aux=False,
        complexity="average O(n log n)   worst O(n^2)   space O(log n)",
        legend=[(C_PIVOT, "Pivot"), (C_SCAN, "Scanning (j)"),
                (C_BOUNDARY, "Boundary (i)"), (C_SWAP, "Swapping (crane)"),
                (C_LEFT, "Checked: \u2264 pivot"), (C_RIGHT, "Checked: > pivot"),
                (EMERALD, "Final position")]),
}


def expand_states(frames, tween_steps):
    """Turn frames into render states, each with a duration in milliseconds."""
    states = []
    n = len(frames[0]["arr"])
    fly_steps = max(2, tween_steps // 2) if tween_steps > 0 else 0

    def add(fi, f, dur, role="main", tween=None, fx=None, pop=None, phase=None):
        states.append({"fi": fi, "f": f, "dur": dur, "role": role,
                       "tween": tween, "fx": fx, "pop": pop, "phase": phase})

    def wave_fx(f, k):
        bursts = []
        for b in range(max(0, k - 3), min(n, k + 1)):
            age = k - b
            bursts.append((b, f["arr"][b], age / 4, b * 7 + 3, C_SPARK))
        return {"bursts": bursts}

    for fi, f in enumerate(frames):
        kind = f["kind"]
        sw = f["swapped"]
        if tween_steps > 0 and len(sw) == 2 and sw[0] != sw[1]:
            x, y = sw
            prev = f["arr"][:]
            prev[x], prev[y] = prev[y], prev[x]
            for s in range(1, tween_steps + 1):
                u = s / (tween_steps + 1)
                add(fi, f, TWEEN_MS, role="tween",
                    tween={"type": "swap", "x": x, "y": y, "te": ease(u),
                           "prev": prev, "u": u})

        if f["fly"] and fly_steps > 0:
            src, dst, val = f["fly"]
            for s in range(1, fly_steps + 1):
                u = s / (fly_steps + 1)
                add(fi, f, TWEEN_MS * 0.8, role="tween",
                    tween={"type": "fly", "src": src, "dst": dst, "val": val,
                           "te": ease(u), "u": u})

        if kind in ("place", "single", "write"):
            px = f["focus"]
            py = f["arr"][px]
            steps, ms, tail = {"place": (FX_STEPS, FX_MS, 260),
                               "single": (3, 60, 150),
                               "write": (2, 45, 60)}[kind]
            add(fi, f, 80, fx={"bursts": [(px, py, 0.0, fi, C_SPARK)]}, pop=(px, 0.0))
            for s in range(1, steps + 1):
                p = s / (steps + 1)
                add(fi, f, ms, role="fx",
                    fx={"bursts": [(px, py, p, fi, C_SPARK)]}, pop=(px, p))
            add(fi, f, tail, role="tail")
        elif kind == "compare":
            add(fi, f, BASE_MS * 0.8, phase="ask")                 # "a > b ?"
            add(fi, f, BASE_MS * 0.9, role="ans", phase="answer")  # YES / NO
        elif kind == "wave":
            add(fi, f, 90, fx=wave_fx(f, f["wave"]))
        elif kind == "final":
            for s in range(1, 4):
                add(fi, f, 45, role="wavetail", fx=wave_fx(f, n - 1 + s))
            for s in range(CONF_STEPS):
                add(fi, f, CONF_MS, role="confetti",
                    fx={"confetti": (s + 1) / CONF_STEPS})
            add(fi, f, BASE_MS * f["hold"])
        else:
            add(fi, f, BASE_MS * f["hold"])
    return states


def assign_times(states, speed):
    """Give every state a start time `t0` and length `dur_s` in seconds."""
    t = 0.0
    for st in states:
        st["t0"] = t
        st["dur_s"] = st["dur"] / 1000.0 / speed
        t += st["dur_s"]
    return t


SR = 44100
PENTATONIC = [0, 2, 4, 7, 9]


def note_freq(frac, octaves=3, base=130.81):
    """Map 0..1 to a note of the C major pentatonic scale (C3 .. C6)."""
    steps = octaves * len(PENTATONIC)
    idx = int(round(min(max(frac, 0.0), 1.0) * steps))
    octave, degree = divmod(idx, len(PENTATONIC))
    return base * 2 ** ((12 * octave + PENTATONIC[degree]) / 12)


def _t(dur):
    return np.arange(int(dur * SR)) / SR


def blip(freq, dur=0.09, vol=0.2, tau=0.03, harm=0.25):
    """Short marimba-like tick."""
    t = _t(dur)
    env = np.minimum(1, t / 0.004) * np.exp(-t / tau)
    w = np.sin(2 * np.pi * freq * t) + harm * np.sin(4 * np.pi * freq * t)
    return vol * w * env


def glide(f1, f2, dur=0.14, vol=0.18):
    """Sine that slides from f1 to f2."""
    t = _t(dur)
    f = np.linspace(f1, f2, len(t))
    phase = 2 * np.pi * np.cumsum(f) / SR
    env = np.sin(np.pi * t / dur) ** 0.7
    return vol * np.sin(phase) * env


def whoosh(rng, dur=0.14, vol=0.06):
    """Soft filtered-noise swish."""
    n = int(dur * SR)
    x = np.convolve(rng.standard_normal(n), np.ones(28) / 28, mode="same")
    env = np.sin(np.pi * np.arange(n) / n) ** 1.5
    return vol * 5 * x * env


def kick(dur=0.24, vol=0.36):
    """Low drum thump with a quick pitch drop."""
    t = _t(dur)
    f = 52 + 100 * np.exp(-t / 0.045)
    return vol * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.085)


def pad(freq, dur=0.38, vol=0.08):
    """Gentle sustained note."""
    t = _t(dur)
    return vol * np.sin(2 * np.pi * freq * t) * np.sin(np.pi * t / dur) ** 2


def bell(freq, dur=0.9, vol=0.25, tau=0.24):
    """Bell / glockenspiel: a fundamental plus decaying inharmonic partials."""
    t = _t(dur)
    env = np.minimum(1, t / 0.003) * np.exp(-t / tau)
    w = (np.sin(2 * np.pi * freq * t)
         + 0.45 * np.sin(2 * np.pi * 2.0 * freq * t) * np.exp(-t / 0.14)
         + 0.28 * np.sin(2 * np.pi * 2.76 * freq * t) * np.exp(-t / 0.09)
         + 0.15 * np.sin(2 * np.pi * 5.4 * freq * t) * np.exp(-t / 0.05))
    return vol * w * env


def _add(buf, t, sig):
    i = int(t * SR)
    if i < 0 or i >= len(buf):
        return
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[: j - i]


def value_scale(values):
    """Return (base, span) so that (v - base) / span lies in 0..1 for every value."""
    base = min(0, min(values))
    span = max(values) - base
    return base, (span if span > 0 else 1)


def synth_audio(frames, states):
    """Build the whole sound track (int16 mono) from the timed states."""
    vbase, vspan = value_scale(frames[0]["arr"])
    total = states[-1]["t0"] + states[-1]["dur_s"] + 2.0
    buf = np.zeros(int(total * SR) + SR)
    rng = np.random.default_rng(3)

    first, main, confetti = {}, {}, {}
    for si, st in enumerate(states):
        fi = st["fi"]
        first.setdefault(fi, si)
        if st["role"] == "main":
            main[fi] = si
        elif st["role"] == "confetti":
            confetti.setdefault(fi, si)

    def nf(value):
        return note_freq((value - vbase) / vspan)

    _add(buf, 0.0, glide(220, 880, dur=0.35, vol=0.10))            # start-up swoosh

    for fi, f in enumerate(frames):
        kind, arr = f["kind"], f["arr"]
        t_first = states[first[fi]]["t0"]
        t_main = states[main[fi]]["t0"]
        sw = f["swapped"]
        foc = f["focus"] if f["focus"] is not None else 0

        if len(sw) == 2 and sw[0] != sw[1] and kind != "wave":     # swap hop
            f1, f2 = nf(arr[sw[0]]), nf(arr[sw[1]])
            _add(buf, t_first, glide(f1, f2, dur=0.5, vol=0.17))
            _add(buf, t_first, whoosh(rng, dur=0.5, vol=0.05))

        if kind == "compare":
            cm = f["cmp"]
            src = f["aux"] if cm["space"] == "aux" else arr
            _add(buf, t_main, blip(nf(src[cm["a"]]), vol=0.11, tau=0.025))
        elif kind == "keep":
            _add(buf, t_main, blip(nf(arr[foc]) * 2, dur=0.06, vol=0.05, tau=0.02))
        elif kind == "pick":
            _add(buf, t_main, blip(nf(arr[foc]), dur=0.2, vol=0.16, tau=0.08))
            _add(buf, t_main, whoosh(rng, dur=0.2, vol=0.05))
        elif kind == "partition":
            _add(buf, t_main, kick())
            _add(buf, t_main, pad(nf(arr[foc])))
        elif kind == "copy":
            _add(buf, t_main, glide(200, 520, dur=0.35, vol=0.10))
            _add(buf, t_main, whoosh(rng, dur=0.3, vol=0.05))
        elif kind == "write":
            _add(buf, t_first, whoosh(rng, dur=0.12, vol=0.03))
            _add(buf, t_main, blip(nf(arr[foc]), dur=0.12, vol=0.15,
                                   tau=0.05, harm=0.3))
        elif kind == "place":
            fr = nf(arr[foc])
            _add(buf, t_main, bell(fr, vol=0.26))
            for s in range(5):                                      # sparkle grains
                _add(buf, t_main + 0.03 * (s + 1),
                     blip(fr * 4 * (1 + 0.1 * rng.random()), dur=0.05, vol=0.035, tau=0.015))
        elif kind == "recurse":
            _add(buf, t_main, whoosh(rng, dur=0.22, vol=0.05))
        elif kind == "single":
            _add(buf, t_main, bell(nf(arr[foc]) * 2, dur=0.35, vol=0.09, tau=0.1))
        elif kind == "wave":
            _add(buf, t_main, blip(nf(arr[f["wave"]]), dur=0.14, vol=0.22,
                                   tau=0.05, harm=0.35))
        elif kind == "final":
            t_c = states[confetti[fi]]["t0"]
            for k, fr in enumerate((261.63, 329.63, 392.0, 523.25)):  # C major chord
                _add(buf, t_c + 0.025 * k, bell(fr, dur=1.8, vol=0.17, tau=0.55))
            _add(buf, t_c, whoosh(rng, dur=0.3, vol=0.08))

    buf = np.tanh(buf * 1.3)
    buf /= max(1e-9, np.abs(buf).max())
    return (buf * 0.9 * 32767).astype(np.int16)


def write_wav(path, samples):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(samples.tobytes())


class AudioPlayer:

    def __init__(self, samples):
        self.samples = samples
        self.backend = None
        self.proc = None
        self.tmp = os.path.join(tempfile.gettempdir(), f"sv_audio_{os.getpid()}.wav")
        atexit.register(self._cleanup)
        try:
            import sounddevice as sd
            self.sd = sd
            self.backend = "sounddevice"
        except Exception:
            if sys.platform.startswith("win"):
                self.backend = "winsound"
            elif sys.platform == "darwin" and shutil.which("afplay"):
                self.backend = "afplay"
            else:
                for cmd in ("paplay", "aplay", "ffplay", "play"):
                    if shutil.which(cmd):
                        self.backend = cmd
                        break

    @property
    def available(self):
        return self.backend is not None

    def play(self, offset=0.0):
        self.stop()
        part = self.samples[int(offset * SR):]
        if len(part) == 0 or not self.available:
            return
        try:
            if self.backend == "sounddevice":
                self.sd.play(part, SR)
                return
            write_wav(self.tmp, part)
            if self.backend == "winsound":
                import winsound
                winsound.PlaySound(self.tmp, winsound.SND_FILENAME | winsound.SND_ASYNC)
                return
            args = {
                "afplay": ["afplay", self.tmp],
                "paplay": ["paplay", self.tmp],
                "aplay": ["aplay", "-q", self.tmp],
                "ffplay": ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", self.tmp],
                "play": ["play", "-q", self.tmp],
            }[self.backend]
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
        except Exception as exc:  # audio must never crash the animation
            print(f"(audio playback failed: {exc})")
            self.backend = None

    def stop(self):
        try:
            if self.backend == "sounddevice":
                self.sd.stop()
            elif self.backend == "winsound":
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            elif self.proc is not None:
                self.proc.terminate()
        except Exception:
            pass
        self.proc = None

    def _cleanup(self):
        self.stop()
        try:
            os.remove(self.tmp)
        except OSError:
            pass


# --------------------------------------------------------------------------
# Particles
# --------------------------------------------------------------------------
def burst_particles(x, y, p, seed, color, ux, uy, count=16, radius_in=0.8):
    """Sparkles flying outward from (x, y). p goes 0 -> 1 over the burst."""
    rng = np.random.default_rng(seed)
    ang = rng.uniform(0, 2 * np.pi, count)
    spd = rng.uniform(0.5, 1.0, count)
    r = radius_in * spd * (1 - (1 - p) ** 2.2)
    xs = x + np.cos(ang) * r * ux
    ys = y + (np.sin(ang) * r - 0.22 * p * p) * uy
    sizes = 170 * (1 - p) ** 1.1 * (0.5 + spd)
    whiten = rng.uniform(0, 0.6, count)[:, None]
    rgba = np.empty((count, 4))
    rgba[:, :3] = np.array(to_rgb(color)) * (1 - whiten) + whiten
    rgba[:, 3] = (1 - p) ** 0.7
    return np.column_stack([xs, ys]), sizes, rgba


def confetti_particles(p, xmin, xmax, ytop, ybot, count=130, seed=11):
    """Confetti fluttering down from the top. p goes 0 -> 1."""
    rng = np.random.default_rng(seed)
    x0 = rng.uniform(xmin, xmax, count)
    speed = rng.uniform(0.75, 1.3, count)
    phase = rng.uniform(0, 2 * np.pi, count)
    sway = rng.uniform(0.15, 0.6, count)
    y_start = ytop + 0.08 * (ytop - ybot)
    ys = y_start - p * speed * 1.3 * (y_start - ybot)
    xs = x0 + sway * np.sin(p * 10 + phase)
    sizes = rng.uniform(36, 90, count) * (0.55 + 0.45 * np.abs(np.cos(p * 16 + phase)))
    picks = rng.integers(0, len(CONFETTI), count)
    rgba = np.column_stack([
        np.array([to_rgb(CONFETTI[k]) for k in picks]),
        np.full(count, np.clip((1 - p) / 0.25, 0, 1)),
    ])
    return np.column_stack([xs, ys]), sizes, rgba


def bar_colors(frame, n, vbase, vspan):
    colors = []
    lo, hi = frame["lo"], frame["hi"]
    for k in range(n):
        frac = (frame["arr"][k] - vbase) / vspan
        if k in frame["sorted"]:
            c = CMAP_SORTED(frac)[:3]
        elif lo is not None and not (lo <= k <= hi):
            c = mix(CMAP_ACTIVE(frac)[:3], to_rgb(PANEL), 0.74)   # waiting
        else:
            c = CMAP_ACTIVE(frac)[:3]
        colors.append(tuple(c))

    glow = set()

    def paint(k, hexcolor):
        colors[k] = to_rgb(hexcolor)
        glow.add(k)

    for m in frame["marks"]:
        if not m[4]:
            paint(m[0], m[1])
    for k in frame["swapped"]:
        paint(k, C_SWAP)
    for m in frame["marks"]:
        if m[4]:
            paint(m[0], m[1])

    w = frame["wave"]
    if w is not None:
        colors[w] = to_rgb(C_WAVE)
        glow.add(w)
        if w >= 1:
            colors[w - 1] = mix(colors[w - 1], to_rgb(C_WAVE), 0.45)
    return colors, glow


TEX = 8


def _make_tiles():
    rng = np.random.default_rng(42)

    def noisy(hexc, var=0.05):
        base = np.array(to_rgb(hexc))
        return np.clip(base + rng.uniform(-var, var, (TEX, TEX, 1)), 0, 1)

    def shade(t):
        t = t.copy()
        t[-1, :] *= 0.70                                  # dark bottom edge
        t[:, -1] *= 0.82                                  # dark right edge
        t[0, :] = np.minimum(1.0, t[0, :] * 1.10)         # light top edge
        return t

    tiles = {"dirt": [], "stone": [], "grass_side": [], "emerald": [], "moss": []}
    for _v in range(4):
        tiles["dirt"].append(shade(noisy(DIRT, 0.06)))

        st = noisy(STONE, 0.05)
        for _p in range(3):                               # darker pebbles
            r, c = rng.integers(0, TEX, 2)
            st[r, c] *= 0.72
        tiles["stone"].append(shade(st))

        g = noisy(DIRT, 0.06)                             # dirt with a grass fringe
        green = noisy(GRASS, 0.07)
        for c in range(TEX):
            d = int(rng.integers(2, 4))
            g[:d, c] = green[:d, c]
        tiles["grass_side"].append(shade(g))

        mo = noisy(MOSS, 0.06)
        for _p in range(4):
            r, c = rng.integers(0, TEX, 2)
            mo[r, c] *= 0.7
        tiles["moss"].append(shade(mo))
    for _v in range(2):
        e = noisy(EMERALD, 0.04)
        e[2:6, 2:6] = np.clip(e[2:6, 2:6] * 0.8 + 0.2, 0, 1)
        e[3:5, 3:5] = np.clip(e[3:5, 3:5] * 0.4 + 0.6, 0, 1)
        tiles["emerald"].append(shade(e))
    return tiles


TILES = _make_tiles()


def build_scene(data, frames, states, subtitle, spec):
    n = len(data)
    data_lo, data_hi = min(data), max(data)
    height_off = 1 - data_lo if data_lo < 1 else 0
    maxv = data_hi + height_off
    vbase, vspan = value_scale(data)
    has_aux = spec["aux"]
    fig_h = FIG_H_AUX if has_aux else FIG_H

    ROWS = int(min(32, max(8, maxv)))
    block_h = maxv / ROWS
    stone_rows = max(2, ROWS // 2)

    def rows_for(v):
        return max(1, int(round((v + height_off) * ROWS / maxv)))

    tex_cache = {}

    def column_tex(rows, theme):
        key = (rows, theme)
        if key not in tex_cache:
            tiles = []
            for r in range(rows):
                b = rows - 1 - r
                if theme == "sorted":
                    kind = "emerald" if r == 0 else "moss"
                elif r == 0:
                    kind = "grass_side"
                else:
                    kind = "stone" if b < stone_rows else "dirt"
                variants = TILES[kind]
                tiles.append(variants[(b * 5 + 1) % len(variants)])
            img = np.vstack(tiles)
            if theme == "waiting":
                img = img * 0.40 + np.array(to_rgb(PANEL)) * 0.25
            tex_cache[key] = img
        return tex_cache[key]

    aux_base = -1.10 * maxv
    y_top = 1.55 * maxv
    y_bot = (aux_base - 0.28 * maxv) if has_aux else -0.32 * maxv
    pad_x = max(0, 14 - n) / 2
    x_min, x_max = -0.9 - pad_x, n - 0.1 + pad_x

    fig, ax = plt.subplots(figsize=(FIG_W, fig_h))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    ux = (x_max - x_min) / (FIG_W * (AX_R - AX_L))
    uy = (y_top - y_bot) / (fig_h * (AX_T - AX_B))

    sky = np.array([mix(to_rgb("#0f1a47"), to_rgb("#5b86d6"), t)
                    for t in np.linspace(0, 1, 96)])[:, None, :]
    ax.imshow(sky, extent=(x_min, x_max, y_bot, y_top), origin="upper",
              aspect="auto", interpolation="bilinear", zorder=0.1)

    ax.axhline(0, color="#4d8f2a", lw=2.4, zorder=0.3)
    for frac in (0.25, 0.5, 0.75, 1.0):
        ax.axhline(frac * maxv, color="white", alpha=0.07, lw=0.8, zorder=0.3)

    if data_lo <= 0:
        zero_y = rows_for(0) * block_h
        ax.axhline(zero_y, color="white", alpha=0.5, lw=1.3, ls=(0, (4, 3)),
                   zorder=0.35)
        ax.text(x_min + 0.08, zero_y + 0.012 * maxv, "0", color=TEXT, fontsize=9,
                fontweight="bold", ha="left", va="bottom", zorder=0.9)

    if has_aux:
        panel_top = -0.42 * maxv
        ax.add_patch(Rectangle((x_min, y_bot), x_max - x_min, panel_top - y_bot,
                               color="#070b18", alpha=0.72, lw=0, zorder=0.4))
        ax.plot([x_min, x_max], [aux_base, aux_base], color="#3b4a7a", lw=2.0,
                zorder=0.45)
        ax.text(x_min + 0.15, panel_top - 0.03 * maxv,
                "HELPER BUFFER  (copy of the two halves being merged)",
                color=MUTED, fontsize=9.5, fontweight="bold", ha="left", va="top",
                zorder=0.9)

    crng = np.random.default_rng(5)
    cloud_n = 6
    cloud_x0 = crng.uniform(x_min, x_max, cloud_n)
    cloud_y = crng.uniform(1.30, 1.46, cloud_n) * maxv
    cloud_v = crng.uniform(0.15, 0.40, cloud_n)
    clouds = []
    for cy in cloud_y:
        w = float(crng.uniform(2.6, 4.2))
        base = Rectangle((0, cy), w, 0.05 * maxv, color="white", alpha=0.30,
                         lw=0, zorder=0.6)
        top = Rectangle((0, cy + 0.05 * maxv), 0.55 * w, 0.045 * maxv,
                        color="white", alpha=0.30, lw=0, zorder=0.6)
        ax.add_patch(base)
        ax.add_patch(top)
        clouds.append((base, top, w))
    cloud_span = (x_max - x_min) + 6

    band = Rectangle((0, y_bot), 1, y_top - y_bot, color="white",
                     alpha=0.10, zorder=0.5, linewidth=0)
    ax.add_patch(band)

    pline, = ax.plot([], [], color=C_PIVOT, lw=1.6, ls=(0, (5, 4)),
                     alpha=0.95, zorder=1.5)

    by = -0.285 * maxv
    bracket, = ax.plot([], [], color="#a5b4fc", lw=3, solid_capstyle="round",
                       zorder=1.5)

    def make_pointer():
        stem, = ax.plot([], [], lw=2.2, zorder=5.9, solid_capstyle="butt")
        m, = ax.plot([], [], marker="^", ls="", ms=15, mec="black", mew=1.2,
                     zorder=6, clip_on=False)
        tx = ax.text(0, 0, "", ha="center", va="top", fontsize=11.5,
                     fontweight="bold", color="#0b1020", zorder=6.1,
                     bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="black", lw=1.2))
        return stem, m, tx

    ptr_y = -0.045 * maxv
    row_y = [-0.085 * maxv, -0.150 * maxv, -0.215 * maxv]
    pointers = [make_pointer() for _ in range(3)]
    aptr_y = aux_base - 0.045 * maxv
    arow_y = [aux_base - 0.085 * maxv]
    apointers = [make_pointer() for _ in range(2)] if has_aux else []

    def draw_ptrs(artists, items, marker_y, rows):
        for idx, (stem, m, tx) in enumerate(artists):
            if idx < len(items):
                slot, col, txt, row = items[idx]
                ty = rows[row]
                m.set_data([slot], [marker_y])
                m.set_color(col)
                stem.set_data([slot, slot], [marker_y, ty])
                stem.set_color(col)
                tx.set_position((slot, ty))
                tx.set_text(txt)
                tx.get_bbox_patch().set_facecolor(col)
                tx.get_bbox_patch().set_visible(True)
                m.set_visible(True)
                stem.set_visible(True)
            else:
                m.set_visible(False)
                stem.set_visible(False)
                tx.set_text("")
                tx.get_bbox_patch().set_visible(False)

    # Comparison connector
    cmp_line, = ax.plot([], [], color=C_SCAN, lw=2.8, zorder=5.9,
                        solid_capstyle="round", solid_joinstyle="round")
    cmp_end_a, = ax.plot([], [], marker="v", ls="", ms=12, color=C_SCAN,
                         mec="black", mew=1.0, zorder=6, clip_on=False)
    cmp_end_b, = ax.plot([], [], marker="v", ls="", ms=12, color=C_PIVOT,
                         mec="black", mew=1.0, zorder=6, clip_on=False)
    cmp_text = ax.text(0, 0, "", ha="center", va="bottom", fontsize=12,
                       fontweight="bold", color="white", zorder=8.5, linespacing=1.35,
                       bbox=dict(boxstyle="round,pad=0.35", fc=BG, ec=C_SCAN,
                                 lw=2.2, alpha=0.96))
    cmp_artists = (cmp_line, cmp_end_a, cmp_end_b, cmp_text)
    for art in cmp_artists:
        art.set_visible(False)

    # Crane rail across the top, with two trolleys that ride along it
    rail_y = 1.23 * maxv
    ax.plot([x_min, x_max], [rail_y, rail_y], color="#4b5563", lw=6,
            solid_capstyle="butt", zorder=1.2)
    ax.plot([x_min, x_max], [rail_y, rail_y], color="#9ca3af", lw=1.2,
            ls=(0, (1.5, 3.5)), zorder=1.3)
    trolley_h = 0.05 * maxv
    trolley_y = rail_y - trolley_h - 0.002 * maxv
    head_w = BAR_W + 0.16
    cranes = []
    for _ in range(2):
        rope, = ax.plot([], [], color="#e5e7eb", lw=2.4, ls=(0, (1, 1)),
                        zorder=5.4, solid_capstyle="butt")
        trolley = Rectangle((0, trolley_y), 1.0, trolley_h, fc="#374151",
                            ec="#111827", lw=1.2, zorder=5.6)
        head = Rectangle((0, 0), head_w, 0.032 * maxv, fc="#9ca3af",
                         ec="#374151", lw=1.0, zorder=5.8)
        prong_l = Rectangle((0, 0), 0.07, 0.075 * maxv, fc="#9ca3af",
                            ec="#374151", lw=1.0, zorder=5.8)
        prong_r = Rectangle((0, 0), 0.07, 0.075 * maxv, fc="#9ca3af",
                            ec="#374151", lw=1.0, zorder=5.8)
        parts = (trolley, head, prong_l, prong_r)
        for p in parts:
            ax.add_patch(p)
            p.set_visible(False)
        rope.set_visible(False)
        cranes.append((rope, trolley, head, prong_l, prong_r))

    # Halos, block towers (one image per column) and a tint overlay
    heights0 = [v + height_off for v in data]
    halo_outer = ax.bar(range(n), heights0, width=GLOW_W + 0.22, color="white",
                        alpha=0.0, linewidth=0, zorder=1.8)
    halo_inner = ax.bar(range(n), heights0, width=GLOW_W - 0.04, color="white",
                        alpha=0.0, linewidth=0, zorder=2)
    imgs = []
    for k in range(n):
        r0 = rows_for(data[k])
        imgs.append(ax.imshow(column_tex(r0, "active"),
                              extent=(k - BAR_W / 2, k + BAR_W / 2, 0, r0 * block_h),
                              origin="upper", interpolation="nearest",
                              aspect="auto", zorder=3))
    bars = ax.bar(range(n), heights0, width=BAR_W, color=to_rgb(C_PIVOT),
                  edgecolor="none", linewidth=0, zorder=3.2)
    for rect in bars:
        rect.set_facecolor((*to_rgb(C_PIVOT), 0.0))

    # Helper-buffer towers and the "flyer" that hops from buffer to slot
    aimgs, abars, flyer = [], [], None
    if has_aux:
        for k in range(n):
            ai = ax.imshow(column_tex(1, "active"),
                           extent=(k - BAR_W / 2, k + BAR_W / 2, aux_base,
                                   aux_base + block_h * AUXS),
                           origin="upper", interpolation="nearest",
                           aspect="auto", zorder=3)
            ai.set_visible(False)
            aimgs.append(ai)
        abars = list(ax.bar(range(n), [block_h * AUXS] * n, bottom=aux_base,
                            width=BAR_W, color=to_rgb(C_PIVOT), edgecolor="none",
                            linewidth=0, zorder=3.2))
        for rect in abars:
            rect.set_facecolor((*to_rgb(C_PIVOT), 0.0))
            rect.set_visible(False)
        flyer = ax.imshow(column_tex(1, "active"),
                          extent=(0, 1, aux_base, aux_base + block_h * AUXS),
                          origin="upper", interpolation="nearest",
                          aspect="auto", zorder=5)
        flyer.set_visible(False)

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_bot, y_top)
    ax.set_autoscale_on(False)

    label_size = 9 if n <= 20 else 7
    label_fx = [pe.withStroke(linewidth=2.6, foreground="#000000")]
    labels, alabels = [], []
    if n <= 30:
        for k in range(n):
            lb = ax.text(k, 0, "", ha="center", va="bottom", color="white",
                         fontsize=label_size, fontweight="bold", zorder=6)
            lb.set_path_effects(label_fx)
            labels.append(lb)
            if has_aux:
                al = ax.text(k, aux_base, "", ha="center", va="bottom", color="white",
                             fontsize=label_size, fontweight="bold", zorder=6)
                al.set_path_effects(label_fx)
                alabels.append(al)

    sparks = ax.scatter([], [], marker="*", s=10, linewidths=0, zorder=7)
    confetti = ax.scatter([], [], marker="s", s=10, linewidths=0, zorder=7)

    fig.text(0.045, 0.952, f"{spec['title']}", color=TEXT,
             fontsize=22, fontweight="bold", ha="left", va="center")
    fig.text(0.045, 0.905, subtitle, color=MUTED, fontsize=10.5,
             ha="left", va="center")
    fig.text(0.965, 0.952, spec["complexity"], color=MUTED, fontsize=10,
             ha="right", va="center")

    caption = ax.text(0.5, 0.955, "", transform=ax.transAxes, ha="center",
                      va="top", color=TEXT, fontsize=13, zorder=8,
                      bbox=dict(boxstyle="round,pad=0.45", fc=CAPTION_BG,
                                ec="none", alpha=0.95))

    progress = Rectangle((0, 0.988), 0, 0.012, transform=ax.transAxes,
                         color="#8b5cf6", zorder=9, linewidth=0)
    ax.add_patch(progress)

    legend = [Patch(color=c, label=lbl) for c, lbl in spec["legend"]]
    leg = ax.legend(handles=legend, loc="upper center",
                    bbox_to_anchor=(0.5, -0.02), ncol=min(5, len(legend)),
                    frameon=False, fontsize=9, handlelength=1.2, columnspacing=1.4)
    for t in leg.get_texts():
        t.set_color(TEXT)

    fig.subplots_adjust(left=AX_L, right=AX_R, top=AX_T, bottom=AX_B)

    glow_pad = 0.012 * maxv
    no_pts = np.zeros((0, 2))

    def update(si, t=None):
        st = states[si]
        f = st["f"]
        if t is None:
            t = st["t0"]
        arr = f["arr"]
        lo, hi = f["lo"], f["hi"]
        sorted_set = f["sorted"]
        pos = [float(k) for k in range(n)]
        lift = [0.0] * n
        colors, glow = bar_colors(f, n, vbase, vspan)
        moving = set()
        tint = f["tint"]
        hidden = set(f["hidden"])
        piv = None
        for m in f["marks"]:
            if m[4]:
                piv = m[0]
                break

        def theme_of(k):
            if k in sorted_set:
                return "sorted"
            if lo is not None and not (lo <= k <= hi):
                return "waiting"
            return "active"

        tw = st["tween"]
        fly = None
        if tw and tw["type"] == "swap":
            x, y, te, prev, u = tw["x"], tw["y"], tw["te"], tw["prev"], tw["u"]
            arr = prev
            pos[x] = x + (y - x) * te
            pos[y] = y + (x - y) * te
            lift[x] = HOP_HI * maxv * np.sin(np.pi * u)    # pulled up and over
            lift[y] = HOP_LO * maxv * np.sin(np.pi * u)    # slides underneath
            # Colors belong to the bar that ends up in a slot, so swap them
            colors[x], colors[y] = colors[y], colors[x]
            gx, gy = x in glow, y in glow
            glow.discard(x)
            glow.discard(y)
            if gy:
                glow.add(x)
            if gx:
                glow.add(y)
            moving = {x, y}
            piv = None
        elif tw and tw["type"] == "fly":
            fly = tw
            hidden.add(tw["dst"])

        scale = [1.0] * n
        pop = st["pop"]
        if pop:
            scale[pop[0]] = 1 + 0.16 * np.sin(np.pi * pop[1]) * (1 - 0.3 * pop[1])

        pulse = 0.5 + 0.5 * np.sin(2 * np.pi * t / 0.8)
        tops = {}
        for k in range(n):
            rect = bars[k]
            if k in hidden:                               # slot waiting for a value
                imgs[k].set_visible(False)
                rect.set_x(pos[k] - BAR_W / 2)
                rect.set_y(0)
                rect.set_height(0.05 * maxv)
                rect.set_facecolor((1, 1, 1, 0.14))
                rect.set_zorder(3.2)
                halo_outer[k].set_alpha(0.0)
                halo_inner[k].set_alpha(0.0)
                if labels:
                    labels[k].set_text("")
                tops[k] = 0.0
                continue

            rows = rows_for(arr[k])
            h = rows * block_h * scale[k]
            y0 = lift[k]
            z = 4 if (k in glow or k in moving) else 3
            if moving and k == max(moving, key=lambda m: lift[m]):
                z = 5                                     # the pulled bar is on top

            img = imgs[k]
            img.set_visible(True)
            img.set_data(column_tex(rows, theme_of(k)))
            img.set_extent((pos[k] - BAR_W / 2, pos[k] + BAR_W / 2, y0, y0 + h))
            img.set_zorder(z)

            rect.set_x(pos[k] - BAR_W / 2)
            rect.set_y(y0)
            rect.set_height(h)
            if k in glow:
                rect.set_facecolor((*colors[k], 0.5))
            elif k in tint:
                rect.set_facecolor((*to_rgb(tint[k]), 0.34))
            else:
                rect.set_facecolor((*colors[k], 0.0))
            rect.set_zorder(z + 0.2)
            tops[k] = y0 + h

            lit = k in glow and f["wave"] is None     # no halo on the final sweep
            boost = 0.75 + 0.5 * pulse if k == piv else 1.0
            for halo, width, alpha, extra in (
                    (halo_outer[k], GLOW_W + 0.22, 0.11, 2.2 * glow_pad),
                    (halo_inner[k], GLOW_W - 0.04, 0.22, glow_pad)):
                halo.set_x(pos[k] - width / 2)
                halo.set_y(y0)
                halo.set_height(h + extra)
                halo.set_facecolor(colors[k])
                halo.set_alpha(min(0.5, alpha * boost) if lit else 0.0)
            if labels:
                bump = 0.075 * maxv if k in moving else 0.0
                labels[k].set_position((pos[k], y0 + h + 0.006 * maxv + bump))
                labels[k].set_text(str(arr[k]))

        holds = sorted(moving)
        for idx, (rope, trolley, head, prong_l, prong_r) in enumerate(cranes):
            if idx < len(holds):
                m = holds[idx]
                px, tp = pos[m], tops[m]
                trolley.set_xy((px - 0.5, trolley_y))
                rope.set_data([px, px], [trolley_y, tp + 0.044 * maxv])
                head.set_xy((px - head_w / 2, tp + 0.012 * maxv))
                prong_l.set_xy((px - BAR_W / 2 - 0.10, tp - 0.045 * maxv))
                prong_r.set_xy((px + BAR_W / 2 + 0.03, tp - 0.045 * maxv))
                for artist in (rope, trolley, head, prong_l, prong_r):
                    artist.set_visible(True)
            else:
                for artist in (rope, trolley, head, prong_l, prong_r):
                    artist.set_visible(False)

        atops = {}
        aux = f["aux"] or {}
        if has_aux:
            amcol = {m[0]: m[1] for m in f["amarks"]}
            amid = f["amid"]
            for k in range(n):
                if k in aux:
                    v = aux[k]
                    rows = rows_for(v)
                    h = rows * block_h * AUXS
                    aimgs[k].set_data(column_tex(rows, "active"))
                    aimgs[k].set_extent((k - BAR_W / 2, k + BAR_W / 2,
                                         aux_base, aux_base + h))
                    aimgs[k].set_visible(True)
                    rect = abars[k]
                    rect.set_height(h)
                    if k in amcol:
                        rect.set_facecolor((*to_rgb(amcol[k]), 0.5))
                    elif amid is not None:
                        rect.set_facecolor((*to_rgb(C_LEFT if k <= amid else C_RIGHT), 0.34))
                    else:
                        rect.set_facecolor((1, 1, 1, 0.0))
                    rect.set_visible(True)
                    atops[k] = aux_base + h
                    if alabels:
                        alabels[k].set_position((k, aux_base + h + 0.006 * maxv))
                        alabels[k].set_text(str(v))
                else:
                    aimgs[k].set_visible(False)
                    abars[k].set_visible(False)
                    if alabels:
                        alabels[k].set_text("")
            if fly:
                te = fly["te"]
                rows = rows_for(fly["val"])
                s = AUXS + (1 - AUXS) * te
                h = rows * block_h * s
                y0 = aux_base * (1 - te)
                fx_ = fly["src"] + (fly["dst"] - fly["src"]) * te
                flyer.set_data(column_tex(rows, "active"))
                flyer.set_extent((fx_ - BAR_W / 2, fx_ + BAR_W / 2, y0, y0 + h))
                flyer.set_visible(True)
            else:
                flyer.set_visible(False)

        msg = f["msg"]
        cm = f["cmp"]
        if cm and f["kind"] == "compare":
            aux_sp = cm["space"] == "aux"
            tp = atops if aux_sp else tops
            vals = aux if aux_sp else arr
            base = aux_base if aux_sp else 0.0
            A, B = cm["a"], cm["b"]
            va, vb = vals[A], vals[B]
            yes = cm["yes"]
            answered = st["phase"] == "answer"
            col = (C_LEFT if yes else C_NO) if answered else C_SCAN
            ly = max(tp.get(k, base) for k in range(min(A, B), max(A, B) + 1)) + 0.085 * maxv
            ya, yb = tp[A] + 0.075 * maxv, tp[B] + 0.075 * maxv
            cmp_line.set_data([A, A, B, B], [ya, ly, ly, yb])
            cmp_line.set_color(col)
            cmp_end_a.set_data([A], [ya])
            cmp_end_b.set_data([B], [yb])
            if not answered:
                txt = f"{va}  {cm['op']}  {vb}  ?"
            elif yes:
                txt = f"{va}  {cm['op']}  {vb}   YES\n{cm['yes_txt']}"
                msg = f"{va} {cm['op']} {vb}: {cm['yes_txt']}"
            else:
                txt = f"{va}  {cm['nop']}  {vb}   NO\n{cm['no_txt']}"
                msg = f"{va} {cm['nop']} {vb}: {cm['no_txt']}"
            cmp_text.set_text(txt)
            cmp_text.set_position(((A + B) / 2, ly + 0.012 * maxv))
            cmp_text.get_bbox_patch().set_edgecolor(col)
            for art in cmp_artists:
                art.set_visible(True)
        else:
            for art in cmp_artists:
                art.set_visible(False)

        in_range = lo is not None and f["wave"] is None
        if in_range:
            band.set_visible(True)
            band.set_x(lo - 0.5)
            band.set_width(hi - lo + 1)
            bracket.set_data([lo - 0.4, hi + 0.4], [by, by])
        else:
            band.set_visible(False)
            bracket.set_data([], [])

        if f["pline"] is not None:
            v = rows_for(f["arr"][f["pline"]]) * block_h
            x0 = (lo if lo is not None else 0) - 0.5
            x1 = (hi if hi is not None else n - 1) + 0.5
            pline.set_data([x0, x1], [v, v])
        else:
            pline.set_data([], [])

        show_ptrs = f["wave"] is None and f["kind"] != "final"
        items = [(m[0], m[1], m[2], m[3]) for m in f["marks"]] if show_ptrs else []
        draw_ptrs(pointers, items, ptr_y, row_y)
        if has_aux:
            aitems = [(m[0], m[1], m[2], 0) for m in f["amarks"]] if show_ptrs else []
            draw_ptrs(apointers, aitems, aptr_y, arow_y)

        fx = st["fx"]
        if fx and "bursts" in fx and fx["bursts"]:
            parts_ = [burst_particles(bx, by_, p, seed, col, ux, uy)
                      for bx, by_, p, seed, col in fx["bursts"]]
            sparks.set_offsets(np.vstack([q[0] for q in parts_]))
            sparks.set_sizes(np.concatenate([q[1] for q in parts_]))
            sparks.set_facecolor(np.vstack([q[2] for q in parts_]))
            sparks.set_visible(True)
        else:
            sparks.set_offsets(no_pts)
            sparks.set_visible(False)
        if fx and "confetti" in fx:
            off, sz, rgba = confetti_particles(fx["confetti"], x_min, x_max, y_top, y_bot)
            confetti.set_offsets(off)
            confetti.set_sizes(sz)
            confetti.set_facecolor(rgba)
            confetti.set_visible(True)
        else:
            confetti.set_offsets(no_pts)
            confetti.set_visible(False)

        for ci, (base_, top_, w) in enumerate(clouds):
            cx = (cloud_x0[ci] + t * cloud_v[ci] - x_min + 3) % cloud_span + x_min - 3
            base_.set_x(cx)
            top_.set_x(cx + 0.2 * w)

        caption.set_text(msg)
        progress.set_width((st["fi"] + 1) / len(frames))

    return fig, update


def play_live(fig, update, states, total_s, player):

    starts = [st["t0"] for st in states]
    clock = {"t0": None, "paused": False, "pause_t": 0.0, "si": -1, "drawn": -1.0}

    def tick(_):
        if clock["t0"] is None:
            clock["t0"] = time.perf_counter()
            if player:
                player.play(0.0)
        if clock["paused"]:
            return []
        t = time.perf_counter() - clock["t0"]
        if t >= total_s:
            update(len(states) - 1, total_s)
            anim.event_source.stop()
            return []
        si = bisect.bisect_right(starts, t) - 1
        if si != clock["si"] or t - clock["drawn"] > 0.045:
            clock["si"], clock["drawn"] = si, t
            update(si, t)
        return []

    anim = FuncAnimation(fig, tick, frames=itertools.count(), interval=15,
                         blit=False, cache_frame_data=False)

    def on_key(event):
        if event.key != " " or clock["t0"] is None:
            return
        if not clock["paused"]:
            clock["paused"] = True
            clock["pause_t"] = time.perf_counter() - clock["t0"]
            if player:
                player.stop()
        else:
            clock["t0"] = time.perf_counter() - clock["pause_t"]
            clock["paused"] = False
            if player:
                player.play(clock["pause_t"])

    fig.canvas.mpl_connect("key_press_event", on_key)
    fig.canvas.mpl_connect("close_event", lambda e: player and player.stop())
    plt.show()
    return anim


def save_gif(fig, update, states, path, dpi):
    from PIL import Image

    fig.set_dpi(dpi)
    images, durations = [], []
    for si, st in enumerate(states):
        update(si)
        fig.canvas.draw()
        rgba = np.asarray(fig.canvas.buffer_rgba()).copy()
        img = Image.fromarray(rgba).convert("RGB")
        img = img.quantize(colors=128, method=Image.Quantize.MEDIANCUT,
                           dither=Image.Dither.NONE)
        images.append(img)
        durations.append(max(20, int(round(st["dur_s"] * 1000))))
    images[0].save(path, save_all=True, append_images=images[1:],
                   duration=durations, loop=0, optimize=False, disposal=2)


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def save_mp4(fig, update, states, total_s, wav_path, out, fps, dpi):
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        sys.exit("ffmpeg was not found. Install ffmpeg (or `pip install imageio-ffmpeg`) "
                 "to export MP4, or use --save something.gif for a silent GIF.")
    fig.set_dpi(dpi)
    fig.canvas.draw()
    w, h = fig.canvas.get_width_height()
    cmd = [ffmpeg, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-r", str(fps),
           "-i", "-"]
    if wav_path:
        cmd += ["-i", wav_path]
    cmd += ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
            "-preset", "veryfast"]
    if wav_path:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += [out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    starts = [st["t0"] for st in states]
    n_frames = int((total_s + 1.5) * fps)
    for k in range(n_frames):
        t = k / fps
        si = min(len(states) - 1, max(0, bisect.bisect_right(starts, t) - 1))
        update(si, t)
        fig.canvas.draw()
        proc.stdin.write(np.asarray(fig.canvas.buffer_rgba()).tobytes())
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        sys.exit("ffmpeg failed while writing the video.")


def main():
    ap = argparse.ArgumentParser(
        description="Animated sorting visualizer with sound: bubble, insertion, "
                    "selection, merge and quick sort")
    ap.add_argument("--algo", choices=list(ALGOS),
                    help="which algorithm to show (asked in the terminal if omitted)")
    ap.add_argument("--numbers", metavar="LIST",
                    help='numbers to sort, e.g. "5 -3 8 1" (skips the numbers prompt)')
    ap.add_argument("--size", type=int, default=25,
                    help="number of bars for random data (default 25)")
    ap.add_argument("--mode", default="random",
                    choices=["random", "sorted", "reversed", "few-unique", "mixed"],
                    help="random-data pattern; mixed includes negatives (default random)")
    ap.add_argument("--pivot", default="last", choices=["last", "random", "median"],
                    help="pivot strategy, quick sort only (default last)")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="playback speed multiplier; 0.5 = half speed (default 1.0)")
    ap.add_argument("--tween", type=int, default=8,
                    help="in-between frames for swap hops, 0 disables (default 8)")
    ap.add_argument("--seed", type=int, default=7, help="random seed for reproducibility")
    ap.add_argument("--mute", action="store_true", help="turn the sound off")
    ap.add_argument("--save", metavar="FILE", help="export to FILE.mp4 (with sound) or FILE.gif (silent)")
    ap.add_argument("--wav", metavar="FILE.wav", help="export just the sound track")
    ap.add_argument("--fps", type=int, default=30, help="MP4 frame rate (default 30)")
    ap.add_argument("--dpi", type=int, default=None,
                    help="export resolution (default 110 for MP4, 72 for GIF)")
    ap.add_argument("--show", action="store_true", help="also open a window when exporting")
    args = ap.parse_args()

    if args.size < 2:
        ap.error("--size must be at least 2")
    if args.speed <= 0:
        ap.error("--speed must be positive")
    ext = os.path.splitext(args.save)[1].lower() if args.save else ""
    if args.save and ext not in (".mp4", ".gif"):
        ap.error("--save needs a .mp4 or .gif file name")

    random.seed(args.seed)

    algo = args.algo or ask_user_algo()
    spec = ALGOS[algo]

    if args.numbers:
        try:
            data = parse_numbers(args.numbers)
        except ValueError as exc:
            ap.error(f"--numbers: {exc}")
    else:
        data = ask_user_numbers()
    if data is None:
        data = make_data(args.size, args.mode, args.seed)
    else:
        args.size = len(data)

    if algo == "quick":
        frames = spec["record"](data, args.pivot)
    else:
        frames = spec["record"](data)
    states = expand_states(frames, max(0, args.tween))
    total_s = assign_times(states, args.speed)
    last = frames[-1]
    print(f"{spec['title']}: recorded {len(frames)} steps "
          f"({last['comparisons']} comparisons, {last['moves']} {spec['move']}); "
          f"animation length about {total_s:.0f}s at speed {args.speed}")

    samples = None
    if not args.mute:
        samples = synth_audio(frames, states)
    if args.wav:
        if samples is None:
            ap.error("--wav cannot be combined with --mute")
        write_wav(args.wav, samples)
        print(f"Wrote sound track to {args.wav}")
        if not args.save and not args.show:
            return

    subtitle = f"n = {args.size}"
    if algo == "quick":
        subtitle += f"   |   pivot: {args.pivot}"
    fig, update = build_scene(data, frames, states, subtitle, spec)

    if args.save:
        if ext == ".mp4":
            wav_path = None
            tmp_wav = None
            if samples is not None:
                tmp_wav = args.wav or os.path.join(tempfile.gettempdir(),
                                                   f"sv_track_{os.getpid()}.wav")
                if not args.wav:
                    write_wav(tmp_wav, samples)
                wav_path = tmp_wav
            print(f"Rendering {args.save} at {args.fps} fps... this can take a minute or two")
            save_mp4(fig, update, states, total_s, wav_path, args.save,
                     args.fps, args.dpi or 110)
            if tmp_wav and not args.wav:
                os.remove(tmp_wav)
        else:
            print(f"Saving {args.save} ({len(states)} frames). GIFs cannot carry sound; "
                  f"use .mp4 for video with audio.")
            save_gif(fig, update, states, args.save, args.dpi or 72)
        print("Done.")
        if not args.show:
            return

    player = None
    if samples is not None:
        player = AudioPlayer(samples)
        if not player.available:
            print("No audio backend found, so playing silently. "
                  "Try: pip install sounddevice   (or use --save file.mp4)")
            player = None
    play_live(fig, update, states, total_s, player)


if __name__ == "__main__":
    main()