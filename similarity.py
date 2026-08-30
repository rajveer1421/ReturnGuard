from flask import Flask, request, render_template, jsonify, redirect
import os
from rembg import remove
from EmbeddingSimilarity import final_embedder
from DatabaseHandling import generate_order_id, add_similarity_data, fetch_order, fetch_all_orders
from PIL import Image
from torch import nn
from langchain_google_genai import ChatGoogleGenerativeAI
from vlm import Sub_Comparator
from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from MainLanggraph import MainAgent
from DatabaseHandling import add_review_data

app = Flask(__name__)


def remove_background(img):
    img = Image.open(img)
    blacked = remove(img)
    box = blacked.getbbox()
    blacked = blacked.crop(box)
    return blacked


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/submit_delivery_image', methods=['POST'])
def submit_delivery_image():
    os.makedirs('delivery_images', exist_ok=True)
    os.makedirs('delivery_images/front', exist_ok=True)
    os.makedirs('delivery_images/back', exist_ok=True)
    os.makedirs('delivery_images/side', exist_ok=True)

    front_image = request.files.get('front_image')
    back_image = request.files.get('back_image')
    side_image = request.files.get('side_image')

    if not front_image or not back_image or not side_image:
        return jsonify({"success": False, "error": "All three images (front, back, side) are required."}), 400

    front_image = remove_background(front_image)
    back_image = remove_background(back_image)
    side_image = remove_background(side_image)

    order_id = str(generate_order_id())

    front_image.save(os.path.join('delivery_images/front', order_id + ".png"))
    back_image.save(os.path.join('delivery_images/back', order_id + ".png"))
    side_image.save(os.path.join('delivery_images/side', order_id + ".png"))

    return jsonify({
        "success": True,
        "order_id": order_id,
        "message": f"Delivery images saved successfully with Order ID {order_id}"
    })


@app.route("/submit_return_images", methods=['POST'])
def submit_return_images():
    os.makedirs('return_images', exist_ok=True)
    os.makedirs('return_images/front', exist_ok=True)
    os.makedirs('return_images/back', exist_ok=True)
    os.makedirs('return_images/side', exist_ok=True)

    order_id = request.form.get("order_id")

    if not order_id:
        return jsonify({"success": False, "error": "Order ID is required."}), 400

    front_image = request.files.get('front_image')
    back_image = request.files.get('back_image')
    side_image = request.files.get('side_image')

    if not front_image or not back_image or not side_image:
        return jsonify({"success": False, "error": "All three images (front, back, side) are required."}), 400

    front_image = remove_background(front_image)
    back_image = remove_background(back_image)
    side_image = remove_background(side_image)

    front_image.save(os.path.join('return_images/front', order_id + ".png"))
    back_image.save(os.path.join('return_images/back', order_id + ".png"))
    side_image.save(os.path.join('return_images/side', order_id + ".png"))

    initial_state = {
        "order_id": order_id,
        "front_score": None,
        "back_score": None,
        "side_score": None,
        "avg_score": None,
        "front_review": None,
        "back_review": None,
        "side_review": None,
        "main_review": None,
        "status": None
    }

    results = MainAgent.invoke(initial_state)

    status = results["status"]
    if status == "PASSED TO VLM FOR REVIEW":
        if "vlm accepted" in results["main_review"].lower():
            status = "VLM Accepted"
        elif "human review" in results["main_review"].lower():
            status = "Human Review"
        else:
            status = "Rejected"

    add_review_data(
        order_id,
        results["front_score"],
        results["back_score"],
        results["side_score"],
        results["avg_score"],
        results["front_review"],
        results["back_review"],
        results["side_review"],
        results["main_review"],
        status
    )

    return jsonify({
        "success": True,
        "order_id": order_id,
        "status": status,
        "front_score": results["front_score"],
        "back_score": results["back_score"],
        "side_score": results["side_score"],
        "avg_score": results["avg_score"],
        "front_review": results["front_review"],
        "back_review": results["back_review"],
        "side_review": results["side_review"],
        "main_review": results["main_review"]
    })


@app.route('/api/status/<order_id>')
def api_status(order_id):
    order = fetch_order(int(order_id))
    if order is None:
        return jsonify({"success": False, "error": f"Order {order_id} not found."}), 404
    return jsonify({"success": True, "order": order})


@app.route('/api/orders')
def api_orders():
    orders = fetch_all_orders()
    return jsonify({"success": True, "orders": orders})


if __name__ == "__main__":
    app.run(debug=True)
