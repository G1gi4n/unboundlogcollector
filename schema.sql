CREATE TABLE IF NOT EXISTS accounts_clientip (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    ip_address VARCHAR(45) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_accounts_clientip_ip_address (ip_address)
);

CREATE TABLE IF NOT EXISTS dns_logs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    client_ip VARCHAR(45) NOT NULL,
    domain VARCHAR(255) NOT NULL,
    qtype VARCHAR(32) NOT NULL,
    rcode VARCHAR(32) NULL,
    latency_ms DOUBLE NULL,
    status ENUM('query', 'response') NOT NULL,
    timestamp DATETIME NOT NULL,
    PRIMARY KEY (id),
    KEY idx_dns_logs_timestamp (timestamp),
    KEY idx_dns_logs_domain (domain),
    KEY idx_dns_logs_client_ip (client_ip),
    KEY idx_dns_logs_status (status)
);
