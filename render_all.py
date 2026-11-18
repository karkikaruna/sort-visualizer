
import argparse
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ALL = ["bubble", "insertion", "selection", "merge", "quick"]


def main():
    ap = argparse.ArgumentParser(description="Render every sorting algorithm to MP4")
    ap.add_argument("--script", default="sorting_visualizer.py",
                    help="your visualizer file (default sorting_visualizer.py)")
    ap.add_argument("--algos", nargs="+", choices=ALL, default=ALL)
    ap.add_argument("--size", type=int, default=25, help="random bars (default 25)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--numbers", help='your own numbers, e.g. "5 -3 8 1"')
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--dpi", type=int, default=None, help="video resolution (default 110)")
    ap.add_argument("--pivot", default="last", choices=["last", "random", "median"])
    ap.add_argument("--out", default="videos", help="output folder (default ./videos)")
    ap.add_argument("--jobs", type=int, default=2,
                    help="videos to render at the same time (default 2)")
    args = ap.parse_args()

    if not os.path.isfile(args.script):
        sys.exit(f"Cannot find {args.script}. Put this file next to your visualizer or "
                 f"pass --script path/to/it.py")
    os.makedirs(args.out, exist_ok=True)

    if args.numbers:
        numbers = args.numbers
    else:                       # one shared dataset for every algorithm
        data = list(range(1, args.size + 1))
        random.Random(args.seed).shuffle(data)
        numbers = " ".join(map(str, data))
    print(f"Input: {numbers}\n")

    def render(algo):
        out = os.path.join(args.out, f"{algo}.mp4")
        cmd = [sys.executable, args.script, "--algo", algo, "--numbers", numbers,
               "--speed", str(args.speed), "--fps", str(args.fps),
               "--pivot", args.pivot, "--seed", str(args.seed), "--save", out]
        if args.dpi:
            cmd += ["--dpi", str(args.dpi)]
        t0 = time.time()
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True)
        ok = res.returncode == 0 and os.path.isfile(out)
        print(f"  {'done  ' if ok else 'FAILED'} {algo:<9} {time.time() - t0:5.0f}s  {out}",
              flush=True)
        if not ok:
            print(res.stdout[-1500:])
        return ok

    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        results = list(pool.map(render, args.algos))

    print(f"\n{sum(results)}/{len(results)} videos saved in ./{args.out}/")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()