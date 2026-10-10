"""Render a video from an edit decision list (EDL).

Each retained range is re-encoded with millisecond-accurate cuts and short
audio fades, then the resulting segments are concatenated without another
encode pass.

Encoder policy:
  - auto + preview/final: use NVENC when available, otherwise CPU.
  - cpu: libx264/libx265, two encoder threads per job.
  - nvenc: h264_nvenc/hevc_nvenc, multipass fullres for final.

Defaults (tuned on this workstation, 2026-09-28)
  --encoder   auto     resolves to nvenc here
  --workers   2        two segments encoded in parallel, both backends
  --nvenc-preset p5    for final, p4 for preview
  --priority  below    ffmpeg children run at BELOW_NORMAL_PRIORITY_CLASS

Why workers=2 and preset=p5: every segment decodes the source in software, so
the CPU cost is dominated by decode rather than by the encoder. Two parallel
jobs finish the same total work in about half the wall time without raising
total CPU consumption (measured 86 -> 55 CPU-seconds per 10-segment sample),
and p5 is ~1.45x faster than p7 with no visible loss on screencast content
(SSIM 0.99970 vs 0.99978, PSNR 55.8 vs 57.2 dB, worst single frame >= 0.9993).
Combined effect measured at 2.07x. p5 also produces ~5% larger files at the
same CQ, so it trades size for time, not both.

Usage:
    python helpers/render.py <video> <edl.json> -o output.mp4
    python helpers/render.py <video> <edl.json> -o preview.mp4 --preview
    python helpers/render.py <video> <edl.json> -o output.mp4 --encoder nvenc

Fallback when something goes wrong - each flag is independent:
    --workers 1          NVENC session limit ("OpenEncodeSessionEx failed"),
                         GPU driver errors, or the machine needs headroom
    --nvenc-preset p7    maximum quality, ~1.45x slower than p5
    --priority normal    let ffmpeg compete for CPU normally
    --encoder cpu        force libx264/libx265 when NVENC is unavailable
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

CPU_THREADS = 2
# Both backends decode the source in software, so the CPU cost is dominated by
# decode, not by the encoder. Two parallel jobs finish the same total work in
# about half the wall time without increasing total CPU consumption.
MAX_WORKERS = 2
DEFAULT_WORKERS = 2
NVENC_PRESETS = ("p1", "p2", "p3", "p4", "p5", "p6", "p7")
NVENC_PRESET_FINAL = "p5"
NVENC_PRESET_PREVIEW = "p4"
DEFAULT_PRIORITY = "below"


class SourceInfo:
    """Metadata extracted from the source video via ffprobe."""

    def __init__(
        self,
        width: int,
        height: int,
        fps: float,
        pix_fmt: str,
        vbitrate: int,
    ):
        self.width = width
        self.height = height
        self.fps = fps
        self.pix_fmt = pix_fmt
        self.vbitrate = vbitrate

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"


def require_ffmpeg_tools() -> None:
    """Fail early with a clear message when FFmpeg is not configured."""
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        sys.exit(
            "Missing required executable(s): "
            + ", ".join(missing)
            + ". Install FFmpeg and add it to PATH."
        )


def ffmpeg_has_encoder(encoder: str) -> bool:
    """Return whether the current FFmpeg build exposes an encoder."""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    return out.returncode == 0 and encoder in out.stdout


def priority_flags(priority: str) -> int:
    """Map a priority name to Windows creation flags (0 elsewhere).

    Running ffmpeg below normal priority keeps the desktop responsive while a
    render is in flight, and costs no measurable speed when the machine is
    otherwise idle. On POSIX the result is always 0, so callers can pass it
    through unconditionally.
    """
    if os.name != "nt" or priority != "below":
        return 0
    return getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


def resolve_encoder_backend(requested: str, mode: str, codec: str) -> str:
    """Resolve auto/cpu/nvenc without silently overriding explicit NVENC."""
    nvenc_name = "hevc_nvenc" if codec == "h265" else "h264_nvenc"

    if requested == "cpu":
        return "cpu"
    if requested == "nvenc":
        if not ffmpeg_has_encoder(nvenc_name):
            sys.exit(
                f"FFmpeg encoder '{nvenc_name}' is unavailable. "
                "Install an FFmpeg build with NVENC support or use --encoder cpu."
            )
        return "nvenc"

    if ffmpeg_has_encoder(nvenc_name):
        return "nvenc"
    return "cpu"


def probe_source(video: Path) -> SourceInfo:
    """Probe source resolution, frame rate, pixel format, and bitrate."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,avg_frame_rate,pix_fmt,bit_rate",
        "-show_entries", "format=bit_rate",
        "-of", "json",
        str(video),
    ]
    out = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        errors="replace",
        check=True,
    )
    data = json.loads(out.stdout)
    streams = data.get("streams", [])
    if not streams:
        sys.exit(f"no video stream found in {video}")

    stream = streams[0]
    width = int(stream["width"])
    height = int(stream["height"])
    pix_fmt = stream.get("pix_fmt", "yuv420p")

    def parse_fps(value: str) -> float:
        numerator, denominator = value.split("/")
        return float(numerator) / float(denominator)

    average = stream.get("avg_frame_rate", "0/1")
    raw = stream.get("r_frame_rate", "30/1")
    fps = parse_fps(average) if parse_fps(average) > 0 else parse_fps(raw)

    vbitrate = 0
    if stream.get("bit_rate"):
        vbitrate = int(stream["bit_rate"])
    elif data.get("format", {}).get("bit_rate"):
        vbitrate = int(data["format"]["bit_rate"])

    return SourceInfo(width, height, fps, pix_fmt, vbitrate)


def build_encode_params(
    src: SourceInfo,
    mode: str,
    codec: str,
    backend: str,
    nvenc_preset: str | None = None,
) -> dict:
    """Build CPU or NVENC parameters for preview/final output.

    `nvenc_preset` overrides the default preset (p5 final / p4 preview); pass
    "p7" to buy back the last bit of quality at ~1.45x the encode time.
    """
    if mode == "preview":
        if src.height > 720:
            scale_vf = "scale=-2:720"
        elif src.width > 1280:
            scale_vf = "scale=1280:-2"
        else:
            scale_vf = ""
    else:
        scale_vf = ""

    maxrate = int(src.vbitrate * 1.5) if src.vbitrate else 20_000_000
    bufsize = maxrate * 2

    if backend == "nvenc":
        vcodec = "hevc_nvenc" if codec == "h265" else "h264_nvenc"
        cq = (
            ("20" if mode == "final" else "25")
            if codec == "h265"
            else ("18" if mode == "final" else "23")
        )
        preset = nvenc_preset or (
            NVENC_PRESET_FINAL if mode == "final" else NVENC_PRESET_PREVIEW
        )
        multipass = "fullres" if mode == "final" else "qres"
        video_args = [
            "-c:v", vcodec,
            "-preset", preset,
            "-tune", "hq",
            "-multipass", multipass,
            "-rc", "vbr",
            "-cq", cq,
            "-b:v", "0",
            "-maxrate", str(maxrate),
            "-bufsize", str(bufsize),
        ]
        quality = f"CQ {cq}, preset {preset}, {multipass}"
    else:
        vcodec = "libx265" if codec == "h265" else "libx264"
        crf = (
            ("20" if mode == "final" else "24")
            if codec == "h265"
            else ("18" if mode == "final" else "23")
        )
        preset = "medium" if mode == "final" else "veryfast"
        video_args = [
            "-c:v", vcodec,
            "-preset", preset,
            "-crf", crf,
            "-maxrate", str(maxrate),
            "-bufsize", str(bufsize),
            "-threads", str(CPU_THREADS),
        ]
        if codec == "h265":
            video_args.extend(["-x265-params", f"pools={CPU_THREADS}"])
        quality = f"CRF {crf}, preset {preset}, {CPU_THREADS} threads"

    return {
        "backend": backend,
        "vcodec": vcodec,
        "video_args": video_args,
        "quality": quality,
        "scale_vf": scale_vf,
        "fps": src.fps,
        "maxrate": maxrate,
    }


def run(cmd: list[str], quiet: bool = False, creationflags: int = 0) -> None:
    """Run a command and preserve useful FFmpeg diagnostics on failure."""
    if not quiet:
        display = " ".join(str(part) for part in cmd[:8])
        if len(cmd) > 8:
            display += " …"
        print(f"  $ {display}")

    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        check=False,
        creationflags=creationflags,
    )
    if result.returncode != 0:
        details = "\n".join(result.stderr.splitlines()[-20:])
        raise RuntimeError(
            f"command failed with exit code {result.returncode}: "
            f"{' '.join(str(part) for part in cmd[:4])}\n{details}"
        )


def ffprobe_duration(video: Path) -> float:
    """Return video duration in seconds."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video),
        ],
        capture_output=True,
        text=True,
        errors="replace",
        check=True,
    )
    return float(out.stdout.strip())


def extract_segment(
    source: Path,
    seg_start: float,
    seg_end: float,
    out_path: Path,
    enc: dict,
) -> None:
    """Extract and encode one retained EDL range."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    duration = seg_end - seg_start
    if duration <= 0:
        raise ValueError(f"invalid segment duration: {seg_start} -> {seg_end}")

    fade_duration = min(0.03, duration / 2)
    fade_out_start = max(0.0, duration - fade_duration)
    af = (
        f"afade=t=in:st=0:d={fade_duration:.3f},"
        f"afade=t=out:st={fade_out_start:.3f}:d={fade_duration:.3f}"
    )

    vf_parts = []
    if enc["scale_vf"]:
        vf_parts.append(enc["scale_vf"])
    vf_parts.append("setsar=1")
    vf = ",".join(vf_parts)

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{seg_start:.3f}",
        "-i", str(source),
        "-to", f"{duration:.3f}",
        "-vf", vf,
        "-af", af,
        *enc["video_args"],
        "-pix_fmt", "yuv420p",
        "-r", f"{enc['fps']:.4f}",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-movflags", "+faststart",
        str(out_path),
    ]
    run(cmd, quiet=True, creationflags=enc.get("creationflags", 0))


def extract_all_segments(
    edl: list[dict],
    source: Path,
    work_dir: Path,
    enc: dict,
    workers: int,
) -> list[Path]:
    """Extract all EDL ranges with bounded concurrency and preserved order."""
    seg_dir = work_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)

    seg_meta = []
    for index, entry in enumerate(edl):
        start = float(entry["start"])
        end = float(entry["end"])
        if end <= start:
            sys.exit(f"invalid EDL segment {index}: {start} -> {end}")
        out_path = seg_dir / f"seg_{index:04d}.mp4"
        text = entry.get("text", "")
        preview = text[:50] + ("..." if len(text) > 50 else "")
        seg_meta.append((start, end, end - start, out_path, preview))

    print(f"extracting {len(edl)} segment(s) → segments/")
    for index, (start, end, duration, _, preview) in enumerate(seg_meta):
        print(
            f"  [{index:04d}] {start:8.3f} → {end:8.3f}  "
            f"({duration:5.2f}s)  {preview}"
        )

    worker_count = min(len(seg_meta), workers)
    paths: list[Path | None] = [None] * len(seg_meta)
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        future_to_index = {}
        for index, (start, end, _, out_path, _) in enumerate(seg_meta):
            future = pool.submit(
                extract_segment, source, start, end, out_path, enc
            )
            future_to_index[future] = index

        for future in as_completed(future_to_index):
            index = future_to_index[future]
            future.result()
            paths[index] = seg_meta[index][3]

    return paths  # type: ignore[return-value]


def concat_segments(
    segment_paths: list[Path],
    out_path: Path,
) -> None:
    """Concatenate encoded segments without another encode pass."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        safe_paths = []
        for index, source in enumerate(segment_paths):
            destination = tmp_dir / f"seg_{index:04d}.mp4"
            shutil.copy2(str(source), str(destination))
            safe_paths.append(destination)

        concat_list = tmp_dir / "concat.txt"
        concat_list.write_text(
            "".join(f"file '{path}'\n" for path in safe_paths),
            encoding="utf-8",
        )

        tmp_out = tmp_dir / "concat_out.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-movflags", "+faststart",
            str(tmp_out),
        ]
        print(f"concat → {out_path.name}")
        run(cmd, quiet=True)
        shutil.move(str(tmp_out), str(out_path))


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a video from an EDL")
    ap.add_argument("video", type=Path, help="Source video file")
    ap.add_argument("edl", type=Path, help="Path to edl.json")
    ap.add_argument(
        "-o", "--output",
        type=Path,
        required=True,
        help="Output video path",
    )
    ap.add_argument(
        "--preview",
        action="store_true",
        help="Preview mode: 720p maximum and faster quality settings.",
    )
    ap.add_argument(
        "--codec",
        choices=["h264", "h265"],
        default="h264",
        help="Video codec (default: h264).",
    )
    ap.add_argument(
        "--encoder",
        choices=["auto", "cpu", "nvenc"],
        default="auto",
        help=(
            "Encoding backend. auto uses NVENC for preview and final output "
            "when available, otherwise CPU (default: auto)."
        ),
    )
    ap.add_argument(
        "--workers",
        type=int,
        choices=range(1, MAX_WORKERS + 1),
        default=DEFAULT_WORKERS,
        metavar="{1,2}",
        help=(
            "Concurrent segment jobs, both backends "
            f"(default: {DEFAULT_WORKERS}, max: {MAX_WORKERS}). "
            "Drop to 1 if NVENC session limits or GPU driver errors appear."
        ),
    )
    ap.add_argument(
        "--nvenc-preset",
        choices=NVENC_PRESETS,
        default=None,
        help=(
            "Override the NVENC preset. Default: "
            f"{NVENC_PRESET_FINAL} for final, {NVENC_PRESET_PREVIEW} for "
            "preview. Use p7 for maximum quality at ~1.45x the encode time."
        ),
    )
    ap.add_argument(
        "--priority",
        choices=["normal", "below"],
        default=DEFAULT_PRIORITY,
        help=(
            "Priority for ffmpeg children, Windows only "
            f"(default: {DEFAULT_PRIORITY}). 'below' keeps the desktop "
            "responsive during a render at no measurable speed cost."
        ),
    )
    ap.add_argument(
        "--keep-segments",
        action="store_true",
        help="Keep segment files. Preview mode keeps them by default.",
    )
    args = ap.parse_args()

    source = args.video.resolve()
    edl_path = args.edl.resolve()
    out_path = args.output.resolve()

    if not source.exists():
        sys.exit(f"source video not found: {source}")
    if not edl_path.exists():
        sys.exit(f"EDL not found: {edl_path}")

    edl = json.loads(edl_path.read_text(encoding="utf-8"))
    if not isinstance(edl, list) or not edl:
        sys.exit("edl.json must be a non-empty JSON array")

    require_ffmpeg_tools()
    mode = "preview" if args.preview else "final"
    backend = resolve_encoder_backend(args.encoder, mode, args.codec)
    workers = min(args.workers, MAX_WORKERS)

    src = probe_source(source)
    enc = build_encode_params(src, mode, args.codec, backend, args.nvenc_preset)
    enc["creationflags"] = priority_flags(args.priority)

    mbps = (
        f"{src.vbitrate / 1_000_000:.1f} Mb/s"
        if src.vbitrate
        else "unknown"
    )
    cap_mbps = f"{enc['maxrate'] / 1_000_000:.1f} Mb/s"

    print(f"source:   {source.name}")
    print(f"  resolution: {src.resolution}")
    print(f"  fps:        {src.fps:.2f}")
    print(f"  pix_fmt:    {src.pix_fmt}")
    print(f"  vbitrate:   {mbps}")
    print(f"segments: {len(edl)}")
    print(f"encoder:  {backend} ({enc['vcodec']})")
    print(f"quality:  {mode} ({enc['quality']}, maxrate {cap_mbps})")
    print(f"workers:  {workers}")
    print(f"priority: {args.priority}")
    if enc["scale_vf"]:
        print(f"scale:    {enc['scale_vf']}")
    else:
        print("scale:    source resolution")
    print()

    work_dir = edl_path.parent
    segment_paths = extract_all_segments(
        edl, source, work_dir, enc, workers
    )
    concat_segments(segment_paths, out_path)

    if not args.keep_segments and not args.preview:
        seg_dir = work_dir / "segments"
        if seg_dir.exists():
            shutil.rmtree(seg_dir)
            print(f"cleaned: {seg_dir.name}/")

    if not out_path.exists():
        sys.exit("output file was not created")

    size_mb = out_path.stat().st_size / (1024 * 1024)
    duration = ffprobe_duration(out_path)
    expected = sum(
        float(entry["end"]) - float(entry["start"]) for entry in edl
    )
    out_info = probe_source(out_path)
    print(f"\ndone: {out_path}")
    print(f"  duration:   {duration:.2f}s (expected ≈ {expected:.2f}s)")
    print(f"  resolution: {out_info.resolution}")
    print(f"  size:       {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
