<?php
require "db.php";

if ($_SERVER["REQUEST_METHOD"] === "GET") {
    $stmt = $pdo->query("SELECT * FROM orders");
    echo json_encode($stmt->fetchAll());
}

if ($_SERVER["REQUEST_METHOD"] === "POST") {
    $data = json_decode(file_get_contents("php://input"), true);

    $stmt = $pdo->prepare(
        "INSERT INTO orders (user_id, total_price, status)
         VALUES (?, ?, 'pending')"
    );
    $stmt->execute([
        $data["user_id"],
        $data["total_price"]
    ]);

    echo json_encode([
        "message" => "สร้างคำสั่งซื้อสำเร็จ",
        "order_id" => $pdo->lastInsertId()
    ]);
}
