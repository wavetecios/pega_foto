# Pega Foto

Galeria de fotos em Django. O endpoint recebe imagens pelo campo multipart
`imagem` e aceita `codigo_evento` opcional (padrão: `evento_padrao`).

## Desenvolvimento local

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py makemigrations galeria
python manage.py migrate
python manage.py runserver
```

As variáveis do arquivo `.env.example` são referências: configure-as no ambiente
antes de iniciar o servidor (o Django não carrega arquivos `.env` por padrão).

Abra `http://127.0.0.1:8000/` para a galeria padrão. Para um evento específico,
use `http://127.0.0.1:8000/?evento=CODIGO_DO_EVENTO`.

O endpoint `POST /api/upload/` espera `multipart/form-data`:

- `imagem`: arquivo de imagem (obrigatório)
- `codigo_evento`: código do evento (opcional)
- `X-API-KEY`: chave configurada na variável de ambiente `TOTEM_API_KEY`

Exemplo de teste com cURL:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/upload/ `
  -H "X-API-KEY: dev-totem-api-key-change-me" `
  -F "imagem=@C:\caminho\foto.jpg" `
  -F "codigo_evento=meu_evento"
```

O endpoint rejeita chaves ausentes/incorretas com HTTP 401 e valida que o
arquivo é uma imagem válida de até 10 MB antes de salvá-lo. No desenvolvimento,
se `TOTEM_API_KEY` não estiver definida, a chave padrão é
`dev-totem-api-key-change-me`; em produção ela é obrigatória.

Exemplo de envio pelo totem em `app.py` (instale `requests` no ambiente do
totem):

```python
import os

import requests

chave = os.environ["TOTEM_API_KEY"]
with open("foto.jpg", "rb") as imagem:
    resposta = requests.post(
        "https://seu-dominio.onrender.com/api/upload/",
        headers={"X-API-KEY": chave},
        files={"imagem": imagem},
        data={"codigo_evento": "meu_evento"},
        timeout=30,
    )
resposta.raise_for_status()
```

Para fazer o envio sem bloquear a interface, o módulo auxiliar
[envio_galeria.py](/C:/pega_fotos/envio_galeria.py) inicia uma thread daemon.
Depois de salvar cada arquivo de **1 Foto** ou **Tira 3x**, integre no `app.py`:

```python
from envio_galeria import enviar_foto_em_segundo_plano

# Chame após salvar a foto em fotos_prontas/:
enviar_foto_em_segundo_plano(caminho_arquivo, codigo_evento="meu_evento")
```

O módulo usa `TOTEM_API_KEY` do ambiente quando definida; sem ela, usa a chave
padrão de desenvolvimento, que não deve ser utilizada em produção.

## Render

Defina `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False` e `DJANGO_ALLOWED_HOSTS` nas
variáveis de ambiente do serviço e configure `TOTEM_API_KEY` com uma chave
aleatória e forte. Configure a mesma chave como variável de ambiente
`TOTEM_API_KEY` no totem. Não use a chave padrão de desenvolvimento em produção.
Para arquivos de mídia persistentes, crie um
Persistent Disk e defina `MEDIA_ROOT` com o caminho de montagem (por exemplo,
`/var/data/media`). Se o serviço usar PostgreSQL, informe a variável
`DATABASE_URL`. Use `pip install -r requirements.txt` e
`python manage.py collectstatic --noinput` no build, `python manage.py migrate`
como comando pre-deploy e `gunicorn pega_foto.wsgi:application` como comando de
inicialização.

O backend de arquivos padrão é local (`FileSystemStorage`); para armazenamento
de objetos em nuvem, configure um backend Django compatível por
`DEFAULT_STORAGE_BACKEND` e instale as dependências desse backend.
