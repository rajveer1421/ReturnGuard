from langchain_google_gemini import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from PIL import Image
from langchain_core.messages import SystemMessage, HumanMessage
import base64
import mimetypes

VLM = ChatGoogleGenerativeAI()


class VLMState(TypedDict):
    delivery_path: str
    return_path: str
    vlm_review: str
    similarity_score: float


def image_to_data_url(path):

    mime_type, _ = mimetypes.guess_type(path)

    with open(path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    return f"data:{mime_type};base64,{image_data}"


def review(state: VLMState):

    delivery_image = image_to_data_url(state["delivery_path"])
    return_image = image_to_data_url(state["return_path"])

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

Your primary objective is HIGH PRECISION.

A false positive is particularly costly because it may incorrectly
reject a legitimate customer return and damage customer trust.

Therefore, DO NOT conclude that the returned product is different
unless there is convincing product-specific evidence.

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
                        "url": delivery_image
                    }
                },
                {
                    "type": "text",
                    "text": "Return-time image:"
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": return_image
                    }
                }
            ]
        )
    ]

    response = VLM.invoke(messages)

    return {
        "vlm_review": response.content
    }


Sub_Comparator_builder = StateGraph(VLMState)
Sub_Comparator_builder.add_node("reviewer",review)
Sub_Comparator_builder.add_edge(START,"reviewer")
Sub_Comparator_builder.add_edge("reviewer",END)
Sub_Comparator = Sub_Comparator_builder.compile()