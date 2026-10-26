import os
import re
import pymysql
import hashlib
import hmac
import secrets
from datetime import datetime  # ใช้สร้างเลขคำสั่งซื้อ
from typing import List, Optional  # ใช้กำหนดชนิดข้อมูลของ /orders
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from decimal import Decimal

app = FastAPI()

# อนุญาตให้ Flutter Web และหน้า admin.html เรียก API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:61194",
        "http://127.0.0.1:61194",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ข้อมูลที่ Flutter ส่งมา
class User(BaseModel):
    username: str
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


# รองเท้า 1 รายการในคำสั่งซื้อ (ตรงกับตาราง order_items)
class OrderItemRequest(BaseModel):
    product_id: Optional[int] = None   # -> order_items.product_id
    name: Optional[str] = None         # ใช้หา product_id สำรอง ถ้าไม่ได้ส่ง id มา
    quantity: int = 1                  # -> order_items.quantity
    price: float                       # -> order_items.price (ราคาต่อคู่)


# คำสั่งซื้อทั้งใบที่ Flutter ส่งมาตอนกด "ยืนยันคำสั่งซื้อ"
class OrderRequest(BaseModel):
    user_id: Optional[int] = None      # ผู้ใช้ที่ล็อกอินอยู่ (ถ้ามี)
    total: float                       # ยอดชำระทั้งหมด (รวมค่าจัดส่ง)
    items: List[OrderItemRequest]


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


# ต้องวาง /products/search ไว้ "ก่อน" /products/{product_id}
# ไม่งั้นคำว่า "search" จะถูกมองเป็น product_id แล้วเกิด error 422
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


###บันทึกผู้ใช้ใหม่ (สมัครสมาชิก)
@app.post("/users")
def add_user(user: User):
    conn = get_db()

    try:
        with conn.cursor() as cursor:
            # ตรวจสอบก่อนว่าอีเมลนี้มีในระบบแล้วหรือยัง
            cursor.execute(
                "SELECT user_id FROM users WHERE email = %s",
                (user.email.strip(),),
            )

            if cursor.fetchone():
                raise HTTPException(
                    status_code=409,
                    detail="อีเมลนี้มีผู้ใช้แล้ว",
                )

            # บันทึกชื่อ อีเมล และรหัสผ่านที่ผ่านการ Hash แล้ว
            cursor.execute(
                """
                INSERT INTO users (username, email, password_hash)
                VALUES (%s, %s, %s)
                """,
                (
                    user.username,
                    user.email.strip(),
                    hash_password(user.password),
                ),
            )

            user_id = cursor.lastrowid

        conn.commit()

        return {
            "message": "สมัครสมาชิกสำเร็จ",
            "user": {
                "user_id": user_id,
                "username": user.username,
                "email": user.email.strip(),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        print("REGISTER ERROR:", e)
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






#####ส่วน ทดลองทำคู่กับ DB แล้วก้มีส่วนเก่าที่เป็นของ Flutter อยู่แล้ว
###ออเดอร์เพิ่ม แล้วก้ กดยืนยันคำสั่งซื้อ
@app.post("/orders")
def create_order(data: OrderRequest):
    if not data.items:
        raise HTTPException(status_code=400, detail="ตะกร้าว่าง")

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            # --- 1) สร้างแถวในตาราง orders ---
            cursor.execute("SHOW COLUMNS FROM orders")
            columns = cursor.fetchall()

            fields = []   # ชื่อ column
            marks = []    # %s หรือ ฟังก์ชัน SQL เช่น NOW()
            params = []   # ค่าที่ส่งเข้า %s

            def add(field, value=None, sql="%s"):
                fields.append(f"`{field}`")
                marks.append(sql)
                if sql == "%s":
                    params.append(value)

            for col in columns:
                field = col["Field"]
                low = field.lower()

                # ข้าม column ที่รันเลขเอง
                if "auto_increment" in (col["Extra"] or "").lower():
                    continue

                if low == "user_id":
                    add(field, data.user_id)
                elif low in (
                    "total", "total_price", "total_amount",
                    "grand_total", "amount",
                ):
                    add(field, data.total)
                elif low in ("status", "order_status"):
                    add(field, "Pending")
                elif low in ("shipping_fee", "shipping_cost"):
                    add(field, 100)
                # column NOT NULL ที่ไม่มี default -> เติมค่ากันพัง
                elif col["Null"] == "NO" and col["Default"] is None:
                    t = str(col["Type"]).lower()
                    if t.startswith("enum"):
                        add(field, t.split("'")[1])      # ค่าแรกของ enum
                    elif t.startswith(("datetime", "timestamp")):
                        add(field, sql="NOW()")
                    elif t.startswith("date"):
                        add(field, sql="CURDATE()")
                    elif any(x in t for x in ("int", "decimal", "float", "double")):
                        add(field, 0)
                    else:
                        add(field, "")

            if fields:
                cursor.execute(
                    f"INSERT INTO orders ({', '.join(fields)}) "
                    f"VALUES ({', '.join(marks)})",
                    tuple(params),
                )
            else:
                cursor.execute("INSERT INTO orders () VALUES ()")

            order_id = cursor.lastrowid

            # --- สร้างเลขคำสั่งซื้อให้เอง เช่น #RP-261025-025 ---
            # (ต้องเพิ่ม column order_number ในตาราง orders ก่อน ถ้ายังไม่มีจะข้ามส่วนนี้)
            order_number = f"#RP-{datetime.now():%y%m%d}-{order_id:03d}"
            if any(c["Field"].lower() == "order_number" for c in columns):
                pk = next(
                    (c["Field"] for c in columns if c["Key"] == "PRI"),
                    "order_id",
                )
                cursor.execute(
                    f"UPDATE orders SET `order_number` = %s WHERE `{pk}` = %s",
                    (order_number, order_id),
                )

            # --- 2) บันทึกรองเท้าลง order_items ---
            for item in data.items:
                if item.product_id is None:
                    continue  # ไม่มี product_id ก็ข้ามรายการนี้

                cursor.execute(
                    """
                    INSERT INTO order_items
                        (order_id, product_id, quantity, price)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (order_id, item.product_id, item.quantity, item.price),
                )

        conn.commit()

        return {
            "success": True,
            "message": "บันทึกคำสั่งซื้อเรียบร้อยแล้ว",
            "order_id": order_id,
            "order_number": order_number,
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        print("CREATE ORDER ERROR:", e)
        raise HTTPException(
            status_code=500,
            detail=f"บันทึกคำสั่งซื้อไม่สำเร็จ: {e}",
        )
    finally:
        conn.close()


# =========================================================
# ADMIN (ส่วนใหม่ แยกจากของเดิม) — ให้หน้า admin.html เรียกใช้
# ใช้ตาราง orders / order_items / products ชุดเดียวกับ Flutter
# แต่ใช้ path ขึ้นต้นด้วย /admin จึงไม่กระทบ POST /orders ของ Flutter
#   GET    /admin/orders                  ดึงออเดอร์ทั้งหมด (พร้อมรายการสินค้า)
#   PATCH  /admin/orders/{id}/status      รับออเดอร์ (status = Accepted)
#   PATCH  /admin/orders/{id}/items       แก้จำนวน/ราคาสินค้าในออเดอร์
#   DELETE /admin/orders/{id}             ลบออเดอร์
# =========================================================

class OrderItemUpdate(BaseModel):
    product_id: int
    quantity: int = Field(ge=1)
    price: float = Field(ge=0)


def _num(value) -> float:
    """แปลง Decimal/None เป็น float ให้ส่งเป็น JSON ได้"""
    if value is None:
        return 0.0
    return float(value) if isinstance(value, Decimal) else float(value)


def _orders_meta(cursor):
    """อ่านชื่อ column จริงของตาราง orders"""
    cursor.execute("SHOW COLUMNS FROM orders")
    columns = cursor.fetchall()
    names = {c["Field"].lower(): c for c in columns}

    pk = next((c["Field"] for c in columns if c["Key"] == "PRI"), "order_id")
    status_col = next(
        (names[k] for k in ("status", "order_status") if k in names), None
    )
    total_col = next(
        (names[k] for k in (
            "total", "total_price", "total_amount", "grand_total", "amount"
        ) if k in names),
        None,
    )
    return pk, status_col, total_col, names


def _check_order_exists(cursor, pk: str, order_id: int):
    cursor.execute(
        f"SELECT `{pk}` FROM orders WHERE `{pk}` = %s", (order_id,)
    )
    if cursor.fetchone() is None:
        raise HTTPException(status_code=404, detail="ไม่พบคำสั่งซื้อนี้")


def _products_meta(cursor):
    """หา primary key และ column ชื่อสินค้าจริงของตาราง products"""
    cursor.execute("SHOW COLUMNS FROM products")
    columns = cursor.fetchall()
    names = {c["Field"].lower(): c["Field"] for c in columns}

    pk = next((c["Field"] for c in columns if c["Key"] == "PRI"), None)
    if pk is None:
        pk = next(
            (names[k] for k in ("id", "product_id") if k in names),
            columns[0]["Field"],
        )

    name_col = next(
        (names[k] for k in ("name", "product_name", "title") if k in names),
        pk,  # ไม่เจอ column ชื่อ -> ใช้ pk แทน หน้า admin จะโชว์เป็นเลข
    )
    return pk, name_col


@app.get("/admin/orders")
def admin_get_orders():
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            pk, status_col, total_col, names = _orders_meta(cursor)

            cursor.execute(f"SELECT * FROM orders ORDER BY `{pk}` DESC")
            order_rows = cursor.fetchall()

            if not order_rows:
                return {"success": True, "orders": []}

            ids = [r[pk] for r in order_rows]
            marks = ", ".join(["%s"] * len(ids))

            # รายการสินค้าของทุกออเดอร์ (ชื่อสินค้าจากตาราง products)
            # แก้: อ่านชื่อ column จริงของ products แทนการเดาว่าเป็น id / name
            p_pk, p_name = _products_meta(cursor)
            cursor.execute(
                f"""
                SELECT oi.order_id, oi.product_id, oi.quantity, oi.price,
                       p.`{p_name}` AS product_name
                FROM order_items oi
                LEFT JOIN products p ON p.`{p_pk}` = oi.product_id
                WHERE oi.order_id IN ({marks})
                ORDER BY oi.order_item_id
                """,
                tuple(ids),
            )
            items_by_order = {}
            for r in cursor.fetchall():
                items_by_order.setdefault(r["order_id"], []).append({
                    "product_id": r["product_id"],
                    "product_name": r["product_name"],
                    "quantity": int(r["quantity"] or 1),
                    "price": _num(r["price"]),
                })

            # ชื่อผู้ใช้
            usernames = {}
            if "user_id" in names:
                uids = list({
                    r["user_id"] for r in order_rows
                    if r.get("user_id") is not None
                })
                if uids:
                    um = ", ".join(["%s"] * len(uids))
                    cursor.execute(
                        f"SELECT user_id, username FROM users "
                        f"WHERE user_id IN ({um})",
                        tuple(uids),
                    )
                    usernames = {
                        u["user_id"]: u["username"] for u in cursor.fetchall()
                    }

        orders = []
        for o in order_rows:
            oid = o[pk]
            items = items_by_order.get(oid, [])
            subtotal = sum(i["price"] * i["quantity"] for i in items)
            total = (
                _num(o[total_col["Field"]])
                if total_col and o.get(total_col["Field"]) is not None
                else subtotal + 100
            )
            orders.append({
                "order_id": oid,
                "order_number": o.get("order_number"),
                "user_id": o.get("user_id"),
                "username": usernames.get(o.get("user_id")),
                "status": (
                    o.get(status_col["Field"]) if status_col else None
                ) or "Pending",
                "total": total,
                "items": items,
            })

        return {"success": True, "orders": orders}

    except HTTPException:
        raise
    except Exception as e:
        print("GET ORDERS ERROR:", e)
        raise HTTPException(
            status_code=500, detail=f"ดึงคำสั่งซื้อไม่สำเร็จ: {e}"
        )
    finally:
        conn.close()


@app.patch("/admin/orders/{order_id}/status")
def admin_accept_order(order_id: int):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            pk, status_col, _total_col, _names = _orders_meta(cursor)

            if status_col is None:
                raise HTTPException(
                    status_code=400,
                    detail="ตาราง orders ไม่มี column status",
                )

            _check_order_exists(cursor, pk, order_id)

            # ถ้า status เป็น ENUM ต้องมีค่า 'Accepted' อยู่ในรายการ
            new_status = "Accepted"
            options = re.findall(
                r"'((?:[^']|'')*)'", str(status_col["Type"])
            ) if str(status_col["Type"]).lower().startswith("enum(") else []
            if options:
                match = next(
                    (o for o in options if o.lower() == "accepted"), None
                )
                if match is None:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "column status เป็น ENUM แต่ไม่มีค่า 'Accepted' "
                            "ให้รัน: ALTER TABLE orders MODIFY "
                            f"`{status_col['Field']}` VARCHAR(30) "
                            "NOT NULL DEFAULT 'Pending';"
                        ),
                    )
                new_status = match

            cursor.execute(
                f"UPDATE orders SET `{status_col['Field']}` = %s "
                f"WHERE `{pk}` = %s",
                (new_status, order_id),
            )

        conn.commit()
        return {"success": True, "message": "รับออเดอร์แล้ว"}

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        print("ACCEPT ORDER ERROR:", e)
        raise HTTPException(
            status_code=500, detail=f"รับออเดอร์ไม่สำเร็จ: {e}"
        )
    finally:
        conn.close()


@app.patch("/admin/orders/{order_id}/items")
def admin_update_order_item(order_id: int, data: OrderItemUpdate):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            pk, _status_col, total_col, _names = _orders_meta(cursor)
            _check_order_exists(cursor, pk, order_id)

            cursor.execute(
                """
                SELECT order_item_id FROM order_items
                WHERE order_id = %s AND product_id = %s
                """,
                (order_id, data.product_id),
            )
            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=404, detail="ไม่พบสินค้านี้ในออเดอร์"
                )

            cursor.execute(
                """
                UPDATE order_items SET quantity = %s, price = %s
                WHERE order_id = %s AND product_id = %s
                """,
                (data.quantity, data.price, order_id, data.product_id),
            )

            # คำนวณยอดรวมใหม่ (ราคาสินค้าทั้งหมด + ค่าจัดส่ง 100)
            if total_col is not None:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(quantity * price), 0) AS subtotal
                    FROM order_items WHERE order_id = %s
                    """,
                    (order_id,),
                )
                subtotal = _num(cursor.fetchone()["subtotal"])
                cursor.execute(
                    f"UPDATE orders SET `{total_col['Field']}` = %s "
                    f"WHERE `{pk}` = %s",
                    (subtotal + 100, order_id),
                )

        conn.commit()
        return {"success": True, "message": "แก้ไขออเดอร์แล้ว"}

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        print("UPDATE ORDER ITEM ERROR:", e)
        raise HTTPException(
            status_code=500, detail=f"แก้ไขออเดอร์ไม่สำเร็จ: {e}"
        )
    finally:
        conn.close()


@app.delete("/admin/orders/{order_id}")
def admin_delete_order(order_id: int):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            pk, _status_col, _total_col, _names = _orders_meta(cursor)
            _check_order_exists(cursor, pk, order_id)

            # ลบรายการสินค้าก่อน (กัน foreign key error) แล้วค่อยลบออเดอร์
            cursor.execute(
                "DELETE FROM order_items WHERE order_id = %s", (order_id,)
            )
            cursor.execute(
                f"DELETE FROM orders WHERE `{pk}` = %s", (order_id,)
            )

        conn.commit()
        return {"success": True, "message": "ลบออเดอร์แล้ว"}

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        print("DELETE ORDER ERROR:", e)
        raise HTTPException(
            status_code=500, detail=f"ลบออเดอร์ไม่สำเร็จ: {e}"
        )
    finally:
        conn.close()


from fastapi import HTTPException
from pydantic import BaseModel
from typing import Optional

class ProductInput(BaseModel):
    name: str
    price: float
    image_url: Optional[str] = None


@app.get("/admin/products")
def get_admin_products():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT * FROM products")
        products = cursor.fetchall()
        return products
    finally:
        cursor.close()
        conn.close()


@app.post("/admin/products")
def add_admin_product(product: ProductInput):
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO products (name, price, image_url)
            VALUES (%s, %s, %s)
            """,
            (product.name, product.price, product.image_url)
        )

        conn.commit()

        return {
            "message": "Product added successfully",
            "product_id": cursor.lastrowid
        }

    except Exception as error:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(error))

    finally:
        cursor.close()
        conn.close()


@app.delete("/admin/products/{product_id}")
def delete_admin_product(product_id: int):
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "DELETE FROM products WHERE id = %s",
            (product_id,)
        )

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Product not found")

        conn.commit()
        return {"message": "Product deleted successfully"}

    except HTTPException:
        conn.rollback()
        raise
    except Exception as error:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(error))
    finally:
        cursor.close()
        conn.close()
