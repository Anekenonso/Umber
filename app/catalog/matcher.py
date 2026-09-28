"""Deterministic catalog matcher for Umber.

Implements Phase 8 requirement: catalog scoring is strictly deterministic code,
never an LLM call. The matcher is authoritative on WHAT gets recommended.
Guarantees: Same input always produces the same, non-empty match.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CATALOG_PATH = Path(__file__).resolve().parent / "items.json"


def hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    """Convert hex string (e.g., '#8d5524' or '8d5524') to RGB tuple."""
    clean = hex_str.lstrip("#")
    if len(clean) == 3:
        clean = "".join(c * 2 for c in clean)
    if len(clean) != 6:
        return (128, 128, 128)
    return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16))


def estimate_undertone_and_depth(r: int, g: int, b: int) -> Tuple[str, str]:
    """Deterministically estimate undertone and depth from skin RGB."""
    # Luminance estimate (0 - 255)
    luminance = 0.299 * r + 0.587 * g + 0.114 * b

    if luminance > 200:
        depth = "fair"
    elif luminance > 150:
        depth = "light"
    elif luminance > 110:
        depth = "medium"
    elif luminance > 70:
        depth = "deep"
    else:
        depth = "rich"

    # Undertone heuristic: red vs blue/green balance
    # Warm: R noticeably greater than B and G
    # Cool: B closer to R, or higher blue/pinkish
    # Neutral: balanced
    if r > (b + 30) and r > (g + 10):
        undertone = "warm"
    elif b > g or abs(r - b) < 15:
        undertone = "cool"
    else:
        undertone = "neutral"

    return undertone, depth


class CatalogMatcher:
    """Deterministic product matcher matching skin tones to curated catalog items."""

    def __init__(self, catalog_path: Optional[Path] = None):
        self.catalog_path = catalog_path or CATALOG_PATH
        self.items = self._load_catalog()

    def _load_catalog(self) -> List[Dict[str, Any]]:
        with open(self.catalog_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def score_item(
        self,
        item: Dict[str, Any],
        undertone: str,
        depth: str,
        skin_rgb: Tuple[int, int, int],
    ) -> float:
        """Deterministic scoring function:
        
        - Undertone match: +50 points (exact), +25 (neutral)
        - Depth match: +30 points (exact), +15 (adjacent)
        - Visual contrast: 0-20 points based on Euclidean RGB contrast
        """
        score = 0.0

        # Undertone scoring
        item_undertone = item.get("undertone", "neutral")
        if item_undertone == undertone:
            score += 50.0
        elif item_undertone == "neutral" or undertone == "neutral":
            score += 25.0

        # Depth scoring
        item_depth = item.get("tone_depth", "medium")
        if item_depth == depth:
            score += 30.0
        elif depth in ("fair", "light") and item_depth in ("fair", "light"):
            score += 20.0
        elif depth in ("deep", "rich") and item_depth in ("deep", "rich"):
            score += 20.0

        # Contrast scoring: contrast between skin and garment color
        item_rgb = hex_to_rgb(item.get("hex", "#000000"))
        rgb_distance = (
            (skin_rgb[0] - item_rgb[0]) ** 2
            + (skin_rgb[1] - item_rgb[1]) ** 2
            + (skin_rgb[2] - item_rgb[2]) ** 2
        ) ** 0.5
        # Normalize distance (max distance is ~441)
        score += min(20.0, (rgb_distance / 441.0) * 20.0)

        return score

    def match_hex(self, hex_color: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Match items against a skin tone hex color string."""
        rgb = hex_to_rgb(hex_color)
        undertone, depth = estimate_undertone_and_depth(*rgb)

        scored = []
        for item in self.items:
            s = self.score_item(item, undertone, depth, rgb)
            # Deterministic tuple for sorting: (-score, sku)
            scored.append((s, item["sku"], item))

        scored.sort(key=lambda x: (-x[0], x[1]))
        return [item for _, _, item in scored[:limit]]

    def match_skin_tone_data(
        self,
        skin_data: Dict[str, Any],
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """Match items from YouCam skin-tone-analysis task output.
        
        Expected fields from YouCam skin-tone-analysis:
        e.g. {'skin_color': '#8d5524', 'undertone': 'warm'}
        """
        hex_color = skin_data.get("skin_color") or skin_data.get("hex") or "#b87333"
        return self.match_hex(hex_color, limit=limit)


# Global default matcher
catalog_matcher = CatalogMatcher()
