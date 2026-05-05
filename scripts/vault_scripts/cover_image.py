"""Download, convert, and attach a cover image to a travel option file.

Usage:
    scripts/vault-tool cover_image --file "Travel/Japan26/Dining/entries/Fuunji.md" --url "https://example.com/photo.jpg"
    scripts/vault-tool cover_image --file ... --url "..." --write
    scripts/vault-tool cover_image --file ... --local "raw-photo.jpg" --write

Options:
    --file      Path to the option file (relative to vault root)
    --url       URL to download the image from
    --local     Path to a local image file instead of downloading
    --write     Apply changes (default is dry-run)
    --quality   WebP quality, 1-100 (default: 80)
    --max-width Max width in pixels (default: 1200)
"""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
import sys

from PIL import Image
from PIL.Image import Image as PILImage, Resampling

from vault_scripts._retry import request_image_bytes, wikimedia_retry
from vault_scripts._utils import (
    VAULT,
    add_inline_embed,
    find_images_dir,
    parse_typed_args,
    patch_field,
    rewrite_wikimedia_to_thumb,
    user_agent,
)

MAX_WIDTH = 1200
QUALITY = 80
DOWNLOAD_TIMEOUT_S = 30


@wikimedia_retry
def download_image(url: str) -> PILImage:
    """Download an image; Wikimedia URLs auto-rewrite via :func:`rewrite_wikimedia_to_thumb`."""
    fetch_url = rewrite_wikimedia_to_thumb(url)
    if fetch_url != url:
        print(f"  Using Wikimedia thumb: {fetch_url}")
    data = request_image_bytes(
        fetch_url,
        timeout=DOWNLOAD_TIMEOUT_S,
        headers={"User-Agent": user_agent()},
    )
    return Image.open(BytesIO(data))


def process_image(img: PILImage, *, max_width: int = MAX_WIDTH) -> PILImage:
    """Convert to RGB and resize if wider than max_width."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    if img.width > max_width:
        ratio = max_width / img.width
        new_size: tuple[int, int] = (max_width, int(img.height * ratio))
        # Pillow's .resize signature has a partially-unknown size overload
        # (NumPy interop); the tuple[int, int] path is well-typed on our side.
        img = img.resize(new_size, Resampling.LANCZOS)  # pyright: ignore[reportUnknownMemberType]
    return img


class _Args(argparse.Namespace):
    file: str
    url: str | None
    local: str | None
    write: bool
    quality: int
    max_width: int


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a cover image to a travel option file.")
    _ = parser.add_argument("--file", required=True, help="Option file path (relative to vault root)")
    source = parser.add_mutually_exclusive_group(required=True)
    _ = source.add_argument("--url", help="URL to download the image from")
    _ = source.add_argument("--local", help="Path to a local image file")
    _ = parser.add_argument("--write", action="store_true", help="Apply changes (default is dry-run)")
    _ = parser.add_argument("--quality", type=int, default=QUALITY, help=f"WebP quality (default: {QUALITY})")
    _ = parser.add_argument("--max-width", type=int, default=MAX_WIDTH, help=f"Max width in px (default: {MAX_WIDTH})")

    args = parse_typed_args(parser, _Args)

    file_path = VAULT / args.file
    if not file_path.exists():
        print(f"Error: {args.file} not found", file=sys.stderr)
        sys.exit(1)

    output_filename = f"{file_path.stem}.webp"
    images_dir = find_images_dir(file_path)
    output_path = images_dir / output_filename

    if args.url:
        print(f"Downloading: {args.url}")
        img = download_image(args.url)
    else:
        assert args.local is not None  # mutually exclusive + required  # noqa: S101
        local_path = Path(args.local) if Path(args.local).is_absolute() else VAULT / args.local
        if not local_path.exists():
            print(f"Error: {args.local} not found", file=sys.stderr)
            sys.exit(1)
        img = Image.open(local_path)

    print(f"  Source: {img.width}x{img.height} ({img.format})")

    img = process_image(img, max_width=args.max_width)
    print(f"  Output: {img.width}x{img.height} WebP (quality {args.quality})")

    if not args.write:
        print(f"\n  Would save: {output_path.relative_to(VAULT)}")
        print(f'  Would set cover: "{output_filename}"')
        print(f"  Would add embed: ![[{output_filename}|600]]")
        print("\n  Pass --write to apply.")
        return

    img.save(output_path, "webp", quality=args.quality)
    size_kb = output_path.stat().st_size / 1024
    print(f"  Saved: {output_path.relative_to(VAULT)} ({size_kb:.0f} KB)")

    text = file_path.read_text()
    text = patch_field(text, "cover", output_filename)
    text = add_inline_embed(text, output_filename)
    file_path.write_text(text)
    print(f"  Updated: {args.file}")
    print(f'    cover: "{output_filename}"')
    print(f"    embed: ![[{output_filename}|600]]")


if __name__ == "__main__":
    main()
