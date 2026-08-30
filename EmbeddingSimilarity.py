from transformers import pipeline
import torch
from torch import nn
from PIL import Image

embedder = pipeline(model="facebook/dinov2-base",
                    task="image-feature-extraction")


def pad_to_square(image: Image.Image) -> Image.Image:
    """Pad image to a square with black borders, then resize to 448x448.
    This prevents aspect-ratio distortion caused by rembg cropping,
    which was a major cause of low similarity scores between delivery
    and return images that had different spatial layouts."""
    image = image.convert("RGB")
    w, h = image.size
    max_side = max(w, h)
    padded = Image.new("RGB", (max_side, max_side), (0, 0, 0))
    padded.paste(image, ((max_side - w) // 2, (max_side - h) // 2))
    return padded.resize((448, 448), Image.LANCZOS)


class FinalEmbedder(nn.Module):
    def __init__(self, embedder):
        super().__init__()
        self.embedder = embedder

    def forward(self, image: Image.Image):
        # Normalize image dimensions before embedding to avoid layout
        # sensitivity — the biggest cause of low scores for same products.
        image = pad_to_square(image)
        emb = self.embedder(image)

        # Use mean of all patch tokens instead of CLS token only.
        # CLS is dominated by global composition (spatial layout, framing).
        # Patch-mean pooling is more texture/pattern-focused, making it
        # robust to cropping, folding, and presentation differences.
        all_tokens = torch.tensor(emb[0])      # shape: [num_tokens, dim]
        patch_tokens = all_tokens[1:]           # drop CLS (index 0)
        embedding = patch_tokens.mean(dim=0)   # mean pool over patches
        return embedding


final_embedder = FinalEmbedder(embedder)