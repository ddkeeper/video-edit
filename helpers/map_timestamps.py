"""Reverse-map LLM edit decisions to exact millisecond timestamps.

The core algorithm of the video-edit workflow. Takes the LLM's semantic
decisions and maps them back to the physical timestamps in the raw JSON.
Supports both Character-level (ElevenLabs) and Word-level (DashScope) ASRs.

Usage:
    python helpers/map_timestamps.py edit/llm_output.json edit/raw_timestamps.json
    python helpers/map_timestamps.py edit/chunks edit/raw_timestamps.json
    python helpers/map_timestamps.py llm_output.json raw_timestamps.json --pad-start 0.25 --pad-end 0.15
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Default boundary padding for spoken content.
DEFAULT_PAD_START = 0.25
DEFAULT_PAD_END = 0.15
SAME_ID_EDGE_FRACTION = 0.25


# ---------- Loading ------------------------------------------------------------

def load_sentences(ts_path: Path) -> list[dict]:
    """Load the flat sentence array from raw_timestamps.json."""
    data = json.loads(ts_path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        sys.exit(f"raw_timestamps.json must be a non-empty list. Check {ts_path}")
    return data


def load_llm_output(llm_path: Path, allow_empty: bool = False) -> list[dict]:
    """Load and validate one LLM decision file."""
    data = json.loads(llm_path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or (not data and not allow_empty):
        sys.exit(f"{llm_path.name} must be a non-empty JSON array")

    for index, item in enumerate(data):
        if not isinstance(item, dict) or "id" not in item or "keep" not in item:
            sys.exit(
                f"{llm_path.name} item {index + 1} must contain 'id' and 'keep'"
            )
        if not isinstance(item["id"], int) or not isinstance(item["keep"], str):
            sys.exit(
                f"{llm_path.name} item {index + 1} has invalid 'id' or 'keep' type"
            )
        if not item["keep"].strip():
            sys.exit(f"{llm_path.name} item {index + 1} has an empty 'keep'")

    return data


def load_decisions(path: Path) -> tuple[list[dict], Path]:
    """Load one decision file or merge chunk decisions from a directory."""
    if path.is_file():
        return load_llm_output(path), path.parent

    if not path.is_dir():
        sys.exit(f"decision path not found: {path}")

    chunk_files = sorted(path.glob("chunk_*.txt"))
    if not chunk_files:
        sys.exit(f"no chunk_*.txt files found in: {path}")

    merged = []
    for chunk_file in chunk_files:
        range_match = re.search(
            r"\[Output range:\s*IDs\s+(\d+)-(\d+)\]",
            chunk_file.read_text(encoding="utf-8"),
        )
        if not range_match:
            sys.exit(f"missing output ID range in: {chunk_file.name}")
        allowed_start, allowed_end = map(int, range_match.groups())

        decision_file = chunk_file.with_name(
            f"{chunk_file.stem}_decisions.json"
        )
        if not decision_file.exists():
            sys.exit(f"missing chunk decision file: {decision_file.name}")

        decisions = load_llm_output(decision_file, allow_empty=True)
        for index, item in enumerate(decisions):
            if not allowed_start <= item["id"] <= allowed_end:
                sys.exit(
                    f"{decision_file.name} item {index + 1} uses ID "
                    f"{item['id']}, outside allowed range "
                    f"{allowed_start}-{allowed_end}"
                )
        merged.extend(decisions)
        print(f"  merged: {decision_file.name} ({len(decisions)} decisions)")

    if not merged:
        sys.exit("all chunk decision files are empty")

    merged.sort(key=lambda item: item["id"])
    edit_dir = path.parent
    merged_path = edit_dir / "llm_output.json"
    merged_path.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  saved merged decisions: {merged_path.name}")
    return merged, edit_dir


# ---------- Core Mapping Algorithm --------------------------------------------

def map_llm_decisions(
    llm_data: list[dict],
    sentences: list[dict],
    pad_start: float,
    pad_end: float,
) -> list[dict]:
    """Map ID + exact-substring decisions to timestamps, failing on any error."""
    edl = []
    errors = []

    requests_by_sid = {}
    for entry in llm_data:
        requests_by_sid.setdefault(entry["id"], []).append(entry["keep"])

    n = len(sentences)

    for sid, keeps in requests_by_sid.items():
        idx = sid - 1
        if idx < 0 or idx >= n:
            errors.append(f"sentence ID {sid} is outside 1-{n}")
            continue

        sentence = sentences[idx]
        sentence_text = (
            sentence.get("text", "").replace("\n", " ").strip()
        )
        chars_or_words = sentence.get("characters", [])
        if not chars_or_words:
            errors.append(f"sentence ID {sid} has no word/character timestamps")
            continue

        # 1. Build a normalized haystack and a pointer to timestamped tokens.
        haystack_chars = []
        char_map = []

        for item in chars_or_words:
            # Supports both word-level and character-level ASR tokens.
            text = item.get("character", "")
            for char in text:
                if char.isalnum():  # Ignore punctuation and whitespace for timing lookup.
                    haystack_chars.append(char)
                    char_map.append(item)

        haystack = "".join(haystack_chars)
        search_pos = 0

        # 2. Match each exact keep fragment in source order.
        for keep_text in keeps:
            if keep_text not in sentence_text:
                errors.append(
                    f"[ID: {sid}] keep is not an exact source substring: "
                    f"'{keep_text}'"
                )
                continue

            # Normalize the model fragment the same way as the ASR haystack.
            needle = "".join(ch for ch in keep_text if ch.isalnum())
            if not needle:
                errors.append(
                    f"[ID: {sid}] keep contains no mappable characters: "
                    f"'{keep_text}'"
                )
                continue

            start_idx = haystack.find(needle, search_pos)
            if start_idx == -1:
                errors.append(
                    f"[ID: {sid}] could not map keep in output order: "
                    f"'{keep_text}' (normalized: '{needle}')"
                )
                continue

            end_idx = start_idx + len(needle) - 1

            # 3. Resolve the first and last matching token timestamps.
            start_time = char_map[start_idx]["start_time"]
            end_time = char_map[end_idx]["end_time"]

            search_pos = end_idx + 1

            edl.append({
                "start": start_time,
                "end": end_time,
                "text": keep_text,
                "sentence_id": sid,
            })

    if errors:
        for error in errors:
            print(f"  ERROR: {error}", file=sys.stderr)
        sys.exit(
            f"Failed to map {len(errors)} decision(s). "
            "Fix llm_output.json before rendering."
        )

    if not edl:
        sys.exit("Failed to map any substrings to timestamps. Check llm_output.json.")

    edl.sort(key=lambda x: x["start"])

    return _apply_padding(edl, sentences, pad_start, pad_end)


# ---------- Padding & overlap clamping -----------------------------------------

def _apply_padding(edl: list[dict], sentences: list[dict], pad_start: float, pad_end: float) -> list[dict]:
    """Apply asymmetric padding and adaptively clamp overlaps."""
    global_min = sentences[0]["start"] or 0.0
    global_max = sentences[-1]["end"] or edl[-1]["end"]
    base_bounds = [
        (float(entry["start"]), float(entry["end"])) for entry in edl
    ]

    # 1. Apply padding independently.
    for entry in edl:
        entry["start"] = max(global_min, entry["start"] - pad_start)
        entry["end"] = min(global_max, entry["end"] + pad_end)

    # 2. For same-ID fragments, cap padding so an interior deletion remains.
    #    Other adjacent fragments use the midpoint rule to avoid overlap.
    for i in range(len(edl) - 1):
        current = edl[i]
        following = edl[i + 1]
        if current["end"] <= following["start"]:
            continue

        base_end = base_bounds[i][1]
        base_start = base_bounds[i + 1][0]
        source_gap = base_start - base_end
        same_sentence = current.get("sentence_id") == following.get("sentence_id")

        if same_sentence and source_gap > 0:
            edge_cap = source_gap * SAME_ID_EDGE_FRACTION
            current["end"] = min(
                global_max, base_end + min(pad_end, edge_cap)
            )
            following["start"] = max(
                global_min, base_start - min(pad_start, edge_cap)
            )
            if current["end"] <= following["start"]:
                continue

        mid = (current["end"] + following["start"]) / 2.0
        current["end"] = mid
        following["start"] = mid

    return edl


# ---------- Main ---------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Map LLM JSON decisions to exact millisecond timestamps"
    )
    ap.add_argument(
        "llm_output",
        type=Path,
        help="Path to llm_output.json or a chunks directory",
    )
    ap.add_argument(
        "raw_timestamps",
        type=Path,
        help="Path to raw_timestamps.json",
    )
    ap.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output EDL path",
    )
    ap.add_argument(
        "--pad-start",
        type=float,
        default=DEFAULT_PAD_START,
        help=f"Padding before cut in seconds (default: {DEFAULT_PAD_START})",
    )
    ap.add_argument(
        "--pad-end",
        type=float,
        default=DEFAULT_PAD_END,
        help=f"Padding after cut in seconds (default: {DEFAULT_PAD_END})",
    )
    args = ap.parse_args()

    # --- Load inputs ---
    llm_path = args.llm_output.resolve()
    ts_path = args.raw_timestamps.resolve()

    if not llm_path.exists():
        sys.exit(f"decision path not found: {llm_path}")
    if not ts_path.exists():
        sys.exit(f"raw_timestamps.json not found: {ts_path}")

    llm_data, edit_dir = load_decisions(llm_path)
    sentences = load_sentences(ts_path)

    # --- Execute Mapping ---
    edl = map_llm_decisions(llm_data, sentences, pad_start=args.pad_start, pad_end=args.pad_end)

    # --- Write output ---
    out_path = args.output or (edit_dir / "edl.json")
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(edl, indent=2, ensure_ascii=False), encoding="utf-8")

    total_duration = sum(e["end"] - e["start"] for e in edl)
    print(f"\nDone. EDL saved to: {out_path.name}")
    print(f"  Padding used: Start -{args.pad_start}s, End +{args.pad_end}s")
    print(f"  Total Segments: {len(edl)}")
    print(f"  Total Kept Duration: {total_duration:.2f}s")

if __name__ == "__main__":
    main()
