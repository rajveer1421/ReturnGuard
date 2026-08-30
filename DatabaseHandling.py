import sqlite3

def create_database():
    conn = sqlite3.connect('request.db')
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS Orders (
        Order_ID INTEGER PRIMARY KEY,
        Similarity_Score REAL,
        front_score REAL,
        back_score REAL,
        side_score REAL,
        avg_score REAL,
        front_review TEXT,
        back_review TEXT,
        side_review TEXT,
        main_review TEXT,
        Status TEXT
    )""")
    conn.commit()
    return conn

def generate_order_id():
    conn = create_database()
    cursor = conn.cursor()
    results = cursor.execute("""SELECT MAX(Order_ID) FROM Orders""").fetchone()
    conn.close()
    if results[0] is None:
        return 1
    else:
        return results[0] + 1

def add_similarity_data(order_id, similarity, status):
    conn = create_database()
    cursor = conn.cursor()
    results = cursor.execute("""SELECT * FROM Orders WHERE Order_ID=?""", (order_id,)).fetchone()
    if results is not None:
        return
    cursor.execute("""INSERT INTO Orders(Order_ID, Similarity_Score, Status) VALUES(?,?,?)""", (order_id, similarity, status))
    conn.commit()
    conn.close()
    return

def fetch_status(order_id):
    conn = create_database()
    cursor = conn.cursor()
    results = cursor.execute("""SELECT Status FROM Orders WHERE Order_ID=?""", (order_id,)).fetchone()
    conn.close()
    if results is None:
        return None
    return results[0]

def add_review_data(order_id, front_score, back_score, side_score, avg_score, front_review, back_review, side_review, main_review, status):
    conn = create_database()
    cursor = conn.cursor()
    cursor.execute("""UPDATE Orders SET front_score=?, back_score=?, side_score=?, avg_score=?, front_review=?, back_review=?, side_review=?, main_review=?, Status=? WHERE Order_ID=?""",
                   (front_score, back_score, side_score, avg_score, front_review, back_review, side_review, main_review, status, order_id))
    conn.commit()
    conn.close()
    return

def fetch_order(order_id):
    conn = create_database()
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    result = cursor.execute("""SELECT * FROM Orders WHERE Order_ID=?""", (order_id,)).fetchone()
    conn.close()
    if result is None:
        return None
    return dict(result)

def fetch_all_orders():
    conn = create_database()
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    results = cursor.execute("""SELECT Order_ID, Similarity_Score, avg_score, Status FROM Orders ORDER BY Order_ID DESC LIMIT 50""").fetchall()
    conn.close()
    return [dict(row) for row in results]