<?php
require "db.php";

if ($_SERVER["REQUEST_METHOD"] === "GET") {
    $stmt = $pdo->query("SELECT * FROM categories");
    echo json_encode($stmt->fetchAll());
}

if ($_SERVER["REQUEST_METHOD"] === "POST") {
    $data = json_decode(file_get_contents("php://input"), true);

    $stmt = $pdo->prepare(
        "INSERT INTO categories (category_name) VALUES (?)"
    );
    $stmt->execute([$data["category_name"]]);

    echo json_encode(["message" => "เพิ่มหมวดหมู่สำเร็จ"]);
}
