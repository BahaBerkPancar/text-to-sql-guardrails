#!/usr/bin/env python3
"""Record the static demo against an already-running API using system Chrome."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib import parse, request

DEFAULT_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
DEFAULT_FFMPEG = Path("/opt/homebrew/bin/ffmpeg")
ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class DemoState:
    slug: str
    sql: str


STATES = (
    DemoState(
        "query",
        "SELECT status, COUNT(*) AS order_count FROM orders "
        "GROUP BY status ORDER BY status",
    ),
    DemoState("denied-column", "SELECT email FROM customers"),
    DemoState("whole-row", "SELECT id AS c FROM customers AS c ORDER BY c"),
    DemoState("stacked-drop", "SELECT 1; DROP TABLE orders"),
    DemoState("pg-sleep", "SELECT pg_sleep(5)"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record the demo page. The API must already be running.",
    )
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs")
    parser.add_argument("--chrome", type=Path, default=DEFAULT_CHROME)
    parser.add_argument("--ffmpeg", type=Path, default=DEFAULT_FFMPEG)
    parser.add_argument("--seconds-per-state", type=float, default=3.6)
    return parser.parse_args()


def require_executable(path: Path, name: str) -> None:
    if not path.is_file():
        raise SystemExit(f"{name} was not found at {path}")


def check_server(base_url: str) -> None:
    health_url = parse.urljoin(f"{base_url.rstrip('/')}/", "health")
    try:
        with request.urlopen(health_url, timeout=5) as response:
            if response.status != 200:
                raise SystemExit(f"API health check returned HTTP {response.status}")
    except OSError as error:
        raise SystemExit(
            f"API is not running at {base_url}. Start it before recording: {error}",
        ) from error


def capture_state(
    chrome: Path,
    base_url: str,
    profile_dir: Path,
    state: DemoState,
    output: Path,
) -> None:
    fragment = parse.urlencode(
        {"sql": state.sql, "run": "1", "capture": "1"},
        quote_via=parse.quote,
    )
    page_url = f"{base_url.rstrip('/')}/#{fragment}"
    command = [
        str(chrome),
        "--headless=new",
        "--disable-gpu",
        "--disable-default-apps",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--metrics-recording-only",
        "--disable-features=OptimizationHints,MediaRouter",
        "--run-all-compositor-stages-before-draw",
        "--window-size=1280,860",
        "--force-device-scale-factor=1",
        f"--user-data-dir={profile_dir}",
        "--virtual-time-budget=3500",
        f"--screenshot={output}",
        page_url,
    ]
    # Own process group, so Chrome's helper processes die with it on timeout.
    process = subprocess.Popen(command, start_new_session=True)
    try:
        returncode = process.wait(timeout=30)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    if returncode != 0:
        raise SystemExit(f"Chrome exited with {returncode}")
    if not output.is_file():
        raise SystemExit(f"Chrome did not create {output}")


def write_concat_file(
    path: Path,
    frames: list[Path],
    seconds_per_state: float,
) -> None:
    lines: list[str] = []
    for frame in frames:
        lines.extend((f"file '{frame}'", f"duration {seconds_per_state}"))
    lines.append(f"file '{frames[-1]}'")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def assemble_gif(ffmpeg: Path, concat_file: Path, output: Path) -> None:
    filters = (
        "fps=10,scale=900:-1:flags=lanczos,split[frames][palette_source];"
        "[palette_source]palettegen=max_colors=128:stats_mode=diff[palette];"
        "[frames][palette]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle"
    )
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-vf",
        filters,
        str(output),
    ]
    subprocess.run(command, check=True, timeout=90)


def main() -> None:
    args = parse_args()
    require_executable(args.chrome, "Chrome")
    require_executable(args.ffmpeg, "ffmpeg")
    if args.seconds_per_state <= 0:
        raise SystemExit("--seconds-per-state must be positive")
    check_server(args.url)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="t2s-demo-") as temporary:
        temporary_dir = Path(temporary)
        profile_dir = temporary_dir / "chrome-profile"
        frames: list[Path] = []
        for index, state in enumerate(STATES):
            frame = temporary_dir / f"{index:02d}-{state.slug}.png"
            capture_state(args.chrome, args.url, profile_dir, state, frame)
            frames.append(frame)

        shutil.copy2(frames[0], args.output_dir / "screenshot-query.png")
        shutil.copy2(frames[1], args.output_dir / "screenshot-blocked.png")
        concat_file = temporary_dir / "frames.txt"
        write_concat_file(concat_file, frames, args.seconds_per_state)
        gif_path = args.output_dir / "demo.gif"
        assemble_gif(args.ffmpeg, concat_file, gif_path)

    size_mib = gif_path.stat().st_size / (1024 * 1024)
    duration = len(STATES) * args.seconds_per_state
    print(f"Recorded {gif_path} ({duration:.1f} s, {size_mib:.2f} MiB)")


if __name__ == "__main__":
    main()
