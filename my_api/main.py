import os
import pymysql
from fastapi import FastAPI, HTTPException, Query
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

app = FastAPI()

class User(BaseModel):
    name: str
    email: str

def get_db():
    return pymysql.connect(
        host="127.0.0.1",
        port=3307,
        user=os.getenv("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", "root123"),
        database=os.getenv(
            "DB_NAME", "Final_project_304_499"
        ),
        cursorclass=pymysql.cursors.DictCursor,
    )


@app.get("/")
def home():
    return {"message": "FastAPI is running"}


@app.get("/products")
def get_products():
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM products")
            return cursor.fetchall()
    finally:
        conn.close()


@app.get("/products/{product_id}")
def get_product(product_id: int):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM products WHERE id = %s",
                (product_id,),
            )
            product = cursor.fetchone()

            if product is None:
                raise HTTPException(
                    status_code=404,
                    detail="Product not found",
                )

            return product
    finally:
        conn.close()


@app.get("/products/search")
def search_products(
    name: str = Query(..., min_length=1)
):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM products "
                "WHERE name LIKE %s",
                (f"%{name}%",),
            )
            return cursor.fetchall()
    finally:
        conn.close()


@app.post("/users")
def add_user(user: User):
    db = get_db()
    try:
        with db.cursor() as cursor:
            sql = "INSERT INTO users (name, email) VALUES (%s, %s)"
            cursor.execute(sql, (user.name, user.email))
        db.commit()
        return {"message": "บันทึกสำเร็จ"}
    finally:
        db.close()

# ดึงข้อมูลผู้ใช้ทั้งหมดกลับไปแสดง
@app.get("/users")
def get_users():
    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("SELECT * FROM users")
            return cursor.fetchall()
    finally:
        db.close()