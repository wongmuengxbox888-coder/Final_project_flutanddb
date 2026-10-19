<?php
require_once "db.php";

try {
    $stmt = $pdo->query("SELECT * FROM products");

    echo json_encode(
        $stmt->fetchAll(),
        JSON_UNESCAPED_UNICODE
    );

} catch (PDOException $e) {
    http_response_code(500);

    echo json_encode([
        "error" => "Failed to fetch products"
    ], JSON_UNESCAPED_UNICODE);
}
