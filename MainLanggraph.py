from torch import nn
from langchain_google_gemini import ChatGoogleGenerativeAI
from vlm import Sub_Comparator
from langgraph.graph import StateGraph,START,END
from typing import TypedDict
from flask import Response
from DatabaseHandling import generate_order_id,add_similarity_data
from vlm import Sub_Comparator
import os 
class MainState(TypedDict):
    order_id:int
    front_score:float
    back_score:float
    side_score:float
    avg_score:float
    front_review:str
    back_review:str
    side_review:str
    main_review:str
def similarity_check(e1,e2):
    similarity=nn.functional.cosine_similarity(e1,e2,dim=0)
    return similarity.item()
def compare_images(state:MainState):
    Response("Comparing the Images")
    front_emb=final_embedder(Image.open(os.path.join('delivery_images/front',state["order_id"]+".png")))
    back_emb=final_embedder(Image.open(os.path.join('delivery_images/back',state["order_id"]+".png")))
    side_emb=final_embedder(Image.open(os.path.join('delivery_images/side',state["order_id"]+".png")))
    front_emb1=final_embedder(Image.open(os.path.join('return_images/front',state["order_id"]+".png")))
    back_emb1=final_embedder(Image.open(os.path.join('return_images/back',state["order_id"]+".png")))
    side_emb1=final_embedder(Image.open(os.path.join('return_images/side',state["order_id"]+".png")))
    front_sim=similarity_check(front_emb,front_emb1)
    back_sim=similarity_check(back_emb,back_emb1)
    side_sim=similarity_check(side_emb,side_emb1)
    avg_sim=(front_sim+back_sim+side_sim)/3.0
    return {"front_score":front_sim,
            "side_score":side_sim,
            "back_score":back_sim,
            "avg_score":avg_sim}
def vlm_router(state:MainState):
    status:str
    if avg_score>0.8:
            status="RETURN_ACCEPTED"
    else:
            status="PASSED TO VLM FOR REVIEW"
       
    add_similarity_data(order_id,avg_score,status)
    if status=="RETURN_ACCEPTED":
          return "END"
    else:
          return "Tool_VLM"
def vlm_review(state:MainState):
    return {}
def front_vlm(state:MainState):
     delivery_path:os.path.join("delivery_images/front",state["order_id"]+".png")
     return_path:os.path.join("return_images/front",state["order_id"+".png"])
     initial_state:{"delivery_path":delivery_path,"return_path":return_path,"vlm_review":None
                    ,"similarity_score":state["front_score"]}
     Sub_Comparator.invoke(intial_state)
     return{"front_review":initial_state["vlm_review"]}
def back_vlm(state:MainState):
     delivery_path:os.path.join("delivery_images/back",state["order_id"]+".png")
     return_path:os.path.join("return_images/back",state["order_id"]+".png")
     initial_state:{"delivery_path":delivery_path,"return_path":return_path,"vlm_review":None,
                    "similarity_score":state["back_score"]}
     Sub_Comparator.invoke(initial_state)
     return{"back_review":initial_state["vlm_review"]}
def side_vlm(state:MainState):
     delivery_path:os.path.join("delivery_images/side",state["order_id"]+".png")
     return_path:os.path.join("return_images/side",state["order_id"]+".png")
     initial_state:{"delivery_path":delivery_path,"return_path":return_path,"vlm_review":None,
                    "similarity_score":state["side_score"]}
     Sub_Comparator.invoke(initial_state)
     return{"back_review":initial_state["vlm_review"]}




       


