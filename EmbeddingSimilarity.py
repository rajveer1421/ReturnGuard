from transformers import pipeline 
import torch 
from torch import nn
embedder=pipeline(model="facebook/dinov2-base",
                  task="image-feature-extraction" )
class FinalEmbedder(nn.Module):
    def __init__(self,embedder):
        super().__init__()
        self.embedder=embedder
    def forward(self,image):
        emb=self.embedder(image)
        cls=torch.tensor(emb[0][0])
        return cls
final_embedder=FinalEmbedder(embedder)