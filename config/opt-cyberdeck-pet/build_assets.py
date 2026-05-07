#!/usr/bin/env python3
"""Build deployment-ready pet assets from source art.

Resizes and renames source assets in fb_assets/ (or fb_assets_source/)
to consistent sizes with underscore naming. Run this on the dev machine
before deploying to the cyberdeck.
"""
import os
import shutil
from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(SCRIPT_DIR, "fb_assets_source")
DST_DIR = os.path.join(SCRIPT_DIR, "fb_assets")

# Fallback: if no source dir, use current fb_assets as source
FALLBACK_SRC = os.path.join(SCRIPT_DIR, "fb_assets")

# Target sizes
MERMAID_W, MERMAID_H = 240, 336
EGG_W, EGG_H = 160, 224
FRIEND_W, FRIEND_H = 120, 120
PROP_W, PROP_H = 80, 80
FOOD_W, FOOD_H = 80, 80
FOOD_ICON_W, FOOD_ICON_H = 48, 48
PARTICLE_W, PARTICLE_H = 64, 64
BG_W, BG_H = 640, 480


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def resize_fit(img, target_w, target_h):
    """Resize image to fit within target, maintaining aspect ratio,
    and center on a transparent canvas of exactly target size.

    If source is landscape, center-crop to portrait aspect ratio first
    so the mermaid fills the canvas instead of being tiny."""
    img = img.convert("RGBA")
    w, h = img.size

    # For landscape images, crop to content bbox first so we don't cut off
    # the mermaid if she's positioned off-center in the source frame.
    if w > h:
        bbox = img.getbbox()
        if bbox:
            x1, y1, x2, y2 = bbox
            # Add padding so we don't clip soft edges/glows
            pad = 10
            x1 = max(0, x1 - pad)
            y1 = max(0, y1 - pad)
            x2 = min(w, x2 + pad)
            y2 = min(h, y2 + pad)
            img = img.crop((x1, y1, x2, y2))
            w, h = img.size

    ratio = min(target_w / w, target_h / h)
    new_w = max(1, int(w * ratio))
    new_h = max(1, int(h * ratio))
    img = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    ox = (target_w - img.width) // 2
    oy = (target_h - img.height) // 2
    canvas.paste(img, (ox, oy), img)
    return canvas


def resize_fit_bottom(img, target_w, target_h):
    """Resize image to fit within target, maintaining aspect ratio,
    and place at the BOTTOM of a transparent canvas.

    Used for crab sprites: when the canvas is rotated, the bottom-aligned
    crab's feet automatically align flush to the correct screen edge."""
    img = img.convert("RGBA")
    w, h = img.size

    if w > h:
        bbox = img.getbbox()
        if bbox:
            x1, y1, x2, y2 = bbox
            pad = 10
            x1 = max(0, x1 - pad)
            y1 = max(0, y1 - pad)
            x2 = min(w, x2 + pad)
            y2 = min(h, y2 + pad)
            img = img.crop((x1, y1, x2, y2))
            w, h = img.size

    ratio = min(target_w / w, target_h / h)
    new_w = max(1, int(w * ratio))
    new_h = max(1, int(h * ratio))
    img = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    ox = (target_w - img.width) // 2
    oy = target_h - img.height  # align to bottom
    canvas.paste(img, (ox, oy), img)
    return canvas


def copy_or_resize(src_path, dst_path, target_w=None, target_h=None):
    """Copy file, optionally resizing to target dimensions."""
    img = Image.open(src_path)
    if target_w and target_h and img.size != (target_w, target_h):
        img = resize_fit(img, target_w, target_h)
    else:
        img = img.convert("RGBA")
    img.save(dst_path)
    return img.size


def convert_to_raw(img, dst_path):
    """Convert PIL RGBA image to raw RGB565+alpha format for fast blitting.

    Format: [uint16 w][uint16 h][w*h*2 bytes RGB565][w*h bytes alpha]
    All values little-endian. Alpha: 0=transparent, 255=opaque.
    """
    img = img.convert("RGBA")
    w, h = img.size
    pixels = img.load()
    rgb565_data = bytearray()
    alpha_data = bytearray()
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            rgb565 = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            rgb565_data += rgb565.to_bytes(2, "little")
            alpha_data.append(a)
    with open(dst_path, "wb") as f:
        f.write(w.to_bytes(2, "little"))
        f.write(h.to_bytes(2, "little"))
        f.write(bytes(rgb565_data))
        f.write(bytes(alpha_data))
    return (w, h)


def prepare_source():
    """If fb_assets_source/ doesn't exist, create it from current fb_assets/."""
    if not os.path.isdir(SRC_DIR):
        print("Creating fb_assets_source/ backup from current fb_assets/...")
        ensure_dir(SRC_DIR)
        if os.path.isdir(FALLBACK_SRC):
            for name in os.listdir(FALLBACK_SRC):
                src = os.path.join(FALLBACK_SRC, name)
                dst = os.path.join(SRC_DIR, name)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
        print("  Backup complete.")


def clear_dst():
    """Remove old processed assets so we start clean."""
    if os.path.isdir(DST_DIR):
        shutil.rmtree(DST_DIR)
    ensure_dir(DST_DIR)


def build_mermaids():
    """Process expression and outfit sprites."""
    # Source name -> output name mapping (for cases where they differ)
    expressions = [
        ("happy", "happy"),
        ("sad", "sad"),
        ("excite", "excited"),   # source uses 'excite', code uses 'excited'
        ("sick", "sick"),
        ("hungry", "hungry"),
        ("pissed", "pissed"),
        ("sleep", "sleep"),
        ("tired", "tired"),
        ("wink", "wink"),
        ("clean", "clean"),
        ("dirty", "dirty"),
    ]
    outfits = ["blue", "galaxy", "green", "rainbow"]

    for src_name, out_name in expressions:
        src = os.path.join(SRC_DIR, f"mermaid-{src_name}.png")
        if not os.path.exists(src):
            print(f"  SKIP expression: {src_name}")
            continue

        size = copy_or_resize(src, os.path.join(DST_DIR, f"mermaid_{out_name}.png"), MERMAID_W, MERMAID_H)
        print(f"  mermaid_{out_name}.png: {size}")

        # Blink variant
        blink_src = os.path.join(SRC_DIR, f"mermaid-{src_name}-blink.png")
        if os.path.exists(blink_src):
            size = copy_or_resize(blink_src, os.path.join(DST_DIR, f"mermaid_{out_name}_blink.png"), MERMAID_W, MERMAID_H)
            print(f"  mermaid_{out_name}_blink.png: {size}")

    # Fix typo: sad-bllnk -> sad_blink
    typo = os.path.join(SRC_DIR, "mermaid-sad-bllnk.png")
    if os.path.exists(typo):
        size = copy_or_resize(typo, os.path.join(DST_DIR, "mermaid_sad_blink.png"), MERMAID_W, MERMAID_H)
        print(f"  mermaid_sad_blink.png: {size} (from typo fix)")

    for outfit in outfits:
        src = os.path.join(SRC_DIR, f"mermaid-outfit-{outfit}.png")
        # Handle typo: "mermaid-outfit- rainbow.png" has a space
        if not os.path.exists(src) and outfit == "rainbow":
            typo = os.path.join(SRC_DIR, "mermaid-outfit- rainbow.png")
            if os.path.exists(typo):
                src = typo
        if not os.path.exists(src):
            print(f"  SKIP outfit: {outfit}")
            continue

        size = copy_or_resize(src, os.path.join(DST_DIR, f"outfit_{outfit}.png"), MERMAID_W, MERMAID_H)
        print(f"  outfit_{outfit}.png: {size}")

        blink_src = os.path.join(SRC_DIR, f"mermaid-outfit-{outfit}-blink.png")
        if not os.path.exists(blink_src) and outfit == "rainbow":
            typo_blink = os.path.join(SRC_DIR, "mermaid-outfit- rainbow-blink.png")
            if os.path.exists(typo_blink):
                blink_src = typo_blink
        if os.path.exists(blink_src):
            size = copy_or_resize(blink_src, os.path.join(DST_DIR, f"outfit_{outfit}_blink.png"), MERMAID_W, MERMAID_H)
            print(f"  outfit_{outfit}_blink.png: {size}")


def build_friends():
    """Process friend characters."""
    friends = ["crab", "dolphin", "octopus", "seahorse", "starfish"]
    for name in friends:
        src = os.path.join(SRC_DIR, f"friend-{name}.png")
        if not os.path.exists(src):
            print(f"  SKIP friend: {name}")
            continue
        img = resize_fit(Image.open(src), FRIEND_W, FRIEND_H)
        size = copy_or_resize(src, os.path.join(DST_DIR, f"friend_{name}.png"), FRIEND_W, FRIEND_H)
        raw_size = convert_to_raw(img, os.path.join(DST_DIR, f"friend_{name}.raw"))
        print(f"  friend_{name}.png: {size}, .raw: {raw_size}")

    # Generate oriented crab sprites for perimeter walk animation
    crab_src = os.path.join(SRC_DIR, "friend-crab.png")
    if os.path.exists(crab_src):
        # Bottom-align the crab: when rotated, feet align flush to each edge
        base = resize_fit_bottom(Image.open(crab_src), FRIEND_W, FRIEND_H)
        orientations = {
            "bottom": 0,    # 0°: feet at bottom
            "right": 90,    # 90° CCW: bottom → right side
            "top": 180,     # 180°: feet at top
            "left": 270,    # 270° CCW: bottom → left side
        }
        flush_align = {
            "bottom": ("center", "bottom"),
            "right":  ("right",  "center"),
            "top":    ("center", "top"),
            "left":   ("left",   "center"),
        }
        for orient, angle in orientations.items():
            rotated = base.rotate(angle, expand=True)
            # For square images rotated 90° increments, size stays the same.
            # Just in case, resize back to target (centered fallback).
            if rotated.size != (FRIEND_W, FRIEND_H):
                rotated = resize_fit(rotated, FRIEND_W, FRIEND_H)
            # Reposition visible content flush to the feet edge
            bbox = rotated.getbbox()
            if bbox:
                content = rotated.crop(bbox)
                cw, ch = content.size
                canvas = Image.new("RGBA", (FRIEND_W, FRIEND_H), (0, 0, 0, 0))
                ax, ay = flush_align[orient]
                px = (FRIEND_W - cw) // 2 if ax == "center" else 0 if ax == "left" else FRIEND_W - cw
                py = (FRIEND_H - ch) // 2 if ay == "center" else 0 if ay == "top" else FRIEND_H - ch
                canvas.paste(content, (px, py), content)
                rotated = canvas
            dst_png = os.path.join(DST_DIR, f"friend_crab_{orient}.png")
            rotated.save(dst_png)
            raw_size = convert_to_raw(rotated, os.path.join(DST_DIR, f"friend_crab_{orient}.raw"))
            print(f"  friend_crab_{orient}.png: {rotated.size}, .raw: {raw_size}")


def build_props():
    """Process props / collectibles."""
    props = ["oyster"]
    for name in props:
        src = os.path.join(SRC_DIR, f"{name}.png")
        if not os.path.exists(src):
            print(f"  SKIP prop: {name}")
            continue
        img = resize_fit(Image.open(src), PROP_W, PROP_H)
        size = copy_or_resize(src, os.path.join(DST_DIR, f"prop_{name}.png"), PROP_W, PROP_H)
        raw_size = convert_to_raw(img, os.path.join(DST_DIR, f"prop_{name}.raw"))
        print(f"  prop_{name}.png: {size}, .raw: {raw_size}")

    treats = ["comb", "crystal", "fork", "necklace", "oyster", "treasure"]
    for name in treats:
        src = os.path.join(SRC_DIR, f"treat-{name}.png")
        if not os.path.exists(src):
            print(f"  SKIP treat: {name}")
            continue
        img = resize_fit(Image.open(src), PROP_W, PROP_H)
        size = copy_or_resize(src, os.path.join(DST_DIR, f"treat_{name}.png"), PROP_W, PROP_H)
        raw_size = convert_to_raw(img, os.path.join(DST_DIR, f"treat_{name}.raw"))
        print(f"  treat_{name}.png: {size}, .raw: {raw_size}")


def get_union_bbox(paths):
    """Compute the union of content bboxes across all images.
    Returns (left, top, right, bottom) or None if no valid images."""
    union = None
    for path in paths:
        if not os.path.exists(path):
            continue
        img = Image.open(path).convert("RGBA")
        bbox = img.getbbox()
        if bbox is None:
            continue
        x1, y1, x2, y2 = bbox
        if union is None:
            union = [x1, y1, x2, y2]
        else:
            union[0] = min(union[0], x1)
            union[1] = min(union[1], y1)
            union[2] = max(union[2], x2)
            union[3] = max(union[3], y2)
    return tuple(union) if union else None


def resize_fit_with_crop(img, target_w, target_h, crop_bbox):
    """Crop image to given bbox, then resize to fit target canvas.
    Same centering logic as resize_fit."""
    img = img.convert("RGBA")
    x1, y1, x2, y2 = crop_bbox
    img = img.crop((x1, y1, x2, y2))
    w, h = img.size

    ratio = min(target_w / w, target_h / h)
    new_w = max(1, int(w * ratio))
    new_h = max(1, int(h * ratio))
    img = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    ox = (target_w - img.width) // 2
    oy = (target_h - img.height) // 2
    canvas.paste(img, (ox, oy), img)
    return canvas


def process_lifecycle_group(name, src_prefix, variants, target_w, target_h):
    """Process a lifecycle group (egg/baby/kid) with consistent cropping.
    Uses the UNION of ALL variant bboxes as the master crop so no variant
    gets clipped (e.g. baby sleep pose extending left of base bbox).
    variants: list of (src_suffix, out_suffix) tuples.
    """
    # Collect all variant source paths
    variant_paths = []
    for src_suffix, out_suffix in variants:
        src_name = f"{src_prefix}-{src_suffix}.png" if src_suffix else f"{src_prefix}.png"
        src_path = os.path.join(SRC_DIR, src_name)
        if os.path.exists(src_path):
            variant_paths.append(src_path)
        # Also include blink variants in union
        blink_src = os.path.join(SRC_DIR, f"{src_prefix}-{src_suffix}-blink.png" if src_suffix else f"{src_prefix}-blink.png")
        if os.path.exists(blink_src):
            variant_paths.append(blink_src)

    master_bbox = get_union_bbox(variant_paths)

    if master_bbox is None:
        print(f"  SKIP {name}: no images found")
        return

    print(f"  {name} union bbox: {master_bbox}")

    # Process all variants with the same master bbox
    for src_suffix, out_suffix in variants:
        src_name = f"{src_prefix}-{src_suffix}.png" if src_suffix else f"{src_prefix}.png"
        out_name = f"mermaid_{name}_{out_suffix}.png" if out_suffix else f"mermaid_{name}.png"
        src_path = os.path.join(SRC_DIR, src_name)
        dst_path = os.path.join(DST_DIR, out_name)

        if not os.path.exists(src_path):
            print(f"  SKIP {name}: {src_name}")
            continue

        img = Image.open(src_path)
        canvas = resize_fit_with_crop(img, target_w, target_h, master_bbox)
        canvas.save(dst_path)
        print(f"  {out_name}: {canvas.size}")

        # Blink variant
        blink_src = os.path.join(SRC_DIR, f"{src_prefix}-{src_suffix}-blink.png" if src_suffix else f"{src_prefix}-blink.png")
        blink_out = f"mermaid_{name}_{out_suffix}_blink.png" if out_suffix else f"mermaid_{name}_blink.png"
        blink_dst = os.path.join(DST_DIR, blink_out)
        if os.path.exists(blink_src):
            img = Image.open(blink_src)
            canvas = resize_fit_with_crop(img, target_w, target_h, master_bbox)
            canvas.save(blink_dst)
            print(f"  {blink_out}: {canvas.size}")


def build_lifecycle():
    """Process egg, baby, and kid lifecycle sprites with consistent sizing."""
    egg_variants = [("", ""), ("crack", "crack"), ("hatch", "hatch")]
    process_lifecycle_group("egg", "mermaid-egg", egg_variants, EGG_W, EGG_H)

    baby_variants = [("", ""), ("happy", "happy"), ("cry", "cry"), ("excite", "excite"), ("full", "full"), ("sleep", "sleep"), ("dirty", "dirty")]
    process_lifecycle_group("baby", "mermaid-baby", baby_variants, MERMAID_W, MERMAID_H)

    kid_variants = [("", ""), ("cry", "cry"), ("excite", "excite"), ("sleep", "sleep"), ("dirty", "dirty")]
    process_lifecycle_group("kid", "mermaid-kid", kid_variants, MERMAID_W, MERMAID_H)


def build_backgrounds():
    """Copy backgrounds, ensuring 640x480."""
    names = [
        "bg_atlantis", "bg_beach", "bg_castle", "bg_coral",
        "bg_lagoon", "bg_night", "bg_reef", "bg_space", "bg_sunset"
    ]
    for base in names:
        src = os.path.join(SRC_DIR, f"{base}.png")
        if not os.path.exists(src):
            print(f"  SKIP background: {base}")
            continue
        size = copy_or_resize(src, os.path.join(DST_DIR, f"{base}.png"), BG_W, BG_H)
        print(f"  {base}.png: {size}")


def build_foods():
    """Process food items to animation and icon sizes."""
    foods = ["burger", "cupcake", "ice-cream", "matcha", "oyster", "strawberry", "sushi"]

    for food in foods:
        base = food.replace("-", "_")
        src = os.path.join(SRC_DIR, f"food-{food}.png")
        if not os.path.exists(src):
            print(f"  SKIP food: {food}")
            continue

        # Animation size (80x80)
        img = resize_fit(Image.open(src), FOOD_W, FOOD_H)
        size = copy_or_resize(src, os.path.join(DST_DIR, f"food_{base}.png"), FOOD_W, FOOD_H)
        raw_size = convert_to_raw(img, os.path.join(DST_DIR, f"food_{base}.raw"))
        print(f"  food_{base}.png: {size}, .raw: {raw_size}")

        # Icon size (48x48)
        size = copy_or_resize(src, os.path.join(DST_DIR, f"food_{base}_icon.png"), FOOD_ICON_W, FOOD_ICON_H)
        print(f"  food_{base}_icon.png: {size}")

        # Eaten variant
        eaten_src = os.path.join(SRC_DIR, f"food-{food}-eaten.png")
        if os.path.exists(eaten_src):
            eaten_img = resize_fit(Image.open(eaten_src), FOOD_W, FOOD_H)
            size = copy_or_resize(eaten_src, os.path.join(DST_DIR, f"food_{base}_eaten.png"), FOOD_W, FOOD_H)
            raw_size = convert_to_raw(eaten_img, os.path.join(DST_DIR, f"food_{base}_eaten.raw"))
            print(f"  food_{base}_eaten.png: {size}, .raw: {raw_size}")


def build_particles():
    """Process particle sprites (hearts, sparkles, etc.)."""
    particles = ["heart_pink", "heart_red", "heart_gold"]
    for name in particles:
        src = os.path.join(SRC_DIR, f"particle_{name}.png")
        if not os.path.exists(src):
            print(f"  SKIP particle: {name}")
            continue
        img = resize_fit(Image.open(src), PARTICLE_W, PARTICLE_H)
        size = copy_or_resize(src, os.path.join(DST_DIR, f"particle_{name}.png"), PARTICLE_W, PARTICLE_H)
        raw_size = convert_to_raw(img, os.path.join(DST_DIR, f"particle_{name}.raw"))
        print(f"  particle_{name}.png: {size}, .raw: {raw_size}")

        # Multi-size variants for pink hearts (used by HEART_SPRITES in pet_fb_main.py)
        if name == "heart_pink":
            for w, h in [(32, 32), (48, 48), (64, 64)]:
                sized_img = resize_fit(Image.open(src), w, h)
                raw_size = convert_to_raw(sized_img, os.path.join(DST_DIR, f"particle_{name}_{w}.raw"))
                print(f"  particle_{name}_{w}.raw: {raw_size}")


def main():
    prepare_source()
    clear_dst()
    print("\n=== Building mermaid sprites ===")
    build_mermaids()
    print("\n=== Building lifecycle sprites ===")
    build_lifecycle()
    print("\n=== Building friends ===")
    build_friends()
    print("\n=== Building props ===")
    build_props()
    print("\n=== Building backgrounds ===")
    build_backgrounds()
    print("\n=== Building food items ===")
    build_foods()
    print("\n=== Building particles ===")
    build_particles()
    print(f"\n=== Done ===")
    print(f"Output: {DST_DIR}")
    files = sorted(os.listdir(DST_DIR))
    print(f"Generated {len(files)} files")


if __name__ == "__main__":
    main()
