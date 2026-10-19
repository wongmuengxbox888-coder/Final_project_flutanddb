<?php
require "db.php";

if ($_SERVER["REQUEST_METHOD"] === "GET") {
    $stmt = $pdo->query(
        "SELECT user_id, username, email FROM users"
    );
    echo json_encode($stmt->fetchAll());
}

if ($_SERVER["REQUEST_METHOD"] === "POST") {
    $data = json_decode(file_get_contents("php://input"), true);

    $hash = password_hash($data["password"], PASSWORD_DEFAULT);

    $stmt = $pdo->prepare(
        "INSERT INTO users (username, email, password_hash)
         VALUES (?, ?, ?)"
    );
    $stmt->execute([
        $data["username"],
        $data["email"],
        $hash
    ]);

    echo json_encode(["message" => "สมัครสมาชิกสำเร็จ"]);
}
