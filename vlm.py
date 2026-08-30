from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from PIL import Image
from langchain_core.messages import SystemMessage, HumanMessage
import base64
import mimetypes

VLM = ChatGoogleGenerativeAI(model="gemini-2.5-flash")


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


def score_to_label(score: float) -> str:
    """Convert a raw cosine similarity score into a qualitative label.
    Raw floats anchor the VLM to the number (e.g. 0.58 reads as 'bad'
    even for a legitimate same-product return with different presentation).
    A qualitative label conveys the right context without numeric bias."""
    if score >= 0.75:
        return "HIGH (strong visual similarity)"
    elif score >= 0.60:
        return "MODERATE (acceptable similarity; presentation differences expected)"
    elif score >= 0.40:
        return "LOW (significant visual difference detected)"
    else:
        return "VERY LOW (images appear very different; possible image quality issue)"


def review(state: VLMState):
    delivery_image = image_to_data_url(state["delivery_path"])
    return_image = image_to_data_url(state["return_path"])
    score_label = score_to_label(state["similarity_score"])

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

The automated embedding similarity score for these images is: {score_label}

Your primary objective is HIGH PRECISION.

A false positive is particularly costly because it may incorrectly
reject a legitimate customer return and damage customer trust.

Therefore, DO NOT conclude that the returned product is different
unless there is convincing product-specific evidence.

Use both the visual comparison and the similarity score label.

---- CRITICAL GARMENT-SPECIFIC GUIDANCE ----
For clothing and garments, these differences are NORMAL and must NOT
be treated as evidence of fraud:

- At delivery time, garments are often folded, rolled, or presented
  in a way that HIDES decorative hem borders, bottom trim, edge patterns,
  or collar details. At return time, the full garment is spread out,
  REVEALING those borders and patterns that were always part of the design.
  Do NOT flag a visible hem/border pattern at return time as suspicious
  if the central body pattern matches the delivery image.

- The same print garment can look dramatically different across different
  photography conditions (flat-lay vs. held up, folded vs. spread, natural
  vs. artificial lighting). Focus on the CORE product-specific features:
  the central body pattern, colour palette, label, and structural shape.

- Crumpling, wrinkling, or loose presentation of the garment at return
  time is EXPECTED and does not indicate a different product.
---------------------------------------------

If the images appear to show the same product:
- Clearly state that they appear to be the same product.
- Explain the visual evidence supporting this conclusion.

If they appear different:
- Clearly state that they appear to be different products.
- Identify the exact location and nature of the differences.
- Explain why those differences suggest that the products are different
  and cannot be explained by presentation or folding.

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
Sub_Comparator_builder.add_node("reviewer", review)
Sub_Comparator_builder.add_edge(START, "reviewer")
Sub_Comparator_builder.add_edge("reviewer", END)
Sub_Comparator = Sub_Comparator_builder.compile()