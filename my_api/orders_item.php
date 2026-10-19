<?php
require "db.php";

if ($_SERVER["REQUEST_METHOD"] === "GET") {
    $stmt = $pdo->query("SELECT * FROM order_items");
    echo json_encode($stmt->fetchAll());
}

if ($_SERVER["REQUEST_METHOD"] === "POST") {
    $data = json_decode(file_get_contents("php://input"), true);

    $stmt = $pdo->prepare(
        "INSERT INTO order_items (order_id, product_id, quantity, price)
         VALUES (?, ?, ?, ?)"
    );
    $stmt->execute([
        $data["order_id"],
        $data["product_id"],
        $data["quantity"],
        $data["price"]
    ]);

    echo json_encode(["message" => "เพิ่มรายการสินค้าสำเร็จ"]);
}
