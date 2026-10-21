"""Visual screen: free, local comparison that decides whether an LLM is needed."""
import numpy as np

from returnguard import config
from returnguard.embeddings import ViewFeatures, color_shift, shape_similarity


def visual_screen(delivery: dict[str, ViewFeatures], returned: dict[str, ViewFeatures]) -> dict:
    shape = {a: round(shape_similarity(delivery[a], returned[a]), 4) for a in config.ANGLES}
    color = {a: round(color_shift(delivery[a], returned[a]), 2) for a in config.ANGLES}
    shape_mean = float(np.mean(list(shape.values())))
    shape_min = float(min(shape.values()))
    color_median = float(np.median(list(color.values())))

    if shape_mean < config.FAST_REJECT_SHAPE:
        verdict = "clear_mismatch"
    elif (shape_mean >= config.FAST_ACCEPT_SHAPE and shape_min >= config.FAST_ACCEPT_MIN_VIEW
          and color_median <= config.FAST_ACCEPT_MAX_COLOR_SHIFT):
        verdict = "strong_match"
    else:
        verdict = "ambiguous"
    return {"shape": shape, "color_shift": color, "shape_mean": round(shape_mean, 4),
            "shape_min": round(shape_min, 4), "color_shift_median": round(color_median, 2), "verdict": verdict}
