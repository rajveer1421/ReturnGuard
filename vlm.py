from langchain_google_gemini import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START,END
from PIL import Image
from typing import TypedDict
VLM=ChatGoogleGenerativeAI()
class VLMState(TypedDict):
    delivery_path:str
    return_path:str
    vlm_review:str
    similarity_score:float
from PIL import Image
from langchain_core.messages import SystemMessage, HumanMessage

def review(state:VLMState):
    messages = [
        SystemMessage(
            content=f"""
You will be given two images of the same product:

1. Image 1: The product at delivery time.
2. Image 2: The product at return time.

Act as a product image inspector. Compare the two images and determine
whether they appear to show the same physical product.

The goal is to identify possible return fraud, where a customer returns
a different product instead of the product that was originally delivered.

The similarity score produced by the DINOv2 model using cosine similarity is:
{state["similarity_score"]}

Use both the visual comparison and the similarity score.

If the images appear to show the same product:
- Clearly state that they appear to be the same product.
- Explain the visual evidence supporting this conclusion.

If they appear different:
- Clearly state that they appear to be different products.
- Identify the exact location and nature of the differences.
- Explain why those differences suggest that the products are different.

Important considerations:
- The background has been removed from both images.
- Ignore black areas caused by background removal.
- Background-removal errors may leave some background behind.
- Background-removal errors may also remove small portions of the actual object.
- Do not consider minor missing/extra background pixels as evidence of fraud.
- Be tolerant of small changes caused by lighting, camera angle, cropping,
  image quality, or background-removal errors.
- Focus primarily on product-specific features such as shape, structure,
  dimensions, color, patterns, labels, logos, scratches, dents, and other
  distinctive characteristics.

Give the final conclusion in simple language with a clear justification.
"""
        ),
        HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": "Delivery-time image:"
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": state["delivery_path"]
                    }
                },
                {
                    "type": "text",
                    "text": "Return-time image:"
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": state["return_path"]
                    }
                }
            ]
        )
    ]

    response = VLM.invoke(messages)

    return {"vlm_review":response.content}
Sub_Comparator_builder=StateGraph(VLMState)
Sub_Comparator_builder.add_node("reviewer",review)
Sub_Comparator_builder.add_edge(START,"review")
Sub_Comparator_builder.add_edge("review","END")
Sub_Comparator=Sub_Comparator_builder.compile()
