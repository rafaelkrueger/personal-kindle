# Mini Kindle

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

Abra no navegador: `http://localhost:5000`

## Como rodar (Raspberry Pi / Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

Abra no navegador:
- no proprio Raspberry: `http://localhost:5000`
- em outro dispositivo da rede: `http://IP_DO_RASPBERRY:5000`

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

- **Porta em uso**: altere pela variavel de ambiente `PORT` (ex: `PORT=5001 python3 app.py`).
- **Porta em uso ou bloqueada no Windows**: rode em outra porta:
  - PowerShell: `$env:PORT=5001; python .\app.py`
  - Linux: `PORT=5001 python3 app.py`
- **Python nao encontrado**: confirme instalacao com `python --version` (ou `python3 --version` no Linux).
- **Dependencias falhando**: atualize o `pip` com `python -m pip install --upgrade pip`.

## Deploy automatico no Raspberry Pi (push na main)

Este projeto ja tem workflow em `.github/workflows/deploy-raspberry.yml`.

Fluxo:
1. Voce faz `git push` na branch `main`.
2. O GitHub Actions conecta via SSH no Raspberry.
3. O Pi roda `git pull --ff-only`, instala dependencias e reinicia o servico.

### 1) Secrets no GitHub (obrigatorios)

No repositorio: `Settings > Secrets and variables > Actions > New repository secret`

- `PI_HOST`: IP publico ou dominio do Raspberry
- `PI_USER`: usuario SSH (ex: `rafaelkrueger`)
- `PI_SSH_KEY`: chave privada SSH (conteudo completo)
- `PI_PORT` (opcional): porta SSH, normalmente `22`

### 2) Preparar o servico no Pi

O workflow reinicia um servico chamado `personal-kindle`. Exemplo de unidade:

```ini
[Unit]
Description=Personal Kindle
After=network.target

[Service]
User=rafaelkrueger
WorkingDirectory=/home/rafaelkrueger/personal-kindle
Environment="PATH=/home/rafaelkrueger/personal-kindle/.venv/bin"
ExecStart=/home/rafaelkrueger/personal-kindle/.venv/bin/gunicorn -w 1 -b 0.0.0.0:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

### 3) Permitir restart sem senha (sudoers)

No Raspberry, rode `sudo visudo` e adicione:

```text
rafaelkrueger ALL=NOPASSWD: /bin/systemctl restart personal-kindle, /bin/systemctl is-active personal-kindle, /bin/systemctl status personal-kindle
```

### 4) Opcional: nome diferente de pasta/servico

Se sua pasta/servico tiver outro nome, adicione variaveis no GitHub:

- `PI_APP_DIR` (ex: `/home/rafaelkrueger/personal-kindle`)
- `PI_SERVICE_NAME` (ex: `personal-kindle`)
