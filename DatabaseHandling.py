import sqlite3
def create_database():
    conn = sqlite3.connect('request.db')
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS Orders (Order_ID,Similarity_Score,Customer_Review , VLM_Review , Status, Primary key(Order_ID))""")
    conn.commit()
    return conn
def generate_order_id():
    conn=create_database()
    cursor=conn.cursor()
    results=cursor.execute("""Select MAX(Order_ID) from Orders""").fetchone()
    if results[0] is None:
        return 1
    else:
        return results[0]+1
def add_similarity_data(order_id,similarity,status):
    conn=create_database()
    cursor=conn.cursor()
    results=cursor.execute("""SELECT * FROM ORDERS WHERE ORDER_ID=?""",(order_id)).fetchone()
    if results[0] is not None:
        return
    cursor.execute("""INSERT INTO Orders(Order_ID, Similarity_Score, Status) values(?,?,?)""",(order_id,similarity,status)) 
    conn.commit()
    return
def fetch_status(order_id):
    conn=create_database()
    cursor=conn.cursor()
    results=cursor.execute(""" Select Status from Orders where Order_ID==order_id """).fetchone()
    return results[0]
