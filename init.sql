CREATE TABLE IF NOT EXISTS tickets (
  id SERIAL PRIMARY KEY,
  event_name TEXT NOT NULL,
  stock INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
  id SERIAL PRIMARY KEY,
  ticket_id INT NOT NULL REFERENCES tickets(id),
  buyer TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

TRUNCATE orders RESTART IDENTITY;
TRUNCATE tickets RESTART IDENTITY;

-- Event stok 1 (sengaja)
INSERT INTO tickets (event_name, stock) VALUES ('Very Limited Concert', 1);
