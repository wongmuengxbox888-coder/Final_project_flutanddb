import os
import re
import pymysql
import hashlib
import hmac
import secrets
import traceback
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI()

# อนุญาตให้ Flutter Web และหน้า admin.html เรียก API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:56004",
        "http://127.0.0.1:56004",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Models ----------
class User(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class AddressRequest(BaseModel):
    name_lastname: str
    phone: str
    address: str
    subdistrict: str
    amphoe: str
    province: str
    messenger_number: str


class OrderItemRequest(BaseModel):
    product_id: Optional[int] = None
    name: Optional[str] = None
    quantity: int = 1
    price: float


class OrderRequest(BaseModel):
    user_id: Optional[int] = None
    total: float
    items: List[OrderItemRequest]


class OrderItemUpdate(BaseModel):
    product_id: int
    quantity: int = Field(ge=1)
    price: float = Field(ge=0)


class ProductCreateRequest(BaseModel):
    name: Optional[str] = None
    product_name: Optional[str] = None
    type: Optional[str] = "ทั่วไป"
    category: Optional[str] = None
    price: float
    Image_url: Optional[str] = None
    image_url: Optional[str] = None


class ProductUpdateRequest(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = Field(default=None, ge=0)


# ---------- DB / helpers ----------
def get_db():
    return pymysql.connect(
        host="127.0.0.1",
        port=3307,
        user=os.getenv("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", "root123"),
        database=os.getenv("DB_NAME", "Final_project_304_499"),
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


def _num(value) -> float:
    """แปลง Decimal/None เป็น float ให้ส่งเป็น JSON ได้"""
    if value is None:
        return 0.0
    return float(value)


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
        pk,
    )
    return pk, name_col


def _cascade_delete(cursor, table: str, where_sql: str, params: tuple, depth: int = 0):
    """
    ลบแถวใน `table` ตามเงื่อนไข where_sql โดยลบตารางลูกที่มี FK ชี้มาก่อน
    (ทำซ้ำเป็นชั้นๆ เช่น products -> order_items -> ตารางที่ชี้ไป order_items)
    """
    if depth > 5:
        return

    cursor.execute(
        """
        SELECT TABLE_NAME AS t, COLUMN_NAME AS c, REFERENCED_COLUMN_NAME AS rc
        FROM information_schema.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE()
          AND REFERENCED_TABLE_SCHEMA = DATABASE()
          AND REFERENCED_TABLE_NAME = %s
        """,
        (table,),
    )
    children = cursor.fetchall()

    for ch in children:
        if ch["t"] == table:  # FK ชี้หาตัวเอง ข้ามไป กัน loop
            continue
        sub_where = (
            f"`{ch['c']}` IN (SELECT `{ch['rc']}` FROM `{table}` WHERE {where_sql})"
        )
        _cascade_delete(cursor, ch["t"], sub_where, params, depth + 1)

    cursor.execute(f"DELETE FROM `{table}` WHERE {where_sql}", params)


# ---------- Auth ----------
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


@app.get("/")
def home():
    return {"message": "FastAPI is running"}


@app.get("/health")
def health():
    """ใช้เช็กว่าเซิร์ฟเวอร์รันโค้ดล่าสุดอยู่ และต่อฐานข้อมูลได้"""
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            p_pk, name_col = _products_meta(cursor)
        return {
            "ok": True,
            "version": "products-edit-delete-v2",
            "products_pk": p_pk,
            "products_name_col": name_col,
        }
    finally:
        conn.close()


# ---------- Products ----------
@app.get("/products")
def get_products():
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            p_pk, _ = _products_meta(cursor)
            cursor.execute("SELECT * FROM products")
            rows = cursor.fetchall()
            # แนบ primary key จริงไปด้วย ให้ปุ่มแก้ไข/ลบอ้างอิงแถวเดียวกับที่ฐานข้อมูลใช้
            for r in rows:
                r["_pk"] = r.get(p_pk)
            return rows
    finally:
        conn.close()


# ต้องวาง /products/search ไว้ "ก่อน" /products/{product_id}
@app.get("/products/search")
def search_products(name: str = Query(..., min_length=1)):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            _, name_col = _products_meta(cursor)
            cursor.execute(
                f"SELECT * FROM products WHERE `{name_col}` LIKE %s",
                (f"%{name}%",),
            )
            return cursor.fetchall()
    finally:
        conn.close()


@app.get("/products/{product_id}")
def get_product(product_id: str):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            p_pk, _ = _products_meta(cursor)
            cursor.execute(
                f"SELECT * FROM products WHERE `{p_pk}` = %s",
                (product_id,),
            )
            product = cursor.fetchone()
            if product is None:
                raise HTTPException(status_code=404, detail="Product not found")
            return product
    finally:
        conn.close()


# ---------- Users ----------
@app.post("/users")
def add_user(user: User):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT user_id FROM users WHERE email = %s",
                (user.email.strip(),),
            )
            if cursor.fetchone():
                raise HTTPException(status_code=409, detail="อีเมลนี้มีผู้ใช้แล้ว")

            cursor.execute(
                """
                INSERT INTO users (username, email, password_hash)
                VALUES (%s, %s, %s)
                """,
                (user.username, user.email.strip(), hash_password(user.password)),
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
        raise HTTPException(status_code=500, detail="บันทึกข้อมูลไม่สำเร็จ")
    finally:
        conn.close()


@app.get("/users")
def get_users():
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT user_id, username, email FROM users")
            return cursor.fetchall()
    finally:
        conn.close()


@app.get("/users/{user_id}")
def get_user(user_id: int):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT user_id, username, email FROM users WHERE user_id = %s",
                (user_id,),
            )
            user = cursor.fetchone()
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            return {"user": user}
    finally:
        conn.close()


# ---------- Address ----------
@app.post("/addresses")
def save_address(data: AddressRequest):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO form
                (name_lastname, phone, address, subdistrict, amphoe, province, messenger_number)
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
        return {
            "success": True,
            "message": "บันทึกข้อมูลเรียบร้อยแล้ว",
            "address_id": address_id,
        }
    finally:
        conn.close()


@app.get("/addresses")
def get_addresses():
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT name_lastname, phone, address, subdistrict, amphoe,
                       province, messenger_number AS zipcode
                FROM form
                """
            )
            return cursor.fetchall()
    finally:
        conn.close()


# ---------- Orders (Flutter กดยืนยันคำสั่งซื้อ) ----------
@app.post("/orders")
def create_order(data: OrderRequest):
    valid_items = [
        i for i in data.items
        if i.product_id is not None and i.quantity >= 1 and i.price > 0
    ]
    if not valid_items:
        raise HTTPException(status_code=400, detail="ตะกร้าว่าง")

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM orders")
            columns = cursor.fetchall()

            fields = []
            marks = []
            params = []

            def add(field, value=None, sql="%s"):
                fields.append(f"`{field}`")
                marks.append(sql)
                if sql == "%s":
                    params.append(value)

            for col in columns:
                field = col["Field"]
                low = field.lower()

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
                elif col["Null"] == "NO" and col["Default"] is None:
                    t = str(col["Type"]).lower()
                    if t.startswith("enum"):
                        add(field, t.split("'")[1])
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

            # เลขคำสั่งซื้อ เช่น #RP-261025-025 (ต้องมี column order_number)
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

            for item in valid_items:
                cursor.execute(
                    """
                    INSERT INTO order_items (order_id, product_id, quantity, price)
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
            status_code=500, detail=f"บันทึกคำสั่งซื้อไม่สำเร็จ: {e}"
        )
    finally:
        conn.close()


# =========================================================
# ADMIN ORDERS — หน้า Accept ใน dashboard.html
#   GET    /admin/orders                  ดึงออเดอร์ทั้งหมด (พร้อมรายการสินค้า)
#   PATCH  /admin/orders/{id}/status      รับออเดอร์ (status = Accepted)
#   PATCH  /admin/orders/{id}/items       แก้จำนวน/ราคาสินค้าในออเดอร์
#   DELETE /admin/orders/{id}             ลบออเดอร์
# =========================================================
@app.get("/admin/orders")
def admin_get_orders():
    """ดึงเฉพาะตาราง orders (ออเดอร์ที่ลูกค้ากดยืนยันจากตะกร้า) ไม่ยุ่งกับ order_items"""
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            pk, status_col, total_col, names = _orders_meta(cursor)

            cursor.execute(f"SELECT * FROM orders ORDER BY `{pk}` DESC")
            order_rows = cursor.fetchall()

            usernames = {}
            if "user_id" in names:
                uids = list({
                    r["user_id"] for r in order_rows
                    if r.get("user_id") is not None
                })
                if uids:
                    um = ", ".join(["%s"] * len(uids))
                    cursor.execute(
                        f"SELECT user_id, username FROM users WHERE user_id IN ({um})",
                        tuple(uids),
                    )
                    usernames = {
                        u["user_id"]: u["username"] for u in cursor.fetchall()
                    }

        orders = []
        for o in order_rows:
            orders.append({
                "order_id": o[pk],
                "order_number": o.get("order_number"),
                "user_id": o.get("user_id"),
                "username": usernames.get(o.get("user_id")),
                "status": (
                    o.get(status_col["Field"]) if status_col else None
                ) or "Pending",
                "total": _num(o.get(total_col["Field"])) if total_col else 0,
            })

        return {"success": True, "orders": orders}

    except Exception as e:
        print("GET ORDERS ERROR:", e)
        raise HTTPException(status_code=500, detail=f"ดึงคำสั่งซื้อไม่สำเร็จ: {e}")
    finally:
        conn.close()


# ---------- กดรับออเดอร์ -> โยนข้อมูลจากตาราง orders เข้าตาราง accept ----------
@app.patch("/admin/orders/{order_id}/status")
def admin_accept_order(order_id: int):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            pk, status_col, total_col, _names = _orders_meta(cursor)

            if status_col is None:
                raise HTTPException(status_code=400, detail="ตาราง orders ไม่มี column status")
            if total_col is None:
                raise HTTPException(status_code=400, detail="ตาราง orders ไม่มี column ราคารวม (total)")

            cursor.execute(
                f"SELECT * FROM orders WHERE `{pk}` = %s FOR UPDATE", (order_id,)
            )
            order = cursor.fetchone()
            if order is None:
                raise HTTPException(status_code=404, detail="ไม่พบคำสั่งซื้อนี้")

            current = str(order.get(status_col["Field"]) or "").strip().lower()
            if current == "accepted":
                raise HTTPException(status_code=409, detail="ออเดอร์นี้ถูกรับไปแล้ว")

            # --- ตาราง accept ---
            cursor.execute("SHOW COLUMNS FROM `accept`")
            acc = {c["Field"].lower(): c for c in cursor.fetchall()}
            if "accept_name" not in acc or "accept_price" not in acc:
                raise HTTPException(
                    status_code=400,
                    detail="ตาราง accept ต้องมีคอลัมน์ accept_name และ accept_price",
                )

            if order.get(total_col["Field"]) is None:
                raise HTTPException(status_code=400, detail="ออเดอร์นี้ไม่มีราคารวม")

            label = order.get("order_number") or f"Order #{order_id}"
            if order.get("user_id") is not None:
                cursor.execute(
                    "SELECT username FROM users WHERE user_id = %s", (order["user_id"],)
                )
                u = cursor.fetchone()
                if u and u["username"]:
                    label = f"{label} - {u['username']}"
            label = label[:50]
            price = int(round(_num(order[total_col["Field"]])))

            fields = [f"`{acc['accept_name']['Field']}`", f"`{acc['accept_price']['Field']}`"]
            marks = ["%s", "%s"]
            params = [label, price]

            # accept_id ไม่ได้เป็น AUTO_INCREMENT -> ใส่เลขออเดอร์ให้เอง (ไม่งั้น insert ไม่ผ่าน)
            has_id = False
            if "accept_id" in acc:
                if "auto_increment" not in (acc["accept_id"]["Extra"] or "").lower():
                    fields.insert(0, f"`{acc['accept_id']['Field']}`")
                    marks.insert(0, "%s")
                    params.insert(0, order_id)
                    has_id = True

            sql = f"INSERT INTO `accept` ({', '.join(fields)}) VALUES ({', '.join(marks)})"
            if has_id:
                sql += (
                    f" ON DUPLICATE KEY UPDATE "
                    f"`{acc['accept_name']['Field']}` = VALUES(`{acc['accept_name']['Field']}`), "
                    f"`{acc['accept_price']['Field']}` = VALUES(`{acc['accept_price']['Field']}`)"
                )
            cursor.execute(sql, tuple(params))

            # --- เปลี่ยนสถานะออเดอร์เป็น Accepted ---
            new_status = "Accepted"
            col_type = str(status_col["Type"])
            options = (
                re.findall(r"'((?:[^']|'')*)'", col_type)
                if col_type.lower().startswith("enum(") else []
            )
            if options:
                match = next((o for o in options if o.lower() == "accepted"), None)
                if match is None:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "column status เป็น ENUM แต่ไม่มีค่า Accepted ให้รัน: "
                            f"ALTER TABLE orders MODIFY `{status_col['Field']}` "
                            "VARCHAR(30) NOT NULL DEFAULT 'Pending';"
                        ),
                    )
                new_status = match

            cursor.execute(
                f"UPDATE orders SET `{status_col['Field']}` = %s WHERE `{pk}` = %s",
                (new_status, order_id),
            )

        conn.commit()
        return {
            "success": True,
            "message": "รับออเดอร์และบันทึกลงตาราง accept แล้ว",
            "order_id": order_id,
            "accept_name": label,
            "accept_price": price,
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        print("ACCEPT ORDER ERROR:", repr(e))
        raise HTTPException(status_code=500, detail=f"รับออเดอร์ไม่สำเร็จ: {e}")
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
                "SELECT order_item_id FROM order_items WHERE order_id = %s AND product_id = %s",
                (order_id, data.product_id),
            )
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="ไม่พบสินค้านี้ในออเดอร์")

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
                    f"UPDATE orders SET `{total_col['Field']}` = %s WHERE `{pk}` = %s",
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
        raise HTTPException(status_code=500, detail=f"แก้ไขออเดอร์ไม่สำเร็จ: {e}")
    finally:
        conn.close()


@app.delete("/admin/orders/{order_id}")
def admin_delete_order(order_id: int):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            pk, _status_col, _total_col, _names = _orders_meta(cursor)
            _check_order_exists(cursor, pk, order_id)

            cursor.execute("DELETE FROM order_items WHERE order_id = %s", (order_id,))
            cursor.execute(f"DELETE FROM orders WHERE `{pk}` = %s", (order_id,))

        conn.commit()
        return {"success": True, "message": "ลบออเดอร์แล้ว"}

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        print("DELETE ORDER ERROR:", e)
        raise HTTPException(status_code=500, detail=f"ลบออเดอร์ไม่สำเร็จ: {e}")
    finally:
        conn.close()


# =========================================================
# PRODUCT MANAGEMENT (หน้า Product / Add Product ใน dashboard)
# =========================================================
@app.post("/products")
def create_product(product: ProductCreateRequest):
    title = product.name or product.product_name
    if not title:
        raise HTTPException(status_code=400, detail="กรุณาระบุชื่อสินค้า")

    cat = product.category or product.type or "ทั่วไป"
    img = product.Image_url or product.image_url or ""

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM products")
            cols = [c["Field"] for c in cursor.fetchall()]

            name_col = "name" if "name" in cols else "product_name"
            price_col = "price" if "price" in cols else "product_price"
            cat_col = "category" if "category" in cols else ("type" if "type" in cols else None)
            img_col = "Image_url" if "Image_url" in cols else ("image_url" if "image_url" in cols else None)

            fields = [f"`{name_col}`", f"`{price_col}`"]
            marks = ["%s", "%s"]
            params = [title, product.price]

            if cat_col:
                fields.append(f"`{cat_col}`")
                marks.append("%s")
                params.append(cat)

            if img_col:
                fields.append(f"`{img_col}`")
                marks.append("%s")
                params.append(img)

            cursor.execute(
                f"INSERT INTO products ({', '.join(fields)}) VALUES ({', '.join(marks)})",
                tuple(params),
            )
            new_id = cursor.lastrowid

        conn.commit()
        return {"success": True, "message": "เพิ่มสินค้าเรียบร้อยแล้ว", "id": new_id}
    except Exception as e:
        conn.rollback()
        print("ADD PRODUCT ERROR:", e)
        raise HTTPException(status_code=500, detail=f"ไม่สามารถเพิ่มสินค้าได้: {e}")
    finally:
        conn.close()


# ---------- แก้ไขชื่อ/ราคาสินค้า ----------
# product_id เป็น str (ไม่ใช่ int) เพื่อไม่ให้ติด 422 ถ้า primary key ไม่ใช่ตัวเลข
# MySQL จะแปลง '12' เป็น 12 เองตอนเทียบกับ column ตัวเลข
@app.patch("/products/{product_id}")
def update_product(product_id: str, data: ProductUpdateRequest):
    if data.name is None and data.price is None:
        raise HTTPException(status_code=400, detail="ไม่มีข้อมูลที่จะแก้ไข")
    if data.name is not None and not data.name.strip():
        raise HTTPException(status_code=400, detail="ชื่อสินค้าห้ามว่าง")

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            p_pk, name_col = _products_meta(cursor)
            cursor.execute("SHOW COLUMNS FROM products")
            cols = {c["Field"].lower(): c["Field"] for c in cursor.fetchall()}
            price_col = (
                cols.get("price") or cols.get("product_price")
                or next((c for l, c in cols.items() if "price" in l), None)
            )
            name_col = (
                next((c for l, c in cols.items() if l in ("name", "product_name", "title")), None)
                or next((c for l, c in cols.items() if "name" in l or "title" in l), name_col)
            )

            cursor.execute(
                f"SELECT `{p_pk}` FROM products WHERE `{p_pk}` = %s", (product_id,)
            )
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="ไม่พบสินค้านี้ในคลัง")

            sets, params = [], []
            if data.name is not None:
                sets.append(f"`{name_col}` = %s")
                params.append(data.name.strip())
            if data.price is not None:
                if price_col is None:
                    raise HTTPException(status_code=400, detail="ตาราง products ไม่มี column ราคา")
                sets.append(f"`{price_col}` = %s")
                params.append(data.price)

            params.append(product_id)
            cursor.execute(
                f"UPDATE products SET {', '.join(sets)} WHERE `{p_pk}` = %s",
                tuple(params),
            )

        conn.commit()
        return {"success": True, "message": "แก้ไขสินค้าเรียบร้อยแล้ว"}

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        traceback.print_exc()  # ดู error เต็มๆ ใน terminal
        raise HTTPException(status_code=500, detail=f"แก้ไขสินค้าไม่สำเร็จ: {e}")
    finally:
        conn.close()


# ---------- ลบสินค้า ----------
@app.delete("/products/{product_id}")
def delete_product_by_id(product_id: str):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            p_pk, _ = _products_meta(cursor)

            cursor.execute(
                f"SELECT `{p_pk}` FROM products WHERE `{p_pk}` = %s", (product_id,)
            )
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="ไม่พบสินค้านี้ในคลัง")

            # ลบตารางลูกที่ชี้มาที่ products (และลูกของลูก) ก่อน แล้วค่อยลบสินค้า
            _cascade_delete(cursor, "products", f"`{p_pk}` = %s", (product_id,))

        conn.commit()
        return {"success": True, "message": "ลบสินค้าเรียบร้อยแล้ว"}

    except HTTPException:
        conn.rollback()
        raise
    except pymysql.err.IntegrityError as e:
        conn.rollback()
        traceback.print_exc()
        raise HTTPException(
            status_code=409,
            detail=f"ลบไม่ได้ เพราะสินค้านี้ถูกอ้างอิงในตารางอื่น: {e}",
        )
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"ลบสินค้าไม่สำเร็จ: {e}")
    finally:
        conn.close()


# ---------- สินค้าฝากขายที่รออนุมัติ (ของเดิม เก็บไว้) ----------
@app.get("/pending-products")
def get_pending_products():
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'pending_products'")
            if not cursor.fetchone():
                return []
            cursor.execute(
                "SELECT * FROM pending_products WHERE status = 'pending' ORDER BY id DESC"
            )
            return cursor.fetchall()
    except Exception as e:
        print("GET PENDING PRODUCTS ERROR:", e)
        return []
    finally:
        conn.close()


@app.post("/products/approve/{product_id}")
def approve_pending_product(product_id: int):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'pending_products'")
            if not cursor.fetchone():
                return {"success": True, "message": "อนุมัติสินค้าเรียบร้อย"}
            cursor.execute(
                "UPDATE pending_products SET status = 'approved' WHERE id = %s",
                (product_id,),
            )
        conn.commit()
        return {"success": True, "message": "อนุมัติสินค้าเรียบร้อยแล้ว"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"อนุมัติสินค้าไม่สำเร็จ: {e}")
    finally:
        conn.close()


@app.post("/products/reject/{product_id}")
def reject_pending_product(product_id: int):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'pending_products'")
            if not cursor.fetchone():
                return {"success": True, "message": "ปฏิเสธสินค้าเรียบร้อย"}
            cursor.execute(
                "UPDATE pending_products SET status = 'rejected' WHERE id = %s",
                (product_id,),
            )
        conn.commit()
        return {"success": True, "message": "ปฏิเสธสินค้าเรียบร้อยแล้ว"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"ปฏิเสธสินค้าไม่สำเร็จ: {e}")
    finally:
        conn.close()