import os
import pymysql
import hashlib
import hmac
import secrets

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# อนุญาตให้ Flutter Web เรียก API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:49839",
        "http://127.0.0.1:49839",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ข้อมูลที่ Flutter ส่งมา
class User(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):   
    email: str                   
    password: str  


# ข้อมูลที่อยู่จัดส่งจาก Flutter
class AddressRequest(BaseModel):
    name_lastname: str
    phone: str
    address: str
    subdistrict: str
    amphoe: str
    province: str
    messenger_number: str


# เชื่อมต่อ MySQL
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

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 100_000
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 100_000
    ).hex()
    return hmac.compare_digest(check, digest)

@app.post("/login")
def login(data: LoginRequest):
    email = data.email.strip()
    if not email or not data.password:
        raise HTTPException(status_code=400, detail="กรอกอีเมลและรหัสผ่าน")

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT user_id, username, email, password_hash FROM users WHERE email = %s",
                (email,),
            )
            user = cursor.fetchone()

            # อีเมลใหม่ -> บันทึกลงตาราง users
            if user is None:
                username = email.split("@")[0]
                cursor.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
                    (username, email, hash_password(data.password)),
                )
                user_id = cursor.lastrowid
                conn.commit()
                return {"user_id": user_id, "username": username, "email": email}

            # อีเมลเดิม -> ตรวจรหัสผ่าน
            stored = user["password_hash"]
            if not stored:
                cursor.execute(
                    "UPDATE users SET password_hash = %s WHERE user_id = %s",
                    (hash_password(data.password), user["user_id"]),
                )
                conn.commit()
            elif not verify_password(data.password, stored):
                raise HTTPException(status_code=401, detail="อีเมลหรือรหัสผ่านไม่ถูกต้อง")

            return {"user_id": user["user_id"], "username": user["username"], "email": user["email"]}

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        print("LOGIN ERROR:", e)
        raise HTTPException(status_code=500, detail="บันทึกข้อมูลไม่สำเร็จ")
    finally:
        conn.close()

# หน้าแรก
@app.get("/")
def home():
    return {"message": "FastAPI is running"}


# products

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
                "SELECT * FROM products WHERE name LIKE %s",
                (f"%{name}%",),
            )
            return cursor.fetchall()
    finally:
        conn.close()


# =========================
# USERS
# =========================

# POST: บันทึกชื่อและอีเมลจาก Flutter
@app.post("/users")
def add_user(user: User):
    conn = get_db()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (username, email)
                VALUES (%s, %s)
                """,
                (user.username, user.email),
            )

            user_id = cursor.lastrowid

        conn.commit()

        return {
            "message": "บันทึกข้อมูลสำเร็จ",
            "user": {
                "user_id": user_id,
                "username": user.username,
                "email": user.email,
            },
        }

    except Exception:
        conn.rollback()
        raise HTTPException(
            status_code=500,
            detail="บันทึกข้อมูลไม่สำเร็จ",
        )

    finally:
        conn.close()


# GET: ดึงผู้ใช้ทั้งหมดเระ 
@app.get("/users")
def get_users():
    conn = get_db()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT user_id, username, email
                FROM users
                """
            )
            return cursor.fetchall()

    finally:
        conn.close()


# GET: ดึงผู้ใช้คนเดียวสำหรับหน้า Profile
@app.get("/users/{user_id}")
def get_user(user_id: int):
    conn = get_db()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT user_id, username, email
                FROM users
                WHERE user_id = %s
                """,
                (user_id,),
            )

            user = cursor.fetchone()

            if user is None:
                raise HTTPException(
                    status_code=404,
                    detail="User not found",
                )

            return {"user": user}

    finally:
        conn.close()


### address
@app.post("/addresses")
def save_address(data: AddressRequest):
    conn = get_db()

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO form
            (
                name_lastname,
                phone,
                address,
                subdistrict,
                amphoe,
                province,
                messenger_number
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                data.name_lastname,
                data.phone,
                data.address,
                data.subdistrict,
                data.amphoe,
                data.province,
                data.messenger_number,
            ),
        )

        address_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": "บันทึกข้อมูลเรียบร้อยแล้ว",
        "address_id": address_id,
    }


@app.get("/addresses")
def get_addresses():
    conn = get_db()

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                name_lastname,
                phone,
                address,
                subdistrict,
                amphoe,
                province,
                messenger_number AS zipcode
            FROM form
            """
        )

        addresses = cursor.fetchall()

    conn.close()

    return addresses