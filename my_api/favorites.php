<?php
require "db.php";

if ($_SERVER["REQUEST_METHOD"] === "GET") {
    $stmt = $pdo->query("SELECT * FROM favorites");
    echo json_encode($stmt->fetchAll());
}

if ($_SERVER["REQUEST_METHOD"] === "POST") {
    $data = json_decode(file_get_contents("php://input"), true);

    $stmt = $pdo->prepare(
        "INSERT INTO favorites (user_id, product_id)
         VALUES (?, ?)"
    );
    $stmt->execute([
        $data["user_id"],
        $data["product_id"]
    ]);

    echo json_encode(["message" => "เพิ่มรายการโปรดสำเร็จ"]);
}
