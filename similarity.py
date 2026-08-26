from flask import Flask,request,render_template,Response,redirect
import os
from rembg import remove
from EmbeddingSimilarity import final_embedder
from DatabaseHandling import generate_order_id,add_similarity_data
from PIL import Image 
from torch import nn
from langchain_google_gemini import ChatGoogleGenerativeAI
from vlm import Sub_Comparator
from langgraph.graph import StateGraph,START,END
from typing import TypedDict
from MainLanggraph import MainAgent
app=Flask(__name__)
def remove_background(img):
    img=Image.open(img)
    blacked=remove(img)
    box=blacked.getbbox()
    blacked=blacked.crop(box)
    return blacked
@app.route('/')
def home():
    return render_template('home.html')
@app.route('/submit_delivery_image',methods=['POST'])
def submit_delivery_image():
    os.makedirs('delivery_images', exist_ok=True)
    os.makedirs('delivery_images/front', exist_ok=True)
    os.makedirs('delivery_images/back', exist_ok=True)
    os.makedirs('delivery_images/side', exist_ok=True)
    front_image=request.files.get('front_image')
    back_image=request.files.get('back_image')
    side_image=request.files.get('side_image')
    front_image=remove_background(front_image)
    back_image=remove_background(back_image)
    side_image=remove_background(side_image)
    order_id=str(generate_order_id())
    front_image.save(os.path.join('delivery_images/front',order_id+".png"))
    back_image.save(os.path.join('delivery_images/back',order_id+".png"))
    side_image.save(os.path.join('delivery_images/side',order_id+".png"))
    return Response(f"Delivery Images saved successfully with Order-ID{order_id}")
@app.route("/submit_return_images",methods=['POST'])
def submit_return_images():
    os.makedirs('return_images',exist_ok=True)
    os.makedirs('return_images/front',exist_ok=True)
    os.makedirs('return_images/back',exist_ok=True)
    os.makedirs('return_images/side',exist_ok=True)
    order_id=request.form.get("order_id")
    front_image=request.files.get('front_image')
    back_image=request.files.get('back_image')
    side_image=request.files.get('side_image')
    front_image=remove_background(front_image)
    back_image=remove_background(back_image)
    side_image=remove_background(side_image)
    front_image.save(os.path.join('return_images/front',order_id+".png"))
    back_image.save(os.path.join('return_images/back',order_id+".png"))
    side_image.save(os.path.join('return_images/side',order_id+".png"))
    Response("Processing the Return Images")
    results=MainAgent.invoke()
    status=fetch_status(order_id,similarity,status)
    return render_template("results.html",
                           results=results,
                           status=status,
                           order_id=order_id) # show results and status 

if __name__=="__main__":
    app.run(debug=True)
    
