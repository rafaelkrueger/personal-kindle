from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import fitz  # PyMuPDF
from PIL import Image, ImageTk


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PDF_DIR = DATA_DIR / "pdfs"
DB_PATH = DATA_DIR / "books.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def execute(query: str, params: tuple = ()) -> None:
    with get_conn() as conn:
        conn.execute(query, params)
        conn.commit()


def query_all(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(query, params)
        return cur.fetchall()


def query_one(query: str, params: tuple = ()) -> sqlite3.Row | None:
    with get_conn() as conn:
        cur = conn.execute(query, params)
        return cur.fetchone()


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
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


class DesktopReader(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MiniKindle Desktop")
        self.geometry("1320x820")
        self.configure(bg="#10131d")
        self.minsize(1020, 640)

        self.books: list[sqlite3.Row] = []
        self.current_book: sqlite3.Row | None = None
        self.current_doc: fitz.Document | None = None
        self.current_page = 1
        self.zoom = 1.0
        self.tk_image: ImageTk.PhotoImage | None = None
        self.left_panel_visible = True
        self.left_panel: ttk.Frame | None = None
        self.toggle_left_btn: ttk.Button | None = None

        self._build_ui()
        self.refresh_library()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview", rowheight=28, fieldbackground="#1a2033", background="#1a2033", foreground="#dfe6ff")
        style.configure("Treeview.Heading", background="#263156", foreground="#eaf0ff")

        root = ttk.Frame(self)
        root.pack(fill=tk.BOTH, expand=True)

        self.left_panel = ttk.Frame(root, width=340)
        self.left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        self.left_panel.pack_propagate(False)

        center = ttk.Frame(root)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10), pady=10)

        ttk.Label(self.left_panel, text="Biblioteca", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        top_actions = ttk.Frame(self.left_panel)
        top_actions.pack(fill=tk.X, pady=(8, 8))
        ttk.Button(top_actions, text="Importar PDF", command=self.import_pdf).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(top_actions, text="Excluir", command=self.delete_selected_book).pack(side=tk.LEFT, padx=(6, 0))

        cols = ("title", "progress")
        self.library_tree = ttk.Treeview(self.left_panel, columns=cols, show="headings", selectmode="browse")
        self.library_tree.heading("title", text="Livro")
        self.library_tree.heading("progress", text="Progresso")
        self.library_tree.column("title", width=220)
        self.library_tree.column("progress", width=90, anchor=tk.CENTER)
        self.library_tree.pack(fill=tk.BOTH, expand=True)
        self.library_tree.bind("<<TreeviewSelect>>", self.on_select_book)

        self.bookmark_label = ttk.Label(self.left_panel, text="Bookmarks: -")
        self.bookmark_label.pack(anchor="w", pady=(8, 0))

        controls = ttk.Frame(center)
        controls.pack(fill=tk.X)
        self.toggle_left_btn = ttk.Button(controls, text="Ocultar biblioteca", command=self.toggle_left_panel)
        self.toggle_left_btn.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(controls, text="Anterior", command=lambda: self.go_page(self.current_page - 1)).pack(side=tk.LEFT)
        ttk.Button(controls, text="Próxima", command=lambda: self.go_page(self.current_page + 1)).pack(side=tk.LEFT, padx=(6, 0))
        self.page_label = ttk.Label(controls, text="Página - / -")
        self.page_label.pack(side=tk.LEFT, padx=10)
        ttk.Button(controls, text="Marcar página", command=self.toggle_bookmark).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(controls, text="A-", command=lambda: self.set_zoom(self.zoom - 0.1)).pack(side=tk.RIGHT)
        ttk.Button(controls, text="A+", command=lambda: self.set_zoom(self.zoom + 0.1)).pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Button(controls, text="100%", command=lambda: self.set_zoom(1.0)).pack(side=tk.RIGHT, padx=(0, 6))

        canvas_wrap = ttk.Frame(center)
        canvas_wrap.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.reader_canvas = tk.Canvas(canvas_wrap, bg="#0b0e17", highlightthickness=0)
        self.reader_canvas.pack(fill=tk.BOTH, expand=True)
        self.reader_canvas.bind("<Configure>", lambda _e: self.render_current_page())

    def toggle_left_panel(self) -> None:
        if not self.left_panel:
            return
        self.left_panel_visible = not self.left_panel_visible
        if self.left_panel_visible:
            self.left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
            if self.toggle_left_btn:
                self.toggle_left_btn.configure(text="Ocultar biblioteca")
        else:
            self.left_panel.pack_forget()
            if self.toggle_left_btn:
                self.toggle_left_btn.configure(text="Mostrar biblioteca")

    def refresh_library(self) -> None:
        self.books = query_all(
            """
            SELECT id, title, filename, total_pages, last_page
            FROM books
            ORDER BY created_at DESC
            """
        )
        self.library_tree.delete(*self.library_tree.get_children())
        for b in self.books:
            total = b["total_pages"] or 0
            last = b["last_page"] or 1
            pct = f"{int((last / total) * 100)}%" if total > 0 else "0%"
            self.library_tree.insert("", tk.END, iid=str(b["id"]), values=(b["title"], pct))

    def import_pdf(self) -> None:
        src = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if not src:
            return
        src_path = Path(src)
        unique_name = f"{uuid.uuid4().hex}_{src_path.name}"
        dst = PDF_DIR / unique_name
        shutil.copy2(src_path, dst)
        execute(
            """
            INSERT INTO books (title, filename, total_pages, last_page, created_at)
            VALUES (?, ?, 0, 1, ?)
            """,
            (src_path.stem, unique_name, dt.datetime.utcnow().isoformat(timespec="seconds")),
        )
        self.refresh_library()

    def delete_selected_book(self) -> None:
        book = self._selected_book()
        if not book:
            return
        ok = messagebox.askyesno("Excluir livro", f'Excluir "{book["title"]}"?')
        if not ok:
            return
        execute("DELETE FROM books WHERE id = ?", (book["id"],))
        pdf = PDF_DIR / book["filename"]
        if pdf.exists():
            pdf.unlink()
        if self.current_book and self.current_book["id"] == book["id"]:
            self.close_document()
        self.refresh_library()

    def _selected_book(self) -> sqlite3.Row | None:
        selected = self.library_tree.selection()
        if not selected:
            return None
        book_id = int(selected[0])
        return next((b for b in self.books if b["id"] == book_id), None)

    def on_select_book(self, _event=None) -> None:
        book = self._selected_book()
        if not book:
            return
        if self.current_book and self.current_book["id"] == book["id"]:
            return
        self.open_book(book)

    def open_book(self, book: sqlite3.Row) -> None:
        self.save_progress()
        self.close_document()
        pdf_path = PDF_DIR / book["filename"]
        if not pdf_path.exists():
            messagebox.showerror("Erro", "PDF não encontrado em data/pdfs.")
            return
        self.current_doc = fitz.open(pdf_path)
        self.current_book = book
        self.current_page = max(1, min(book["last_page"], len(self.current_doc)))
        self.zoom = 1.0
        self.render_current_page()
        self.update_bookmark_label()

    def close_document(self) -> None:
        if self.current_doc is not None:
            self.current_doc.close()
        self.current_doc = None
        self.current_book = None
        self.current_page = 1
        self.page_label.configure(text="Página - / -")
        self.reader_canvas.delete("all")
        self.bookmark_label.configure(text="Bookmarks: -")

    def set_zoom(self, value: float) -> None:
        self.zoom = max(0.7, min(2.3, value))
        self.render_current_page()

    def go_page(self, page: int) -> None:
        if not self.current_doc:
            return
        if page < 1 or page > len(self.current_doc):
            return
        self.current_page = page
        self.render_current_page()
        self.save_progress()
        self.update_bookmark_label()

    def render_current_page(self) -> None:
        if not self.current_doc:
            return
        page = self.current_doc[self.current_page - 1]

        cw = max(self.reader_canvas.winfo_width(), 400)
        ch = max(self.reader_canvas.winfo_height(), 400)
        base = page.rect
        fit_scale = min(cw / base.width, ch / base.height) * self.zoom
        matrix = fitz.Matrix(fit_scale, fit_scale)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        self.tk_image = ImageTk.PhotoImage(image)
        self.reader_canvas.delete("all")
        x = (cw - pix.width) // 2
        y = (ch - pix.height) // 2
        self.reader_canvas.create_image(max(0, x), max(0, y), anchor="nw", image=self.tk_image)

        self.page_label.configure(text=f"Página {self.current_page} / {len(self.current_doc)}")

        execute(
            """
            UPDATE books
            SET total_pages = ?
            WHERE id = ?
            """,
            (len(self.current_doc), self.current_book["id"]),
        )
        self.refresh_progress_cell()

    def refresh_progress_cell(self) -> None:
        if not self.current_doc or not self.current_book:
            return
        total = len(self.current_doc)
        pct = f"{int((self.current_page / total) * 100)}%" if total > 0 else "0%"
        item = str(self.current_book["id"])
        if self.library_tree.exists(item):
            current_title = self.library_tree.item(item, "values")[0]
            self.library_tree.item(item, values=(current_title, pct))

    def save_progress(self) -> None:
        if not self.current_book:
            return
        execute(
            """
            UPDATE books
            SET last_page = ?
            WHERE id = ?
            """,
            (self.current_page, self.current_book["id"]),
        )

    def toggle_bookmark(self) -> None:
        if not self.current_book:
            return
        exists = query_one(
            """
            SELECT id FROM bookmarks
            WHERE book_id = ? AND page = ?
            """,
            (self.current_book["id"], self.current_page),
        )
        if exists:
            execute(
                "DELETE FROM bookmarks WHERE book_id = ? AND page = ?",
                (self.current_book["id"], self.current_page),
            )
        else:
            execute(
                """
                INSERT INTO bookmarks (book_id, page, created_at)
                VALUES (?, ?, ?)
                """,
                (self.current_book["id"], self.current_page, dt.datetime.utcnow().isoformat(timespec="seconds")),
            )
        self.update_bookmark_label()

    def update_bookmark_label(self) -> None:
        if not self.current_book:
            self.bookmark_label.configure(text="Bookmarks: -")
            return
        rows = query_all(
            """
            SELECT page
            FROM bookmarks
            WHERE book_id = ?
            ORDER BY page ASC
            """,
            (self.current_book["id"],),
        )
        pages = [str(r["page"]) for r in rows]
        text = ", ".join(pages[:12])
        if len(pages) > 12:
            text += " ..."
        self.bookmark_label.configure(text=f"Bookmarks: {text or '-'}")

    def on_close(self) -> None:
        self.save_progress()
        self.destroy()


def main() -> None:
    init_db()
    # Tkinter exige sessao grafica ativa no Linux.
    if os.name != "nt" and not os.getenv("DISPLAY"):
        host = os.getenv("HOST", "0.0.0.0")
        port = int(os.getenv("PORT", "5000"))
        print("Sem DISPLAY detectado. Iniciando modo web automaticamente.")
        print(f"Acesse: http://127.0.0.1:{port} ou http://IP_DO_RASPBERRY:{port}")
        from app import app as web_app

        web_app.run(host=host, port=port, debug=False)
        return

    try:
        app = DesktopReader()
        app.mainloop()
    except tk.TclError:
        host = os.getenv("HOST", "0.0.0.0")
        port = int(os.getenv("PORT", "5000"))
        print("Falha ao abrir interface grafica. Iniciando modo web automaticamente.")
        print(f"Acesse: http://127.0.0.1:{port} ou http://IP_DO_RASPBERRY:{port}")
        from app import app as web_app

        web_app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
