#!/usr/bin/env python3
"""Extract all pet assets from source sprite sheets with proper background removal."""

import os
from PIL import Image

ASSET_DIR = "/home/<YOUR_USER>/Nextcloud/Projects/cyberdeck/config/opt-cyberdeck-pet/fb_assets"
os.makedirs(ASSET_DIR, exist_ok=True)

# ── Background removal helpers ──────────────────────────────────────────

def find_checkerboard_colors(img, sample_step=8, min_grey=50, max_grey=260):
    """Find the two checkerboard grey colors by sampling border pixels."""
    w, h = img.size
    pixels = img.load()
    samples = []
    for x in range(0, w, sample_step):
        samples.append(pixels[x, 0])
        samples.append(pixels[x, h - 1])
    for y in range(0, h, sample_step):
        samples.append(pixels[0, y])
        samples.append(pixels[w - 1, y])
    
    from collections import Counter
    grey_samples = []
    for c in samples:
        if len(c) >= 3:
            r, g, b = c[0], c[1], c[2]
        else:
            continue
        if abs(int(r) - int(g)) < 25 and abs(int(g) - int(b)) < 25 and min_grey < r < max_grey:
            grey_samples.append((r, g, b))
    
    if len(grey_samples) < 5:
        return None
    
    rounded = [(r//5*5, g//5*5, b//5*5) for r,g,b in grey_samples]
    most_common = Counter(rounded).most_common(3)
    if len(most_common) < 2:
        return None
    
    c1 = most_common[0][0]
    c2 = most_common[1][0]
    return c1, c2

def remove_checkerboard(img, cb_colors=None, tol=40):
    """Make checkerboard pixels transparent."""
    img = img.convert("RGBA")
    if cb_colors is None:
        cb = find_checkerboard_colors(img)
        if not cb:
            return img
        c1, c2 = cb
    else:
        c1, c2 = cb_colors
    pixels = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            d1 = abs(r - c1[0]) + abs(g - c1[1]) + abs(b - c1[2])
            d2 = abs(r - c2[0]) + abs(g - c2[1]) + abs(b - c2[2])
            if d1 < tol * 3 or d2 < tol * 3:
                pixels[x, y] = (0, 0, 0, 0)
    return img

def remove_black(img, threshold=25):
    """Make near-black pixels transparent."""
    img = img.convert("RGBA")
    pixels = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if r < threshold and g < threshold and b < threshold:
                pixels[x, y] = (0, 0, 0, 0)
    return img

def crop_to_content(img, pad=2):
    """Crop to bounding box of non-transparent pixels."""
    bbox = img.getbbox()
    if not bbox:
        return img
    x1, y1, x2, y2 = bbox
    w, h = img.size
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(w, x2 + pad)
    y2 = min(h, y2 + pad)
    return img.crop((x1, y1, x2, y2))

def resize_sprite(img, target_w=158, target_h=264):
    """Resize maintaining aspect ratio, center in target size."""
    img = crop_to_content(img)
    w, h = img.size
    ratio = min(target_w / w, target_h / h)
    new_w = int(w * ratio)
    new_h = int(h * ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    ox = (target_w - new_w) // 2
    oy = (target_h - new_h) // 2
    canvas.paste(img, (ox, oy), img)
    return canvas

def resize_backdrop(img, target_w=640, target_h=480):
    """Resize backdrop to fill target size."""
    return img.resize((target_w, target_h), Image.LANCZOS)

def extract_grid(img_path, rows, cols, names, remove_bg_fn, target_size=(158, 264),
                 region=None, text_bottom_px=0, cb_colors=None):
    """Extract sprites from a regular grid."""
    img = Image.open(img_path)
    if region:
        img = img.crop(region)
    w, h = img.size
    cell_w = w // cols
    cell_h = h // rows
    
    results = {}
    for idx, name in enumerate(names):
        row = idx // cols
        col = idx % cols
        x1 = col * cell_w
        y1 = row * cell_h
        x2 = x1 + cell_w
        y2 = y1 + cell_h
        
        if text_bottom_px > 0:
            y2 -= text_bottom_px
        
        sprite = img.crop((x1, y1, x2, y2))
        
        import inspect
        sig = inspect.signature(remove_bg_fn)
        if 'cb_colors' in sig.parameters:
            sprite = remove_bg_fn(sprite, cb_colors=cb_colors)
        else:
            sprite = remove_bg_fn(sprite)
        
        if target_size:
            if target_size == (640, 480):
                sprite = resize_backdrop(sprite, *target_size)
            else:
                sprite = resize_sprite(sprite, *target_size)
        
        out_path = os.path.join(ASSET_DIR, f"{name}.png")
        sprite.save(out_path)
        results[name] = out_path
        print(f"  {name}: {sprite.size}")
    
    return results

# ── Mood sprites ────────────────────────────────────────────────────────

print("Extracting mood sprites from black-bg sheet...")
extract_grid(
    "/home/<YOUR_USER>/Downloads/openart-gpt-image-2-edit-1_1776888933262_bb1be916.png",
    rows=2, cols=3,
    names=["mermaid_happy", "mermaid_excited", "mermaid_cranky",
           "mermaid_sick", "mermaid_hungry", "mermaid_sad"],
    remove_bg_fn=remove_black,
    target_size=(158, 264),
    text_bottom_px=50,
)

print("\nExtracting mood sprites from checkered sheet...")
mood_cb = find_checkerboard_colors(
    Image.open("/home/<YOUR_USER>/Downloads/openart-gpt-image-2-edit-1_1776890324521_1f2ff8b6.png"),
    min_grey=180, max_grey=260)
print(f"  Detected checkerboard colors: {mood_cb}")
extract_grid(
    "/home/<YOUR_USER>/Downloads/openart-gpt-image-2-edit-1_1776890324521_1f2ff8b6.png",
    rows=2, cols=2,
    names=["mermaid_love", "mermaid_dirty", "mermaid_sleep", "mermaid_neutral"],
    remove_bg_fn=remove_checkerboard,
    target_size=(158, 264),
    cb_colors=mood_cb,
)

print("\nExtracting blink states for 6 expressions...")
blink_cb = find_checkerboard_colors(
    Image.open("/home/<YOUR_USER>/Downloads/openart-image_1776891828475_5ee3a459_1776891828715_9db2c701.png"),
    min_grey=50, max_grey=260)
print(f"  Detected checkerboard colors: {blink_cb}")
extract_grid(
    "/home/<YOUR_USER>/Downloads/openart-image_1776891828475_5ee3a459_1776891828715_9db2c701.png",
    rows=2, cols=3,
    names=["blink_happy", "blink_excited", "blink_cranky",
           "blink_sick", "blink_hungry", "blink_sad"],
    remove_bg_fn=remove_checkerboard,
    target_size=(158, 264),
    cb_colors=blink_cb,
)

# ── Outfits ─────────────────────────────────────────────────────────────

print("\nExtracting outfits...")
outfit_cb = find_checkerboard_colors(
    Image.open("/home/<YOUR_USER>/Downloads/openart-image_1776890739338_6102db28_1776890739466_257bce18.png"),
    min_grey=50, max_grey=260)
print(f"  Detected checkerboard colors: {outfit_cb}")
extract_grid(
    "/home/<YOUR_USER>/Downloads/openart-image_1776890739338_6102db28_1776890739466_257bce18.png",
    rows=3, cols=5,
    names=["outfit_lavender", "outfit_pearl", "outfit_teal", "outfit_coral", "outfit_royal",
           "outfit_mint", "outfit_sunset", "outfit_midnight", "outfit_golden", "outfit_aqua",
           "outfit_shell", "outfit_forest", "outfit_volcano", "outfit_silver", "outfit_moss"],
    remove_bg_fn=remove_checkerboard,
    target_size=(158, 264),
    cb_colors=outfit_cb,
)

print("\nExtracting outfit blink states...")
outfit_blink_cb = find_checkerboard_colors(
    Image.open("/home/<YOUR_USER>/Downloads/openart-image_1776892047816_5313f679_1776892047905_5e616f42.png"),
    min_grey=50, max_grey=260)
print(f"  Detected checkerboard colors: {outfit_blink_cb}")
extract_grid(
    "/home/<YOUR_USER>/Downloads/openart-image_1776892047816_5313f679_1776892047905_5e616f42.png",
    rows=3, cols=5,
    names=["outfit_blink_lavender", "outfit_blink_pearl", "outfit_blink_teal", 
           "outfit_blink_coral", "outfit_blink_royal",
           "outfit_blink_mint", "outfit_blink_sunset", "outfit_blink_midnight", 
           "outfit_blink_golden", "outfit_blink_aqua",
           "outfit_blink_shell", "outfit_blink_forest", "outfit_blink_volcano", 
           "outfit_blink_silver", "outfit_blink_moss"],
    remove_bg_fn=remove_checkerboard,
    target_size=(158, 264),
    cb_colors=outfit_blink_cb,
)

# ── Backdrops ───────────────────────────────────────────────────────────

print("\nExtracting backdrops...")
extract_grid(
    "/home/<YOUR_USER>/Downloads/openart-image_1776891498647_38e0e1a2_1776891498760_67a98dc9.png",
    rows=3, cols=3,
    names=["bg_coral", "bg_night", "bg_castle",
           "bg_atlantis", "bg_reef", "bg_sunset",
           "bg_beach", "bg_lagoon", "bg_space"],
    remove_bg_fn=lambda x, **kw: x,
    target_size=(640, 480),
)

print("\nAll assets extracted!")
