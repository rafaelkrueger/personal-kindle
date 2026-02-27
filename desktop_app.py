from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
import threading
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

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
        self.geometry("1440x880")
        self.configure(bg="#0f1420")
        self.minsize(1160, 700)

        self.books: list[sqlite3.Row] = []
        self.current_book: sqlite3.Row | None = None
        self.current_doc: fitz.Document | None = None
        self.current_page = 1
        self.zoom = 1.0
        self.tk_image: ImageTk.PhotoImage | None = None
        self.left_panel_visible = True
        self.left_panel: ttk.Frame | None = None
        self.toggle_left_btn: ttk.Button | None = None
        self.render_scale = 1.0
        self.render_offset_x = 0
        self.render_offset_y = 0
        self.selection_start: tuple[int, int] | None = None
        self.selection_rect_id: int | None = None
        self.selected_text = ""
        self.current_highlights: list[sqlite3.Row] = []
        self.ai_busy = False

        self._build_ui()
        self.refresh_library()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview", rowheight=28, fieldbackground="#1a2033", background="#1a2033", foreground="#dfe6ff")
        style.configure("Treeview.Heading", background="#263156", foreground="#eaf0ff")
        style.configure("TButton", padding=7)

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

        ttk.Label(self.left_panel, text="Bookmarks").pack(anchor="w", pady=(8, 3))
        self.bookmarks_list = tk.Listbox(self.left_panel, height=7, bg="#121932", fg="#dfe6ff", selectbackground="#2f5cff")
        self.bookmarks_list.pack(fill=tk.X)
        self.bookmarks_list.bind("<<ListboxSelect>>", self.on_select_bookmark)

        ttk.Label(self.left_panel, text="Grifos").pack(anchor="w", pady=(8, 3))
        self.highlights_list = tk.Listbox(self.left_panel, height=8, bg="#121932", fg="#dfe6ff", selectbackground="#2f5cff")
        self.highlights_list.pack(fill=tk.BOTH, expand=False)
        self.highlights_list.bind("<<ListboxSelect>>", self.on_select_highlight)

        controls = ttk.Frame(center)
        controls.pack(fill=tk.X)
        self.toggle_left_btn = ttk.Button(controls, text="Ocultar biblioteca", command=self.toggle_left_panel)
        self.toggle_left_btn.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(controls, text="Anterior", command=lambda: self.go_page(self.current_page - 1)).pack(side=tk.LEFT)
        ttk.Button(controls, text="Próxima", command=lambda: self.go_page(self.current_page + 1)).pack(side=tk.LEFT, padx=(6, 0))
        self.page_label = ttk.Label(controls, text="Página - / -")
        self.page_label.pack(side=tk.LEFT, padx=10)
        ttk.Button(controls, text="Marcar página", command=self.toggle_bookmark).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(controls, text="Grifar seleção", command=self.add_highlight_from_selection).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(controls, text="Perguntar IA", command=self.ask_ai_about_selection).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(controls, text="Traduzir", command=self.translate_selection).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(controls, text="A-", command=lambda: self.set_zoom(self.zoom - 0.1)).pack(side=tk.RIGHT)
        ttk.Button(controls, text="A+", command=lambda: self.set_zoom(self.zoom + 0.1)).pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Button(controls, text="100%", command=lambda: self.set_zoom(1.0)).pack(side=tk.RIGHT, padx=(0, 6))

        self.selection_info = ttk.Label(center, text="Seleção: arraste o mouse sobre a página para selecionar trecho.")
        self.selection_info.pack(fill=tk.X, pady=(6, 0))

        canvas_wrap = ttk.Frame(center)
        canvas_wrap.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.reader_canvas = tk.Canvas(canvas_wrap, bg="#0b0e17", highlightthickness=0)
        self.reader_canvas.pack(fill=tk.BOTH, expand=True)
        self.reader_canvas.bind("<Configure>", lambda _e: self.render_current_page())
        self.reader_canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.reader_canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.reader_canvas.bind("<ButtonRelease-1>", self.on_canvas_release)

        ttk.Label(center, text="Resposta da IA").pack(anchor="w", pady=(8, 3))
        self.ai_text = tk.Text(center, height=8, wrap=tk.WORD, bg="#10172c", fg="#e8edff")
        self.ai_text.pack(fill=tk.X)
        self.ai_text.insert("1.0", "Selecione um trecho da página e use Perguntar IA/Traduzir.")
        self.ai_text.config(state=tk.DISABLED)

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
        self.bookmarks_list.delete(0, tk.END)
        self.highlights_list.delete(0, tk.END)
        self.selected_text = ""
        self.selection_info.configure(text="Seleção: arraste o mouse sobre a página para selecionar trecho.")

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
        self.render_scale = fit_scale

        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        self.tk_image = ImageTk.PhotoImage(image)
        self.reader_canvas.delete("all")
        x = (cw - pix.width) // 2
        y = (ch - pix.height) // 2
        self.render_offset_x = max(0, x)
        self.render_offset_y = max(0, y)
        self.reader_canvas.create_image(max(0, x), max(0, y), anchor="nw", image=self.tk_image)
        self.draw_highlight_overlays()

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
        self.update_bookmark_label()
        self.refresh_highlight_list()

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
            self.bookmarks_list.delete(0, tk.END)
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
        self.bookmarks_list.delete(0, tk.END)
        for r in rows:
            self.bookmarks_list.insert(tk.END, f"Página {r['page']}")

    def on_select_bookmark(self, _event=None) -> None:
        if not self.current_doc:
            return
        idxs = self.bookmarks_list.curselection()
        if not idxs:
            return
        item = self.bookmarks_list.get(idxs[0])
        try:
            page = int(item.replace("Página", "").strip())
        except ValueError:
            return
        self.go_page(page)

    def refresh_highlight_list(self) -> None:
        if not self.current_book:
            self.current_highlights = []
            self.highlights_list.delete(0, tk.END)
            return
        self.current_highlights = query_all(
            """
            SELECT id, page, text, color
            FROM highlights
            WHERE book_id = ?
            ORDER BY created_at DESC
            """,
            (self.current_book["id"],),
        )
        self.highlights_list.delete(0, tk.END)
        for h in self.current_highlights:
            label = f"P{h['page']}: {h['text'][:60]}"
            self.highlights_list.insert(tk.END, label)

    def on_select_highlight(self, _event=None) -> None:
        idxs = self.highlights_list.curselection()
        if not idxs or not self.current_doc:
            return
        h = self.current_highlights[idxs[0]]
        self.go_page(h["page"])
        self.selected_text = h["text"]
        self.selection_info.configure(text=f"Seleção: {self.selected_text[:180]}")

    def draw_highlight_overlays(self) -> None:
        if not self.current_doc or not self.current_book:
            return
        highlights = query_all(
            """
            SELECT text
            FROM highlights
            WHERE book_id = ? AND page = ?
            """,
            (self.current_book["id"], self.current_page),
        )
        page = self.current_doc[self.current_page - 1]
        for h in highlights:
            text = (h["text"] or "").strip()
            if not text:
                continue
            for rect in page.search_for(text, quads=False):
                x0 = int(rect.x0 * self.render_scale + self.render_offset_x)
                y0 = int(rect.y0 * self.render_scale + self.render_offset_y)
                x1 = int(rect.x1 * self.render_scale + self.render_offset_x)
                y1 = int(rect.y1 * self.render_scale + self.render_offset_y)
                self.reader_canvas.create_rectangle(
                    x0,
                    y0,
                    x1,
                    y1,
                    outline="#ffdc42",
                    fill="#ffdc42",
                    stipple="gray50",
                    width=1,
                )

    def on_canvas_press(self, event: tk.Event) -> None:
        if not self.current_doc:
            return
        self.selection_start = (event.x, event.y)
        if self.selection_rect_id:
            self.reader_canvas.delete(self.selection_rect_id)
            self.selection_rect_id = None

    def on_canvas_drag(self, event: tk.Event) -> None:
        if not self.selection_start:
            return
        x0, y0 = self.selection_start
        x1, y1 = event.x, event.y
        if self.selection_rect_id:
            self.reader_canvas.coords(self.selection_rect_id, x0, y0, x1, y1)
        else:
            self.selection_rect_id = self.reader_canvas.create_rectangle(
                x0,
                y0,
                x1,
                y1,
                outline="#63c7ff",
                width=2,
                dash=(5, 2),
            )

    def on_canvas_release(self, event: tk.Event) -> None:
        if not self.current_doc or not self.selection_start:
            return
        x0, y0 = self.selection_start
        x1, y1 = event.x, event.y
        self.selection_start = None

        left = min(x0, x1)
        top = min(y0, y1)
        right = max(x0, x1)
        bottom = max(y0, y1)
        if right - left < 10 or bottom - top < 10:
            return

        page_rect = fitz.Rect(
            (left - self.render_offset_x) / self.render_scale,
            (top - self.render_offset_y) / self.render_scale,
            (right - self.render_offset_x) / self.render_scale,
            (bottom - self.render_offset_y) / self.render_scale,
        )
        page = self.current_doc[self.current_page - 1]
        words = page.get_text("words")
        selected = []
        for w in words:
            w_rect = fitz.Rect(w[0], w[1], w[2], w[3])
            if w_rect.intersects(page_rect):
                selected.append(w)
        selected.sort(key=lambda item: (item[5], item[6], item[7]))
        text = " ".join(w[4] for w in selected).strip()
        self.selected_text = text
        if text:
            self.selection_info.configure(text=f"Seleção: {text[:220]}")
        else:
            self.selection_info.configure(text="Nenhum texto detectado nessa seleção.")

    def add_highlight_from_selection(self) -> None:
        if not self.current_book:
            return
        text = (self.selected_text or "").strip()
        if not text:
            messagebox.showinfo("Grifar", "Selecione um trecho na página primeiro.")
            return
        execute(
            """
            INSERT INTO highlights (book_id, page, text, color, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (self.current_book["id"], self.current_page, text[:1200], "#ffe066", dt.datetime.utcnow().isoformat(timespec="seconds")),
        )
        self.refresh_highlight_list()
        self.render_current_page()

    def _set_ai_text(self, text: str) -> None:
        self.ai_text.config(state=tk.NORMAL)
        self.ai_text.delete("1.0", tk.END)
        self.ai_text.insert("1.0", text)
        self.ai_text.config(state=tk.DISABLED)

    def _run_ai(self, question: str) -> None:
        from app import call_openai

        system_prompt = (
            "Voce e um assistente de leitura de livros em PDF. "
            "Responda de forma clara, objetiva e em portugues do Brasil."
        )
        parts = [
            {
                "type": "input_text",
                "text": f"Pagina atual: {self.current_page}\n\nTrecho selecionado:\n{self.selected_text}\n\nPergunta:\n{question}",
            }
        ]
        answer = call_openai(system_prompt, parts)
        self.after(0, lambda: self._set_ai_text(answer))
        self.after(0, lambda: setattr(self, "ai_busy", False))

    def ask_ai_about_selection(self) -> None:
        if self.ai_busy:
            return
        if not self.selected_text.strip():
            messagebox.showinfo("IA", "Selecione um trecho para perguntar para a IA.")
            return
        prompt = simpledialog.askstring("Perguntar IA", "O que voce quer perguntar?")
        if not prompt:
            return
        self.ai_busy = True
        self._set_ai_text("Pensando...")
        threading.Thread(target=self._run_ai, args=(prompt,), daemon=True).start()

    def translate_selection(self) -> None:
        if self.ai_busy:
            return
        if not self.selected_text.strip():
            messagebox.showinfo("Traduzir", "Selecione um trecho para traduzir.")
            return
        self.ai_busy = True
        self._set_ai_text("Traduzindo...")
        threading.Thread(
            target=self._run_ai,
            args=("Traduza para portugues do Brasil mantendo o sentido original.",),
            daemon=True,
        ).start()

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
