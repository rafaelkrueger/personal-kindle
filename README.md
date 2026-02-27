# MiniKindle

Leitor web de PDF leve e bonito, com:
- biblioteca de livros (upload de PDF)
- salvamento automatico da ultima pagina lida
- marcacao de paginas (bookmarks)
- grifos por texto selecionado

## Requisitos

- Python 3.10+ (recomendado)
- `pip`

## Como rodar (Windows / PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python .\app.py
```

Abra no navegador: `http://localhost:8080`

## Como rodar (Raspberry Pi / Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

Abra no navegador:
- no proprio Raspberry: `http://localhost:8080`
- em outro dispositivo da rede: `http://IP_DO_RASPBERRY:8080`

## Primeiro uso

1. Acesse a tela inicial.
2. Envie um PDF na area de upload.
3. Clique em **Continuar leitura**.
4. Use:
   - **Marcar pagina** para salvar bookmarks
   - **Grifar selecao** para salvar trechos

## Estrutura do projeto

- `app.py`: backend Flask + API + SQLite
- `data/books.db`: banco local (criado automaticamente)
- `data/pdfs/`: PDFs enviados
- `templates/`: telas HTML
- `static/`: CSS e JavaScript

## Problemas comuns

- **Porta em uso**: altere a porta no final de `app.py` (`port=8080`).
- **Porta em uso ou bloqueada no Windows**: rode em outra porta:
  - PowerShell: `$env:PORT=5001; python .\app.py`
  - Linux: `PORT=5001 python3 app.py`
- **Python nao encontrado**: confirme instalacao com `python --version` (ou `python3 --version` no Linux).
- **Dependencias falhando**: atualize o `pip` com `python -m pip install --upgrade pip`.
