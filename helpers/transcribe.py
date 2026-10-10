"""Transcribe a video with DashScope ASR at word-level precision.

Pipeline:
  1. Extract lossless mono 16kHz FLAC audio via ffmpeg.
  2. Upload to DashScope via Files.upload() → get signed OSS URL.
  3. Call Transcription.async_call(model='fun-asr') with the URL.
  4. Poll via Transcription.wait() until done.
  5. Parse results into artifacts:
     - raw_timestamps.json  (sentences with nested word timestamps)
     - clean_transcript.txt ([ID: N] lines for the LLM)
     - chunks/chunk_NNN.txt (only when the transcript exceeds 800 sentences)

Cached: if raw_timestamps.json already exists, the upload/transcribe is skipped.

Requires: pip install dashscope

Usage:
    python helpers/transcribe.py <video_path>
    python helpers/transcribe.py <video_path> --edit-dir /custom/edit/video_name
    python helpers/transcribe.py <video_path> --language zh
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from http import HTTPStatus
from pathlib import Path
from urllib import request as urlrequest

SKILL_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = SKILL_ROOT / ".env"
USER_ENV_PATH = Path.home() / ".codex" / "video-edit.env"
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CONTEXT_SIZE = 20
CHUNK_INPUT_RE = re.compile(r"^chunk_\d{3,}\.txt$")
CHUNK_DECISION_RE = re.compile(r"^chunk_\d{3,}_decisions\.json$")


def _response_error(stage: str, response: object) -> RuntimeError:
    """Build a useful DashScope error without assuming output is present."""
    status_code = getattr(response, "status_code", None)
    code = getattr(response, "code", None)
    message = getattr(response, "message", None)
    request_id = getattr(response, "request_id", None)
    output = getattr(response, "output", None)
    return RuntimeError(
        f"DashScope {stage} failed: status_code={status_code}, "
        f"code={code!r}, message={message!r}, request_id={request_id!r}, "
        f"output={output!r}"
    )


def _output_value(output: object, key: str):
    """Read a response output value from either a mapping or SDK object."""
    if isinstance(output, dict):
        return output.get(key)
    return getattr(output, key, None)


def _read_key_from_env_file(path: Path) -> str | None:
    """Try to extract DASHSCOPE_API_KEY from a .env file. Returns None if absent."""
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == "DASHSCOPE_API_KEY":
            val = v.strip().strip('"').strip("'")
            if val:
                return val
    return None


def load_api_key() -> str:
    """Resolve DASHSCOPE_API_KEY from .env or environment."""
    v = os.environ.get("DASHSCOPE_API_KEY", "")
    if v:
        return v

    for candidate in [ENV_PATH, USER_ENV_PATH, Path(".env")]:
        key = _read_key_from_env_file(candidate)
        if key:
            return key

    sys.exit(
        "DASHSCOPE_API_KEY not found.\n"
        f"Expected in: {ENV_PATH} or {USER_ENV_PATH}\n"
        "See SKILL.md → Setup for the configuration flow."
    )


def extract_audio(video_path: Path, dest: Path) -> None:
    """Extract lossless mono 16kHz FLAC audio from video."""
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "flac", "-compression_level", "5",
        str(dest),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def require_ffmpeg() -> None:
    """Fail clearly when fresh transcription cannot extract audio."""
    if not shutil.which("ffmpeg"):
        sys.exit("Missing required executable: ffmpeg. Install FFmpeg and add it to PATH.")


def call_dashscope_asr(audio_path: Path, api_key: str, language: str | None = None) -> list[dict]:
    """Upload audio and transcribe via DashScope async API.

    Returns the raw sentence list from the Transcription result.
    Each sentence has: begin_time, end_time, text, words[]
    Times are in milliseconds.
    """
    import dashscope
    from dashscope import Files
    from dashscope.audio.asr import Transcription

    dashscope.api_key = api_key
    dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"

    # 1. Upload audio to get a signed URL
    upload_result = Files.upload(file_path=str(audio_path.resolve()), purpose="file-extract")
    if upload_result.status_code != HTTPStatus.OK or upload_result.output is None:
        raise _response_error("file upload", upload_result)
    uploaded = _output_value(upload_result.output, "uploaded_files") or []
    if not uploaded:
        raise _response_error("file upload", upload_result)
    file_id = uploaded[0]["file_id"]

    # 2. Get signed URL
    file_info = Files.get(file_id)
    if file_info.status_code != HTTPStatus.OK or file_info.output is None:
        raise _response_error("file URL lookup", file_info)
    file_url = _output_value(file_info.output, "url")
    if not file_url:
        raise _response_error("file URL lookup", file_info)

    # 3. Submit transcription task
    task_response = Transcription.async_call(
        model="fun-asr",
        file_urls=[file_url],
        language_hints=[language or "zh"],
    )
    task_output = getattr(task_response, "output", None)
    task_id = _output_value(task_output, "task_id") if task_output else None
    if task_response.status_code != HTTPStatus.OK or not task_id:
        raise _response_error("task submission", task_response)

    # 4. Wait for completion
    result = Transcription.wait(task=task_id)

    if result.status_code != HTTPStatus.OK or result.output is None:
        raise _response_error("transcription", result)

    # 5. Collect sentences from results
    all_sentences = []
    for tr in result.output["results"]:
        if tr["subtask_status"] == "SUCCEEDED":
            tr_url = tr["transcription_url"]
            data = json.loads(urlrequest.urlopen(tr_url).read().decode("utf8"))
            for transcript in data.get("transcripts", []):
                for sentence in transcript.get("sentences", []):
                    if sentence.get("text"):
                        all_sentences.append(sentence)
        else:
            print(f"  WARNING: subtask failed: {tr.get('message', tr)}", file=sys.stderr)

    if not all_sentences:
        raise RuntimeError("DashScope returned no sentences. Check audio quality.")

    return all_sentences


def build_structured_data(raw_sentences: list[dict]) -> list[dict]:
    """Map DashScope sentence results to the standard format with nested word timestamps.

    DashScope returns: {begin_time, end_time, text, words: [{begin_time, end_time, text}]}
    Times are in milliseconds — we convert to seconds.

    Output: [{text, start, end, speaker_id, characters: [{character, start_time, end_time}]}]
    """
    sentences_out = []

    for sentence in raw_sentences:
        words = sentence.get("words", [])
        if not words:
            continue

        text = sentence.get("text", "")

        characters = []
        for w in words:
            w_text = w.get("text", "")
            if not w_text:
                continue
            t_start = w.get("begin_time", 0)
            t_end = w.get("end_time", 0)
            characters.append({
                "character": w_text,
                "start_time": t_start / 1000.0,
                "end_time": t_end / 1000.0,
                "type": "char",
            })

        if characters:
            sentences_out.append({
                "text": text,
                "start": characters[0]["start_time"],
                "end": characters[-1]["end_time"],
                "speaker_id": "speaker_0",
                "characters": characters,
            })

    return sentences_out


def build_clean_transcript(sentences: list[dict]) -> str:
    """Generate pure text output line by line with sequential IDs for LLM consumption."""
    lines = []
    for idx, s in enumerate(sentences, start=1):
        text = s.get("text", "").replace("\n", " ").strip()
        lines.append(f"[ID: {idx}] {text}")
    return "\n".join(lines)


def write_transcript_chunks(
    sentences: list[dict],
    edit_dir: Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    context_size: int = DEFAULT_CONTEXT_SIZE,
) -> list[Path]:
    """Write chunked LLM inputs while preserving global sentence IDs.

    Each chunk owns at most chunk_size IDs and includes surrounding context.
    The header tells the LLM which IDs it may emit. Decisions are preserved
    only while their corresponding chunk input is byte-for-byte unchanged.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")
    if context_size < 0:
        raise ValueError("context_size cannot be negative")
    chunks_dir = edit_dir / "chunks"

    if len(sentences) <= chunk_size:
        if chunks_dir.exists():
            for path in chunks_dir.iterdir():
                if path.is_file() and (
                    CHUNK_INPUT_RE.fullmatch(path.name)
                    or CHUNK_DECISION_RE.fullmatch(path.name)
                ):
                    path.unlink()
            try:
                chunks_dir.rmdir()
            except OSError:
                pass
        return []

    lines = build_clean_transcript(sentences).splitlines()
    chunks_dir.mkdir(parents=True, exist_ok=True)
    chunk_paths = []
    expected_inputs: set[str] = set()

    for chunk_index, core_start in enumerate(
        range(0, len(lines), chunk_size), start=1
    ):
        core_end = min(core_start + chunk_size, len(lines))
        read_start = max(0, core_start - context_size)
        read_end = min(len(lines), core_end + context_size)
        path = chunks_dir / f"chunk_{chunk_index:03d}.txt"
        header = (
            f"[Chunk {chunk_index:03d}]\n"
            f"[Read range: IDs {read_start + 1}-{read_end}]\n"
            f"[Output range: IDs {core_start + 1}-{core_end}]\n"
            "Context IDs are for understanding only; emit fragments only "
            "for the output range.\n\n"
        )
        content = header + "\n".join(lines[read_start:read_end])
        decision_path = path.with_name(f"{path.stem}_decisions.json")
        old_content = None
        if path.exists():
            try:
                old_content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                pass
        if old_content != content:
            if decision_path.exists():
                decision_path.unlink()
            path.write_text(content, encoding="utf-8")
        chunk_paths.append(path)
        expected_inputs.add(path.name)

    for path in chunks_dir.iterdir():
        if not path.is_file():
            continue
        if CHUNK_INPUT_RE.fullmatch(path.name):
            if path.name not in expected_inputs:
                path.unlink()
        elif CHUNK_DECISION_RE.fullmatch(path.name):
            input_name = path.name.removesuffix("_decisions.json") + ".txt"
            if input_name not in expected_inputs:
                path.unlink()

    return chunk_paths


def transcribe_one(
    video: Path,
    edit_dir: Path,
    api_key: str | None = None,
    language: str | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    context_size: int = DEFAULT_CONTEXT_SIZE,
    verbose: bool = True,
) -> tuple[Path, Path]:
    """Transcribe a single video and produce the two artifact files."""
    edit_dir.mkdir(parents=True, exist_ok=True)
    ts_path = edit_dir / "raw_timestamps.json"
    txt_path = edit_dir / "clean_transcript.txt"

    # --- Cache hit ---
    if ts_path.exists():
        if verbose:
            print(f"cached: {ts_path.name}")
        timestamps = json.loads(ts_path.read_text(encoding="utf-8"))
        txt_path.write_text(build_clean_transcript(timestamps), encoding="utf-8")
        chunk_paths = write_transcript_chunks(
            timestamps, edit_dir, chunk_size, context_size
        )
        if verbose and chunk_paths:
            print(f"chunked: {len(chunk_paths)} file(s) in chunks/")
        return ts_path, txt_path

    # --- Fresh transcription ---
    if verbose:
        print(f"  extracting audio from {video.name}", flush=True)

    require_ffmpeg()
    if api_key is None:
        api_key = load_api_key()

    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / f"{video.stem}.flac"
        extract_audio(video, audio)
        size_mb = audio.stat().st_size / (1024 * 1024)
        if verbose:
            print(
                f"  uploading {video.stem}.flac "
                f"({size_mb:.1f} MB) to DashScope...",
                flush=True,
            )
        raw_sentences = call_dashscope_asr(audio, api_key, language)

    # Build outputs
    timestamps = build_structured_data(raw_sentences)

    ts_path.write_text(json.dumps(timestamps, indent=2, ensure_ascii=False), encoding="utf-8")
    txt_path.write_text(build_clean_transcript(timestamps), encoding="utf-8")
    chunk_paths = write_transcript_chunks(
        timestamps, edit_dir, chunk_size, context_size
    )

    dt = time.time() - t0
    if verbose:
        kb = ts_path.stat().st_size / 1024
        n_sents = len(timestamps)
        print(f"  saved: {ts_path.name} ({kb:.1f} KB, {n_sents} sentences) in {dt:.1f}s")
        print(f"  saved: {txt_path.name}")
        if chunk_paths:
            print(f"  chunked: {len(chunk_paths)} file(s) in chunks/")

    return ts_path, txt_path


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Transcribe a video with DashScope ASR (word-level timestamps)"
    )
    ap.add_argument("video", type=Path, help="Path to video file")
    ap.add_argument(
        "--edit-dir",
        type=Path,
        default=None,
        help=(
            "Per-video edit output directory "
            "(default: <video_parent>/edit/<video_stem>)"
        ),
    )
    ap.add_argument(
        "--language",
        type=str,
        default=None,
        help="Optional ISO language code (e.g. 'zh'). Defaults to 'zh'.",
    )
    ap.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"Maximum owned sentence IDs per chunk (default: {DEFAULT_CHUNK_SIZE}).",
    )
    ap.add_argument(
        "--context-size",
        type=int,
        default=DEFAULT_CONTEXT_SIZE,
        help=f"Context IDs before and after each chunk (default: {DEFAULT_CONTEXT_SIZE}).",
    )
    args = ap.parse_args()

    video = args.video.resolve()
    if not video.exists():
        sys.exit(f"video not found: {video}")

    edit_dir = (
        args.edit_dir or (video.parent / "edit" / video.stem)
    ).resolve()
    ts_path, txt_path = transcribe_one(
        video=video,
        edit_dir=edit_dir,
        language=args.language,
        chunk_size=args.chunk_size,
        context_size=args.context_size,
    )

    print(f"\ndone:")
    print(f"  timestamps: {ts_path}")
    print(f"  clean text: {txt_path}")


if __name__ == "__main__":
    main()
