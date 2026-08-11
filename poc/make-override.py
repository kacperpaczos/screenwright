#!/usr/bin/env python3
"""
Build an AppStream catalogue that overrides a component's screenshots.

Why a full override rather than merge="replace"?
    Merge works, but as_component_merge_with_mode() in AppStream 1.1.3 copies
    only name, summary, description, pkgnames, bundles, icons and provided --
    the source carries a "FIXME/TODO: We need to merge more attributes" comment
    right above it. Screenshots are not on that list, so merge leaves them
    alone. Instead we take the whole component from the distribution catalogue,
    swap its <screenshots> block, and publish it under our own origin with a
    higher priority. Our version wins and every other field stays intact.

Usage:
    make-override.py --id org.kde.kcalc.desktop --base-url http://127.0.0.1:8899 \\
                     --prefix kcalc --out 90-screenwright.xml
"""

import argparse
import gzip
import sys
import xml.etree.ElementTree as ET

# Thumbnail sizes produced by Fedora's appstream-generator.
THUMBS = [(752, 423), (624, 351), (224, 126), (112, 63)]

DEFAULT_CATALOGS = [
    "/usr/share/swcatalog/xml/fedora.xml.gz",
]


def load_catalog(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rb") as fh:
        return ET.fromstring(fh.read())


def find_component(root, cid):
    for cpt in root:
        node = cpt.find("id")
        if node is not None and node.text == cid:
            return cpt
    return None


def build_screenshots(base_url, prefix, caption, width, height):
    shots = ET.Element("screenshots")
    shot = ET.SubElement(shots, "screenshot", {"type": "default"})
    ET.SubElement(shot, "caption").text = caption

    src = ET.SubElement(shot, "image",
                        {"type": "source", "width": str(width), "height": str(height)})
    src.text = f"{base_url}/{prefix}-source.png"

    for w, h in THUMBS:
        thumb = ET.SubElement(shot, "image",
                              {"type": "thumbnail", "width": str(w), "height": str(h)})
        thumb.text = f"{base_url}/{prefix}-{w}x{h}.png"

    return shots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="component identifier")
    ap.add_argument("--base-url", required=True, help="root URL the images are served from")
    ap.add_argument("--prefix", required=True, help="image filename prefix, e.g. kcalc")
    ap.add_argument("--out", required=True)
    ap.add_argument("--origin", default="screenwright")
    ap.add_argument("--priority", type=int, default=1,
                    help="must exceed the distribution catalogue's priority (Fedora declares none, so 0)")
    ap.add_argument("--caption", default="screenwright - generated automatically under Xvfb")
    ap.add_argument("--source-size", default="640x480")
    ap.add_argument("--catalog", action="append", default=None)
    args = ap.parse_args()

    width, height = (int(v) for v in args.source_size.split("x"))

    cpt = None
    for path in (args.catalog or DEFAULT_CATALOGS):
        cpt = find_component(load_catalog(path), args.id)
        if cpt is not None:
            print(f"found {args.id} in {path}")
            break
    if cpt is None:
        print(f"ERROR: no component {args.id} in the catalogues searched", file=sys.stderr)
        return 2

    # Drop the original screenshots and insert ours. Everything else in the
    # component (description, categories, icons, releases...) is carried over
    # untouched, otherwise the store listing would lose those fields.
    for old in cpt.findall("screenshots"):
        cpt.remove(old)
    cpt.append(build_screenshots(args.base_url, args.prefix, args.caption, width, height))

    root = ET.Element("components", {
        "origin": args.origin,
        "version": "0.14",
        "priority": str(args.priority),
    })
    root.append(cpt)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(args.out, encoding="UTF-8", xml_declaration=True)
    print(f"wrote {args.out} (origin={args.origin}, priority={args.priority})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
