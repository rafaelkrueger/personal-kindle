const dropzone = document.getElementById("dropzone");
const input = document.getElementById("pdfInput");
const form = document.getElementById("uploadForm");
const toast = document.getElementById("toast");

if (dropzone && input && form) {
  ["dragenter", "dragover"].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("drag");
    });
  });

  ["dragleave", "drop"].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("drag");
    });
  });

  dropzone.addEventListener("drop", (e) => {
    const files = e.dataTransfer?.files;
    if (!files || !files.length) return;
    input.files = files;
    form.submit();
  });
}

function showToast(message, isError = false) {
  if (!toast) return;
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2200);
}

document.querySelectorAll(".delete-book-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const bookId = btn.dataset.bookId;
    const title = btn.dataset.bookTitle || "este livro";
    const ok = window.confirm(`Excluir "${title}"?\nEssa acao remove o PDF e os dados salvos.`);
    if (!ok) return;

    btn.disabled = true;
    try {
      const res = await fetch(`/api/book/${bookId}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Falha ao excluir");
      showToast("Livro excluido com sucesso.");
      setTimeout(() => window.location.reload(), 350);
    } catch (err) {
      btn.disabled = false;
      showToast("Nao foi possivel excluir o livro.", true);
    }
  });
});
