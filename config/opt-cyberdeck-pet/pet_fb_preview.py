#!/usr/bin/env python3
"""Generate a preview grid of all pet assets."""
import os
from PIL import Image, ImageDraw, ImageFont

ASSET_DIR = os.path.join(os.path.dirname(__file__), "fb_assets")

def load(name):
    return Image.open(os.path.join(ASSET_DIR, name)).convert("RGBA")

def label(d, text, x, y, size=14):
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except:
        font = ImageFont.load_default()
    d.text((x + 1, y + 1), text, fill=(0, 0, 0, 200), font=font)
    d.text((x, y), text, fill=(255, 255, 255, 255), font=font)

THUMB_W, THUMB_H = 160, 120
SPRITE_W, SPRITE_H = 100, 140
FRIEND_W, FRIEND_H = 80, 80
PROP_W, PROP_H = 60, 60
FOOD_SIZE = 48
GAP = 10
MARGIN = 15

bgs = [f"bg_{n}.png" for n in ["coral", "beach", "night", "castle", "atlantis", "lagoon", "reef", "sunset", "space"]]
expressions = [f"mermaid_{n}.png" for n in ["happy", "sad", "excited", "sick", "hungry", "pissed", "heart", "sleep", "tired", "wink", "clean", "dirty"]]
outfits = [f"outfit_{n}.png" for n in ["blue", "galaxy", "green", "rainbow"]]
friends = ["friend_crab.png", "friend_dolphin.png"]
props = ["prop_oyster.png"]
foods = [f"food_{n}_icon.png" for n in ["burger", "cupcake", "ice_cream", "matcha", "oyster", "strawberry", "sushi"]]

max_row = max(len(bgs), len(expressions), len(outfits), len(friends) + len(props), len(foods))
w = MARGIN * 2 + max_row * (THUMB_W + GAP)
h = MARGIN * 2 + 7 * (SPRITE_H + GAP + 25) + 100

img = Image.new("RGBA", (w, h), (20, 25, 35, 255))
d = ImageDraw.Draw(img)

y = MARGIN

d.text((MARGIN, y), "MERMAID PET ASSET PREVIEW", fill=(255, 200, 100, 255))
y += 30

# Row 1: Backgrounds
d.text((MARGIN, y), "BACKGROUNDS", fill=(200, 200, 255, 255))
y += 20
for i, bg_name in enumerate(bgs):
    x = MARGIN + i * (THUMB_W + GAP)
    bg = load(bg_name).resize((THUMB_W, THUMB_H), Image.LANCZOS)
    img.paste(bg, (x, y))
    label(d, bg_name.replace("bg_", "").replace(".png", ""), x + 5, y + THUMB_H - 20, 12)
y += THUMB_H + GAP + 10

# Row 2: Expressions
d.text((MARGIN, y), "EXPRESSIONS", fill=(200, 200, 255, 255))
y += 20
for i, expr_name in enumerate(expressions):
    x = MARGIN + i * (SPRITE_W + GAP)
    sprite = load(expr_name).resize((SPRITE_W, SPRITE_H), Image.LANCZOS)
    img.paste(sprite, (x, y), sprite)
    label(d, expr_name.replace("mermaid_", "").replace(".png", ""), x + 5, y + SPRITE_H - 18, 11)
y += SPRITE_H + GAP + 10

# Row 3: Outfits
d.text((MARGIN, y), "OUTFITS", fill=(200, 200, 255, 255))
y += 20
for i, outfit_name in enumerate(outfits):
    x = MARGIN + i * (SPRITE_W + GAP)
    sprite = load(outfit_name).resize((SPRITE_W, SPRITE_H), Image.LANCZOS)
    img.paste(sprite, (x, y), sprite)
    label(d, outfit_name.replace("outfit_", "").replace(".png", ""), x + 5, y + SPRITE_H - 18, 11)
y += SPRITE_H + GAP + 10

# Row 4: Friends & Props
d.text((MARGIN, y), "FRIENDS & PROPS", fill=(200, 200, 255, 255))
y += 20
for i, name in enumerate(friends + props):
    x = MARGIN + i * (FRIEND_W + GAP)
    sprite = load(name).resize((FRIEND_W, FRIEND_H), Image.LANCZOS)
    img.paste(sprite, (x, y), sprite)
    label(d, name.replace("friend_", "").replace("prop_", "").replace(".png", ""), x + 5, y + FRIEND_H - 18, 11)
y += FRIEND_H + GAP + 10

# Row 5: Foods
d.text((MARGIN, y), "FOODS", fill=(200, 200, 255, 255))
y += 20
for i, food_name in enumerate(foods):
    x = MARGIN + i * (FOOD_SIZE + GAP + 40)
    food = load(food_name)
    bx, by = x, y
    img.paste(food, (bx + 20, by + 20), food)
    label(d, food_name.replace("food_", "").replace("_icon.png", ""), bx + 10, by + FOOD_SIZE + 30, 11)

out_path = os.path.join(os.path.dirname(__file__), "preview_all_assets.png")
img.save(out_path)
print(f"Preview saved to: {out_path}")
