CREATE DATABASE IF NOT EXISTS telegramdb;
USE telegramdb;

CREATE TABLE IF NOT EXISTS jams (
    id INT AUTO_INCREMENT PRIMARY KEY,
    poll_id VARCHAR(255) UNIQUE,
    jam_date DATETIME,
    drums VARCHAR(255),
    bass VARCHAR(255),
    `leads` VARCHAR(255),
    fx VARCHAR(255),
    chat_id BIGINT,
    message_id BIGINT,
    poll_data JSON
);
