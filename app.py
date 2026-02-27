from __future__ import annotations

import datetime as dt
import os
import sqlite3
import uuid
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PDF_DIR = DATA_DIR / "pdfs"
DB_PATH = DATA_DIR / "books.db"
ALLOWED_EXTENSIONS = {"pdf"}


def create_app() -> Flask:
    app = Flask(__name__)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    init_db()

    @app.route("/")
    def index():
        books = query_all(
            """
            SELECT id, title, filename, total_pages, last_page, created_at
            FROM books
            ORDER BY created_at DESC
            """
        )
        return render_template("library.html", books=books)

    @app.route("/upload", methods=["POST"])
    def upload():
        if "pdf" not in request.files:
            return jsonify({"error": "Arquivo nao enviado."}), 400

        file = request.files["pdf"]
        if file.filename == "":
            return jsonify({"error": "Nome do arquivo invalido."}), 400

        if not allowed_file(file.filename):
            return jsonify({"error": "Somente PDF e permitido."}), 400

        original_name = secure_filename(file.filename)
        unique_name = f"{uuid.uuid4().hex}_{original_name}"
        target = PDF_DIR / unique_name
        file.save(target)

        title = Path(original_name).stem
        created_at = dt.datetime.utcnow().isoformat(timespec="seconds")

        execute(
            """
            INSERT INTO books (title, filename, total_pages, last_page, created_at)
            VALUES (?, ?, 0, 1, ?)
            """,
            (title, unique_name, created_at),
        )
        return redirect(url_for("index"))

    @app.route("/book/<int:book_id>")
    def reader(book_id: int):
        book = query_one(
            """
            SELECT id, title, filename, total_pages, last_page
            FROM books
            WHERE id = ?
            """,
            (book_id,),
        )
        if not book:
            return "Livro nao encontrado", 404

        bookmarks = query_all(
            """
            SELECT page
            FROM bookmarks
            WHERE book_id = ?
            ORDER BY page ASC
            """,
            (book_id,),
        )
        highlights = query_all(
            """
            SELECT id, page, text, color, created_at
            FROM highlights
            WHERE book_id = ?
            ORDER BY created_at DESC
            """,
            (book_id,),
        )
        return render_template(
            "reader.html",
            book=book,
            bookmarks=[row["page"] for row in bookmarks],
            highlights=highlights,
        )

    @app.route("/api/book/<int:book_id>", methods=["DELETE"])
    def delete_book(book_id: int):
        book = query_one(
            """
            SELECT id, filename
            FROM books
            WHERE id = ?
            """,
            (book_id,),
        )
        if not book:
            return jsonify({"error": "Livro nao encontrado"}), 404

        execute("DELETE FROM books WHERE id = ?", (book_id,))

        pdf_path = PDF_DIR / book["filename"]
        if pdf_path.exists():
            pdf_path.unlink()

        return jsonify({"ok": True})

    @app.route("/pdf/<path:filename>")
    def serve_pdf(filename: str):
        return send_from_directory(PDF_DIR, filename)

    @app.route("/api/book/<int:book_id>/progress", methods=["POST"])
    def save_progress(book_id: int):
        data = request.get_json(silent=True) or {}
        page = safe_int(data.get("page"), 1)
        total_pages = safe_int(data.get("totalPages"), 0)
        page = max(1, page)

        execute(
            """
            UPDATE books
            SET last_page = ?, total_pages = CASE WHEN ? > 0 THEN ? ELSE total_pages END
            WHERE id = ?
            """,
            (page, total_pages, total_pages, book_id),
        )
        return jsonify({"ok": True})

    @app.route("/api/book/<int:book_id>/bookmark", methods=["POST", "DELETE"])
    def bookmark(book_id: int):
        data = request.get_json(silent=True) or {}
        page = int(data.get("page", 1))
        page = max(1, page)

        if request.method == "POST":
            execute(
                """
                INSERT OR IGNORE INTO bookmarks (book_id, page, created_at)
                VALUES (?, ?, ?)
                """,
                (book_id, page, dt.datetime.utcnow().isoformat(timespec="seconds")),
            )
        else:
            execute(
                "DELETE FROM bookmarks WHERE book_id = ? AND page = ?",
                (book_id, page),
            )
        return jsonify({"ok": True})

    @app.route("/api/book/<int:book_id>/highlight", methods=["POST"])
    def add_highlight(book_id: int):
        data = request.get_json(silent=True) or {}
        page = int(data.get("page", 1))
        text = (data.get("text") or "").strip()
        color = (data.get("color") or "#ffe066").strip()

        if not text:
            return jsonify({"error": "Texto vazio"}), 400

        execute(
            """
            INSERT INTO highlights (book_id, page, text, color, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (book_id, page, text[:1200], color, dt.datetime.utcnow().isoformat(timespec="seconds")),
        )
        return jsonify({"ok": True})

    return app


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def query_all(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(query, params)
        return cur.fetchall()


def query_one(query: str, params: tuple = ()) -> sqlite3.Row | None:
    with get_conn() as conn:
        cur = conn.execute(query, params)
        return cur.fetchone()


def execute(query: str, params: tuple = ()) -> None:
    with get_conn() as conn:
        conn.execute(query, params)
        conn.commit()


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                filename TEXT NOT NULL UNIQUE,
                total_pages INTEGER NOT NULL DEFAULT 0,
                last_page INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bookmarks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                page INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(book_id, page),
                FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS highlights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                page INTEGER NOT NULL,
                text TEXT NOT NULL,
                color TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
            );
            """
        )
        conn.commit()


app = create_app()

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("DEBUG", "0").lower() in {"1", "true", "yes"}
    app.run(host=host, port=port, debug=debug)
