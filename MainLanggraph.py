from torch import nn
from langchain_google_gemini import ChatGoogleGenerativeAI
from vlm import Sub_Comparator
from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from flask import Response
from DatabaseHandling import generate_order_id, add_similarity_data
import os
from PIL import Image
from EmbeddingSimilarity import final_embedder
from langchain_core.messages import HumanMessage, SystemMessage

final_judge = ChatGoogleGenerativeAI()

class MainState(TypedDict):
    order_id: int
    front_score: float
    back_score: float
    side_score: float
    avg_score: float
    front_review: str
    back_review: str
    side_review: str
    main_review: str
    status: str


def similarity_check(e1, e2):
    similarity = nn.functional.cosine_similarity(e1, e2, dim=0)
    return similarity.item()


def compare_images(state: MainState):
    Response("Comparing the Images")

    front_emb = final_embedder(
        Image.open(
            os.path.join(
                "delivery_images/front",
                str(state["order_id"]) + ".png"
            )
        )
    )

    back_emb = final_embedder(
        Image.open(
            os.path.join(
                "delivery_images/back",
                str(state["order_id"]) + ".png"
            )
        )
    )

    side_emb = final_embedder(
        Image.open(
            os.path.join(
                "delivery_images/side",
                str(state["order_id"]) + ".png"
            )
        )
    )

    front_emb1 = final_embedder(
        Image.open(
            os.path.join(
                "return_images/front",
                str(state["order_id"]) + ".png"
            )
        )
    )

    back_emb1 = final_embedder(
        Image.open(
            os.path.join(
                "return_images/back",
                str(state["order_id"]) + ".png"
            )
        )
    )

    side_emb1 = final_embedder(
        Image.open(
            os.path.join(
                "return_images/side",
                str(state["order_id"]) + ".png"
            )
        )
    )

    front_sim = similarity_check(front_emb, front_emb1)
    back_sim = similarity_check(back_emb, back_emb1)
    side_sim = similarity_check(side_emb, side_emb1)

    avg_sim = (front_sim + back_sim + side_sim) / 3.0

    return {
        "front_score": front_sim,
        "side_score": side_sim,
        "back_score": back_sim,
        "avg_score": avg_sim
    }


def vlm_router(state: MainState):
    status: str

    if state["avg_score"] > 0.8:
        status = "RETURN_ACCEPTED"
    else:
        status = "PASSED TO VLM FOR REVIEW"

    add_similarity_data(
        state["order_id"],
        state["avg_score"],
        status
    )

    return {
        "status": status
    }


def router(state: MainState):
    if state["status"] == "RETURN_ACCEPTED":
        return "accept"
    else:
        return "vlm"


def vlm_review(state: MainState):
    return {}


def front_vlm(state: MainState):
    delivery_path = os.path.join(
        "delivery_images/front",
        str(state["order_id"]) + ".png"
    )

    return_path = os.path.join(
        "return_images/front",
        str(state["order_id"]) + ".png"
    )

    initial_state = {
        "delivery_path": delivery_path,
        "return_path": return_path,
        "vlm_review": None,
        "similarity_score": state["front_score"]
    }

    result = Sub_Comparator.invoke(initial_state)

    return {
        "front_review": result["vlm_review"]
    }


def back_vlm(state: MainState):
    delivery_path = os.path.join(
        "delivery_images/back",
        str(state["order_id"]) + ".png"
    )

    return_path = os.path.join(
        "return_images/back",
        str(state["order_id"]) + ".png"
    )

    initial_state = {
        "delivery_path": delivery_path,
        "return_path": return_path,
        "vlm_review": None,
        "similarity_score": state["back_score"]
    }

    result = Sub_Comparator.invoke(initial_state)

    return {
        "back_review": result["vlm_review"]
    }


def side_vlm(state: MainState):
    delivery_path = os.path.join(
        "delivery_images/side",
        str(state["order_id"]) + ".png"
    )

    return_path = os.path.join(
        "return_images/side",
        str(state["order_id"]) + ".png"
    )

    initial_state = {
        "delivery_path": delivery_path,
        "return_path": return_path,
        "vlm_review": None,
        "similarity_score": state["side_score"]
    }

    result = Sub_Comparator.invoke(initial_state)

    return {
        "side_review": result["vlm_review"]
    }


def main_llm(state: MainState):

    messages = [
        SystemMessage(
            content="""
You are the final decision-making reviewer for an e-commerce return
verification system.

You will receive three independent VLM reviews:
1. Front-view review
2. Back-view review
3. Side-view review

The images were captured at delivery time and again at return time.
Before reaching you, each corresponding pair of images was compared
using DINOv2 cosine similarity. Images with ambiguous similarity
scores were then sent to the three VLM reviewers.

Your task is to carefully analyze all three VLM reviews and produce
a final decision.

Your primary objective is HIGH PRECISION.

A false positive is particularly costly because it may incorrectly
reject a legitimate customer return and damage customer trust.
Therefore, DO NOT conclude that the returned product is different
unless there is convincing product-specific evidence.

Consider:
- Product shape and structure
- Color
- Dimensions/proportions
- Logos and labels
- Patterns and markings
- Scratches, dents, damage or distinctive features
- Any consistent difference across multiple views

Do NOT treat differences caused by:
- Lighting
- Camera angle
- Cropping
- Image quality
- Background-removal artifacts

as evidence of fraud unless the difference clearly affects the
actual product.

Your response MUST contain:

## FINAL JUDGEMENT
State one of:
- RETURN ACCEPTED
- RETURN REQUIRES HUMAN REVIEW

Do not reject a return solely because one VLM reports a weak or
uncertain difference.

## FRONT VLM
Summarize the important findings from the front-view VLM.

## BACK VLM
Summarize the important findings from the back-view VLM.

## SIDE VLM
Summarize the important findings from the side-view VLM.

## EVIDENCE
Explain the strongest evidence supporting your final judgement.

## REASONING
Explain how the three reviews collectively led to the decision.

When the evidence is ambiguous or conflicting, prefer HUMAN REVIEW
rather than rejecting the return.
"""
        ),
        HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": f"FRONT VLM REVIEW:\n{state['front_review']}"
                },
                {
                    "type": "text",
                    "text": f"BACK VLM REVIEW:\n{state['back_review']}"
                },
                {
                    "type": "text",
                    "text": f"SIDE VLM REVIEW:\n{state['side_review']}"
                }
            ]
        )
    ]

    response = final_judge.invoke(messages)

    return {
        "main_review": response.content
    }


MainAgent_builder = StateGraph(MainState)

MainAgent_builder.add_node(
    "embedding_comparision",
    compare_images
)

MainAgent_builder.add_node(
    "vlm_router",
    vlm_router
)

MainAgent_builder.add_node(
    "Tool_VLM",
    vlm_review
)

MainAgent_builder.add_node(
    "front_vlm",
    front_vlm
)

MainAgent_builder.add_node(
    "back_vlm",
    back_vlm
)

MainAgent_builder.add_node(
    "side_vlm",
    side_vlm
)

MainAgent_builder.add_node(
    "main_judge",
    main_llm
)

MainAgent_builder.add_edge(
    START,
    "embedding_comparision"
)

MainAgent_builder.add_edge(
    "embedding_comparision",
    "vlm_router"
)

MainAgent_builder.add_conditional_edges(
    "vlm_router",
    router,
    {
        "accept": END,
        "vlm": "Tool_VLM"
    }
)

MainAgent_builder.add_edge(
    "Tool_VLM",
    "front_vlm"
)

MainAgent_builder.add_edge(
    "Tool_VLM",
    "back_vlm"
)

MainAgent_builder.add_edge(
    "Tool_VLM",
    "side_vlm"
)

MainAgent_builder.add_edge(
    "front_vlm",
    "main_judge"
)

MainAgent_builder.add_edge(
    "back_vlm",
    "main_judge"
)

MainAgent_builder.add_edge(
    "side_vlm",
    "main_judge"
)

MainAgent_builder.add_edge(
    "main_judge",
    END
)

MainAgent = MainAgent_builder.compile()