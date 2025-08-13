import os
import time
import random
from flask import Flask, jsonify, request, render_template, abort
import psycopg2
import psycopg2.extras
from datetime import timezone

# -------------------------------------------------
# Config
# -------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://ticket:ticketpass@localhost:5432/ticketdb"
)

def get_conn():
    return psycopg2.connect(DATABASE_URL)

app = Flask(__name__)


# -------------------------------------------------
# Bootstrap: ensure tables + seed ticket id=1 exists
# Dipanggil di awal setiap handler penting
# -------------------------------------------------
def ensure_seed(conn):
    with conn.cursor() as cur:
        cur.execute("""
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
        """)
        # seed kalau belum ada id=1
        cur.execute("SELECT 1 FROM tickets WHERE id=1")
        if cur.fetchone() is None:
            # ⬇️ penting: truncate keduanya dalam SATU statement
            cur.execute("TRUNCATE orders, tickets RESTART IDENTITY;")
            cur.execute(
                "INSERT INTO tickets (event_name, stock) VALUES (%s, %s)",
                ("Konser Coldplay Limited", 1)
            )
    conn.commit()

# -------------------------------------------------
# Routes
# -------------------------------------------------
@app.get("/")
def index():
    return render_template("index.html")


@app.get("/status")
def status():
    with get_conn() as conn:
        ensure_seed(conn)
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT id, event_name, stock FROM tickets WHERE id=1")
            t = cur.fetchone()
            if not t:
                # Defensive fallback meski ensure_seed seharusnya menjamin ada
                return jsonify({"error": "no ticket seeded yet"}), 503
            cur.execute("SELECT COUNT(*) FROM orders WHERE ticket_id=1")
            oc = cur.fetchone()[0]
            return jsonify({
                "ticket": {
                    "id": t["id"],
                    "event_name": t["event_name"],
                    "stock": t["stock"]
                },
                "orders_count": oc
            })


@app.get("/reset")
def reset():
    with get_conn() as conn:
        ensure_seed(conn)
        with conn.cursor() as cur:
            cur.execute("UPDATE tickets SET stock=1 WHERE id=1")
            cur.execute("DELETE FROM orders WHERE ticket_id=1")
        conn.commit()
        return jsonify({"ok": True, "message": "reset stock to 1 & delete all orders"})


# =================== VULNERABLE BUY ===================
# Anti-pattern: check-then-update tanpa transaksi/locking/guard
@app.post("/buy")
def buy_vuln():
    data = request.get_json(silent=True) or {}
    buyer = data.get("buyer", f"user-{random.randint(1000, 9999)}")

    # Tambah delay kecil untuk memperbesar window race
    try:
        jitter = float(request.args.get("jitter", "0.02"))
    except ValueError:
        jitter = 0.02

    with get_conn() as conn:
        ensure_seed(conn)
        # Tanpa transaksi (autocommit) biar makin rentan
        conn.autocommit = True
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # 1) Cek stok saat ini
            cur.execute("SELECT stock FROM tickets WHERE id=1")
            row = cur.fetchone()
            stock_seen = row["stock"] if row else 0

            # 2) Delay -> memberi kesempatan request lain melihat stok yang sama
            time.sleep(jitter)

            if stock_seen <= 0:
                return jsonify({
                    "status": False,
                    "message": f"Sold Out ({stock_seen} stock)",
                    "ticket_id": None
                }), 409

            # 3) Update stok tanpa guard (bisa jadi < 0)
            cur.execute("UPDATE tickets SET stock = stock - 1 WHERE id=1")

            tix_id = random.randint(10000000, 99999999)
            # 4) Catat order
            cur.execute(
                "INSERT INTO orders (id, ticket_id, buyer) VALUES (%s, 1, %s)",
                (tix_id, buyer,)
            )

            return jsonify({
                "status": True,
                "message": f"Thanks for order Bro/Sis {buyer}!",
                "ticket_id": f"TIX-{tix_id}"
            })


@app.get("/orders/TIX-<int:order_id>")
def order_detail(order_id: int):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT
                  o.id AS order_id,
                  o.buyer,
                  o.created_at,
                  t.event_name
                FROM orders o
                JOIN tickets t ON t.id = o.ticket_id
                WHERE o.id = %s
            """, (order_id,))
            row = cur.fetchone()

    if not row:
        # 404 sederhana (kamu bisa ganti ke template notfound jika mau)
        abort(404, description="Order tidak ditemukan")

    # Format waktu rapi (WIB friendly di sisi UI; di sini iso8601 saja)
    created_iso = row["created_at"].isoformat() if row["created_at"] else ""

    data = {
        "order_code": f"TIX-{row['order_id']}",
        "buyer": row["buyer"],
        "created_at_iso": created_iso,  # untuk <time datetime="...">
        "created_at_human": row["created_at"].strftime("%d %b %Y, %H:%M:%S") if row["created_at"] else "-",
        "event_name": row["event_name"],
    }
    return render_template("eticket.html", **data)


# Optional: health endpoint untuk container
@app.get("/_health")
def health():
    try:
        with get_conn() as conn:
            ensure_seed(conn)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "err", "error": str(e)}), 500


# Untuk local dev (tidak dipakai di Docker karena pakai gunicorn)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8032)
