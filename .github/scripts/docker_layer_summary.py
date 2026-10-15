#!/usr/bin/env python3
"""Generates a GitHub Actions Markdown layer size breakdown for Docker images."""

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any

METADATA_RE = re.compile(
    r"^/bin/sh -c #\(nop\)\s+(ENV|LABEL|EXPOSE|CMD|ENTRYPOINT|STOPSIGNAL|HEALTHCHECK|MAINTAINER|USER)"
    r"|^(ENV|LABEL|EXPOSE|CMD|ENTRYPOINT|STOPSIGNAL|HEALTHCHECK|MAINTAINER|USER)\b"
)
CMD_PREFIX_RE = re.compile(r"^(#\s*buildkit|/bin/sh\s+-c\s+#\(nop\)\s+|/bin/sh\s+-c\s+)")


def docker(*args: str) -> str:
    """Execute a docker CLI command and return its stdout."""
    return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.PIPE)


def format_size(size_bytes: float | None) -> str:
    """Format bytes into human-readable IEC binary units (B, KiB, MiB, GiB)."""
    try:
        size = float(size_bytes)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return "—"

    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024.0:
            return f"{int(size)} B" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PiB"


def clean_command(cmd: str | None, max_length: int = 60) -> str:
    """Sanitize Docker history commands for Markdown table formatting."""
    if not cmd:
        return ""

    cmd = " ".join(CMD_PREFIX_RE.sub("", cmd).split())
    if len(cmd) > max_length:
        cmd = f"{cmd[:max_length - 3]}..."

    return cmd.replace("|", "\\|").replace("`", "'")


def get_compressed_layer_sizes(image_ref: str, target_platform: str) -> list[int]:
    """Fetch compressed layer sizes from the manifest."""
    try:
        data = json.loads(docker("buildx", "imagetools", "inspect", "--raw", image_ref))
        if "manifests" in data:
            req_os, req_arch, *var = target_platform.split("/")
            req_var = var[0] if var else None

            matched = next(
                (
                    m.get("digest")
                    for m in data.get("manifests", [])
                    if (plat := m.get("platform") or {}).get("os") == req_os
                    and plat.get("architecture") == req_arch
                    and (not req_var or plat.get("variant") == req_var)
                ),
                None,
            )
            if not matched:
                return []

            ref = image_ref.split("@")[0]
            base = ref[:colon] if (colon := ref.rfind(":")) > ref.rfind("/") else ref
            raw_child = docker("buildx", "imagetools", "inspect", "--raw", f"{base}@{matched}")
            data = json.loads(raw_child)

        return [layer.get("size", 0) for layer in data.get("layers", [])]
    except Exception as err:
        print(f"[WARN] Failed to fetch compressed layers: {err}", file=sys.stderr)
        return []


def get_uncompressed_layers(image_ref: str, expected_count: int) -> list[dict[str, Any]]:
    """Fetch history entries matching the exact filesystem layers."""
    try:
        raw_history = docker(
            "history", "--no-trunc", "--human=false", "--format", "{{json .}}", image_ref
        )
    except Exception as err:
        print(f"[WARN] Failed to read image history: {err}", file=sys.stderr)
        return []

    layers = []
    for line in reversed(raw_history.splitlines()):
        if not line.strip():
            continue
        entry = json.loads(line)
        cmd, size = entry.get("CreatedBy", ""), int(entry.get("Size", 0))
        if not (size == 0 and METADATA_RE.search(cmd.strip())):
            layers.append({"size": size, "command": cmd})

    if expected_count > 0 and len(layers) > expected_count:
        non_zero = [l for l in layers if l["size"] > 0]
        if len(non_zero) == expected_count:
            return non_zero

    return layers


def generate_markdown_summary(
    platform: str,
    compressed_layers: list[int],
    history_layers: list[dict[str, Any]],
    total_uncompressed: int,
) -> str:
    """Build the GitHub Markdown summary table."""
    lines = [
        f"### 📦 Layer Sizes & Commands — `{platform}`",
        "| Layer | Command | Compressed (Wire) | Uncompressed (Disk) |",
        "| :--- | :--- | :--- | :--- |",
    ]

    for i in range(max(len(compressed_layers), len(history_layers))):
        comp = format_size(compressed_layers[i]) if i < len(compressed_layers) else "—"
        hist = history_layers[i] if i < len(history_layers) else None
        cmd = f"`{c}`" if hist and (c := clean_command(hist["command"])) else "—"
        uncomp = format_size(hist["size"]) if hist else "—"
        lines.append(f"| Layer {i + 1} | {cmd} | {comp} | {uncomp} |")

    uncomp_total = format_size(total_uncompressed) if total_uncompressed > 0 else "—"
    lines.append(
        f"| **Total** | — | **{format_size(sum(compressed_layers))}** | **{uncomp_total}** |"
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Docker image layer summary.")
    parser.add_argument(
        "--image", required=True, help="Full image reference (e.g. ghcr.io/repo@sha256:...)"
    )
    parser.add_argument(
        "--platform", required=True, help="Target platform (e.g. linux/amd64)"
    )
    parser.add_argument(
        "--output", help="Path to write output (defaults to GITHUB_STEP_SUMMARY or stdout)"
    )
    args = parser.parse_args()

    compressed = get_compressed_layer_sizes(args.image, args.platform)
    history = get_uncompressed_layers(args.image, expected_count=len(compressed))

    try:
        total_uncompressed = int(docker("inspect", "--format", "{{.Size}}", args.image).strip())
    except Exception:
        total_uncompressed = 0

    markdown = generate_markdown_summary(
        platform=args.platform,
        compressed_layers=compressed,
        history_layers=history,
        total_uncompressed=total_uncompressed,
    )

    if dest := (args.output or os.environ.get("GITHUB_STEP_SUMMARY")):
        with open(dest, "a", encoding="utf-8") as f:
            f.write(markdown)
    else:
        print(markdown)


if __name__ == "__main__":
    main()
