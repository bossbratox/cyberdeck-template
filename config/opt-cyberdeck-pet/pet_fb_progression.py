#!/usr/bin/env python3
"""Progression system: milestones, unlocks, and notifications."""

# Milestone definitions: condition string → evaluated by ProgressionManager
MILESTONES = {
    # Outfits
    "outfit_blue":    {"type": "outfit", "name": "blue",    "condition": lambda s: True},
    "outfit_galaxy":  {"type": "outfit", "name": "galaxy",  "condition": lambda s: "bg_space" in s.unlocked_bgs},
    "outfit_green":   {"type": "outfit", "name": "green",   "condition": lambda s: s.age_days >= 3},
    "outfit_rainbow": {"type": "outfit", "name": "rainbow", "condition": lambda s: s.age_days >= 7},

    # Backgrounds (visit-based)
    "bg_coral":       {"type": "bg", "name": "coral",    "condition": lambda s: s.visit_counts.get("coral", 0) >= 0},
    "bg_beach":       {"type": "bg", "name": "beach",    "condition": lambda s: s.visit_counts.get("beach", 0) >= 5},
    "bg_night":       {"type": "bg", "name": "night",    "condition": lambda s: s.visit_counts.get("night", 0) >= 10},
    "bg_castle":      {"type": "bg", "name": "castle",   "condition": lambda s: s.visit_counts.get("castle", 0) >= 20},
    "bg_atlantis":    {"type": "bg", "name": "atlantis", "condition": lambda s: s.visit_counts.get("atlantis", 0) >= 35},
    "bg_lagoon":      {"type": "bg", "name": "lagoon",   "condition": lambda s: s.visit_counts.get("lagoon", 0) >= 50},
    "bg_reef":        {"type": "bg", "name": "reef",     "condition": lambda s: s.visit_counts.get("reef", 0) >= 70},
    "bg_sunset":      {"type": "bg", "name": "sunset",   "condition": lambda s: s.visit_counts.get("sunset", 0) >= 90},
    "bg_space":       {"type": "bg", "name": "space",    "condition": lambda s: s.visit_counts.get("space", 0) >= 120},

    # Friends (crab from start, dolphin at 5 feeds, rest via lifecycle milestones)
    "friend_crab":    {"type": "friend", "name": "crab",    "condition": lambda s: True},
    "friend_dolphin": {"type": "friend", "name": "dolphin", "condition": lambda s: s.total_feeds >= 5},
}


class ProgressionManager:
    """Checks milestones and reports new unlocks."""

    def __init__(self, state):
        self.state = state

    def check_all(self):
        """Check all milestones against current state. Returns list of newly unlocked milestone keys."""
        new_unlocks = []
        for key, meta in MILESTONES.items():
            if key in self.state.unlocked_milestones:
                continue
            if meta["condition"](self.state):
                self.state.unlocked_milestones.add(key)
                self._apply_unlock(meta)
                new_unlocks.append(key)
        return new_unlocks

    def _apply_unlock(self, meta):
        """Add unlocked item to the appropriate state list."""
        t = meta["type"]
        name = meta["name"]
        if t == "outfit" and name not in self.state.unlocked_outfits:
            self.state.unlocked_outfits.append(name)
        elif t == "bg" and name not in self.state.unlocked_bgs:
            self.state.unlocked_bgs.append(name)
        elif t == "friend" and name not in self.state.unlocked_friends:
            self.state.unlocked_friends.append(name)

    def check_bg_visit(self, bg_name):
        """Increment visit count for a background and check unlocks."""
        self.state.visit_counts[bg_name] = self.state.visit_counts.get(bg_name, 0) + 1
        return self.check_all()

    def check_feed(self):
        """Check unlocks after a feed action. (total_feeds already incremented in PetState.feed)"""
        return self.check_all()

    def check_play(self):
        """Record play action and check unlocks."""
        return self.check_all()

    def check_happiness(self):
        """Update max happiness and check unlocks."""
        if self.state.happiness > self.state.max_happiness:
            self.state.max_happiness = self.state.happiness
        return self.check_all()
