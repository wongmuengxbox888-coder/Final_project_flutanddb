# final_flutter_project

A Shoes Store 304 499.

## Getting Started

This project is a starting point for a Flutter application.

A few resources to get you started if this is your first Flutter project:

- [Learn Flutter](https://docs.flutter.dev/get-started/learn-flutter)
- [Write your first Flutter app](https://docs.flutter.dev/get-started/codelab)
- [Flutter learning resources](https://docs.flutter.dev/reference/learning-resources)

For help getting started with Flutter development, view the
[online documentation](https://docs.flutter.dev/), which offers tutorials,
samples, guidance on mobile development, and a full API reference.

# 📱 Final Project - E-Commerce App & API

**GitHub Repository:** https://github.com/wongmuengxbox888-coder/Final_project_flutanddb.git

เอกสารประกอบการจัดทำโปรเจกต์รายวิชา อธิบายโครงสร้างและการติดตั้งเพื่อเริ่มใช้งานระบบทั้งหมด ทั้งฝั่ง **Backend API (FastAPI + Docker)** และ **Frontend App (Flutter)**

---

## 🛠️ เทคโนโลยีที่ใช้ (Tech Stack)

* **Backend:** Python 3.12, FastAPI, PyMySQL, Uvicorn, Docker & Docker Compose
* **Database:** MySQL Server (Database Name: `Final_project_304_499`)
* **Frontend:** Flutter (Dart SDK `^3.12.2`), Package `http` (^1.6.0)

---

## ⚙️ ส่วนที่ 1: การติดตั้งและรัน Backend (FastAPI Server)

ระบบหลังบ้านใช้ **FastAPI** ร่วมกับ **PyMySQL** ในการรับส่งข้อมูลผ่าน RESTful API โดยสามารถเลือกวิธีการรันได้ 2 รูปแบบดังนี้:

### วิธีที่ 1: รันด้วย Docker Compose (แนะนำ) 🐳

1. **ตรวจสอบความพร้อมของ Docker:**
   * ติดตั้งและเปิดใช้งาน **Docker Desktop**
   * ตรวจสอบว่ามี Docker Network ชื่อ `mysql-db_default` สอดคล้องตามไฟล์ `compose.yaml`

2. **เตรียมไฟล์ Environment:**
   * ตรวจสอบไฟล์ `.env` หรือ `edit.env` โดยกำหนดรหัสผ่านฐานข้อมูลดังนี้:
     ```env
     DB_PASSWORD=root123
     ```

3. **สั่งรันบริการ:**
   เปิด Terminal ในโฟลเดอร์หลักที่มีไฟล์ `compose.yaml` แล้วใช้คำสั่ง:
   ```bash
   docker compose up -d --build
   ```

> 📌 **หมายเหตุ:** Container จะ Build ภาพจาก `Dockerfile` และ Map Port จากภายใน `80` มายัง Port `8000` ของเครื่อง Host
> * **API Service URL:** `http://localhost:8000`
> * **Swagger UI Documentation:** `http://localhost:8000/docs`

---

### วิธีที่ 2: รันแบบ Manual (ไม่ใช้ Docker) 💻

1. **ตั้งค่าฐานข้อมูล MySQL:**
   * สร้าง Database ชื่อ `Final_project_304_499`
   * ตรวจสอบความถูกต้องของ Username (`root`) และ Password (`root123`)

2. **ติดตั้ง Dependencies และสั่งรัน API Server:**
   เปิด Terminal เข้าไปยังโฟลเดอร์ `my_api` แล้วรันคำสั่ง:
   ```bash
   # ติดตั้ง Packages ที่จำเป็น
   pip install fastapi "uvicorn[standard]" pymysql pydantic

   # สั่งรัน Uvicorn บน Port 8000
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

---

## 📱 ส่วนที่ 2: การติดตั้งและรัน Frontend (Flutter App)

1. **เปิดโครงการใน Flutter Environment:**
   เปิดโฟลเดอร์ `Final_Flutter` (โปรเจกต์ `final_flutter_project`) บน VS Code หรือ Android Studio

2. **ติดตั้ง Packages:**
   เปิด Terminal ในโฟลเดอร์โปรเจกต์ Flutter แล้วสั่งรัน:
   ```bash
   flutter pub get
   ```

3. **สั่งรันแอปพลิเคชัน:**
   ```bash
   flutter run
   ```

---

## 🌐 การกำหนด Base URL เชื่อมต่อ API ใน Flutter

เนื่องจากระบบใช้ Base URL คือ **`http://127.0.0.1:8000`** การตั้งค่า URL ภายในโค้ด Flutter (`http` package) ควรพิจารณาตามอุปกรณ์ที่ใช้รันดังนี้:

* **รันบน Web Browser (Chrome) / Desktop App:**
  ```dart
  static const String baseUrl = '[http://127.0.0.1:8000](http://127.0.0.1:8000)';
