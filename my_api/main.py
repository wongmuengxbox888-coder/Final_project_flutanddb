
import os
import re
import pymysql
import hashlib
import hmac
import secrets
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
    if value is None:
        return 0.0
    return float(value)


def _orders_meta(cursor):
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

            if user is None:
                username = email.split("@")[0]
                cursor.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
                    (username, email, hash_password(data.password)),
                )
                user_id = cursor.lastrowid
                conn.commit()
                return {"user_id": user_id, "username": username, "email": email}

            stored = user["password_hash"]
            if not stored:
                cursor.execute(
                    "UPDATE users SET password_hash = %s WHERE user_id = %s",
                    (hash_password(data.password), user["user_id"]),
                )
                conn.commit()
            elif not verify_password(data.password, stored):
                raise HTTPException(status_code=401, detail="อีเมลหรือรหัสผ่านไม่ถูกต้อง")

            return {
                "user_id": user["user_id"],
                "username": user["username"],
                "email": user["email"]
            }

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


# ---------- Products ----------
@app.get("/products")
def get_products():
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM products")
            return cursor.fetchall()
    finally:
        conn.close()


@app.get("/products/search")
def search_products(name: str = Query(..., min_length=1)):
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


# ---------- Orders ----------
@app.post("/orders")
def create_order(data: OrderRequest):
    if not data.items:
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

            for item in data.items:
                if item.product_id is None:
                    continue
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
# ADMIN ORDERS
# =========================================================
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
        raise HTTPException(status_code=500, detail=f"ดึงคำสั่งซื้อไม่สำเร็จ: {e}")
    finally:
        conn.close()


# ---------- รับออเดอร์และบันทึกลงตาราง accept ----------
@app.patch("/admin/orders/{order_id}/status")
def admin_accept_order(order_id: int):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            pk, status_col, _total_col, _names = _orders_meta(cursor)

            if status_col is None:
                raise HTTPException(
                    status_code=400,
                    detail="ตาราง orders ไม่มี column status"
                )

            _check_order_exists(cursor, pk, order_id)

            # อ่านสถานะปัจจุบัน ป้องกันการกดรับซ้ำ
            cursor.execute(
                f"SELECT `{status_col['Field']}` AS current_status "
                f"FROM orders WHERE `{pk}` = %s FOR UPDATE",
                (order_id,)
            )
            order_row = cursor.fetchone()
            current_status = str(
                (order_row or {}).get("current_status") or ""
            ).strip().lower()

            if current_status == "accepted":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "ออเดอร์นี้มีสถานะ Accepted อยู่แล้ว "
                        "ถ้าเป็นออเดอร์ที่รับก่อนเพิ่มระบบบันทึกตาราง accept "
                        "ให้เปลี่ยนสถานะกลับเป็น Pending ใน SQL แล้วกดรับใหม่"
                    )
                )

            # ตรวจสอบคอลัมน์ในตาราง accept
            cursor.execute("SHOW COLUMNS FROM `accept`")
            accept_columns = {
                col["Field"].lower(): col["Field"]
                for col in cursor.fetchall()
            }

            if (
                "accept_name" not in accept_columns
                or "accept_price" not in accept_columns
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "ตาราง accept ต้องมีคอลัมน์ accept_name "
                        "และ accept_price"
                    )
                )

            # ดึงชื่อสินค้าและราคาจาก order_items
            p_pk, p_name = _products_meta(cursor)
            cursor.execute(
                f"""
                SELECT
                    oi.product_id,
                    oi.quantity,
                    oi.price,
                    p.`{p_name}` AS product_name
                FROM order_items oi
                LEFT JOIN products p
                    ON p.`{p_pk}` = oi.product_id
                WHERE oi.order_id = %s
                """,
                (order_id,)
            )
            items = cursor.fetchall()

            if not items:
                raise HTTPException(
                    status_code=400,
                    detail="ออเดอร์นี้ไม่มีรายการสินค้าใน order_items"
                )

            # เพิ่มสินค้าแต่ละรายการลงตาราง accept
            for item in items:
                product_name = (
                    item.get("product_name")
                    or f"สินค้า #{item.get('product_id')}"
                )
                quantity = int(item.get("quantity") or 1)
                unit_price = Decimal(str(item.get("price") or 0))

                if quantity < 1 or unit_price < 0:
                    raise HTTPException(
                        status_code=400,
                        detail="จำนวนหรือราคาสินค้าในออเดอร์ไม่ถูกต้อง"
                    )

                line_total = unit_price * quantity

                cursor.execute(
                    f"""
                    INSERT INTO `accept`
                        (`{accept_columns['accept_name']}`,
                         `{accept_columns['accept_price']}`)
                    VALUES (%s, %s)
                    """,
                    (product_name, line_total)
                )

            # เปลี่ยนสถานะเป็น Accepted
            new_status = "Accepted"
            col_type = str(status_col["Type"])

            options = (
                re.findall(r"'((?:[^']|'')*)'", col_type)
                if col_type.lower().startswith("enum(") else []
            )

            if options:
                match = next(
                    (
                        option for option in options
                        if option.lower() == "accepted"
                    ),
                    None
                )

                if match is None:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "column status เป็น ENUM แต่ไม่มีค่า Accepted "
                            "กรุณาแก้ชนิด column status ให้รองรับ Accepted"
                        )
                    )

                new_status = match

            cursor.execute(
                f"UPDATE orders SET `{status_col['Field']}` = %s "
                f"WHERE `{pk}` = %s",
                (new_status, order_id)
            )

        conn.commit()

        return {
            "success": True,
            "message": "รับออเดอร์และบันทึกข้อมูลลงตาราง accept เรียบร้อยแล้ว",
            "order_id": order_id,
            "accepted_items": len(items)
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        print("ACCEPT ORDER ERROR:", repr(e))
        raise HTTPException(
            status_code=500,
            detail=f"รับออเดอร์ไม่สำเร็จ: {e}"
        )
    finally:
        conn.close()


# ---------- แก้ไขสินค้าในออเดอร์ ----------
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


# ---------- ลบออเดอร์ ----------
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
# PRODUCT MANAGEMENT
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


# ---------- ลบสินค้า ----------
@app.delete("/products/{product_id}")
def delete_product_by_id(product_id: int):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            p_pk, _ = _products_meta(cursor)
            cursor.execute(f"DELETE FROM products WHERE `{p_pk}` = %s", (product_id,))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="ไม่พบสินค้านี้ในคลัง")

        conn.commit()
        return {"success": True, "message": "ลบสินค้าเรียบร้อยแล้ว"}

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        print("DELETE PRODUCT ERROR:", e)
        raise HTTPException(status_code=500, detail=f"ลบสินค้าไม่สำเร็จ: {e}")
    finally:
        conn.close()


# ---------- สินค้าฝากขายที่รออนุมัติ ----------
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
