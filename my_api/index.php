<?php
header("Content-Type: application/json; charset=utf-8");
header("Access-Control-Allow-Origin: *");
header("Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS");
header("Access-Control-Allow-Headers: Content-Type, Authorization");

echo json_encode([
    "status" => "ok",
    "message" => "Final Project API is running",
    "endpoints" => [
        "GET /products.php"    => "Get all products",
        "GET /categories.php"  => "Get all categories",
        "GET /users.php"       => "Get all users",
        "GET /orders.php"      => "Get all orders",
        "GET /orders_item.php" => "Get all order items",
        "GET /favorites.php"   => "Get all favorites",
    ]
], JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
