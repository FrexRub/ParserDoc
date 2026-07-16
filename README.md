# ParserDoc

ParserDoc - это асинхронный HTTP-сервис на FastAPI для извлечения текста из документов. Он принимает файл по HTTP, определяет подходящий парсер, извлекает и нормализует текст, а затем возвращает структурированный JSON.

Сервис удобно использовать в n8n перед AI Agent, LLM-нодами, базами данных, поиском или любыми workflow, где нужно получить чистый текст из документа.

## Возможности

Поддерживаемые форматы:

- PDF
- DOCX
- DOC
- RTF
- XLS
- TXT
- CSV
- HTML
- JSON
- XML

Ответ при успешном парсинге содержит:

- `status`
- `filename`
- `mime_type`
- `source_type`
- `characters`
- `text`
- `warnings`

Ошибки возвращаются в JSON-формате с полями:

- `status`
- `error`
- `detail`

## Локальный запуск

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -v
uvicorn app.main:app --reload
```

Проверка работоспособности:

```powershell
curl http://127.0.0.1:8000/health
```

Ожидаемый ответ:

```json
{"status":"ok"}
```

## Запуск через Docker Compose

```powershell
docker compose up --build
```

Внутри контейнера сервис слушает порт `8000`. По умолчанию `docker-compose.yml` пробрасывает порт хоста `8000` на порт контейнера `8000`.

Если нужно изменить порт на хосте:

```powershell
$env:PORT=8080
docker compose up --build
```

Полезные переменные окружения:

- `PORT` - порт на хосте, по умолчанию `8000`.
- `PARSERDOC_MAX_UPLOAD_BYTES` - максимальный размер загружаемого файла в байтах, по умолчанию `20971520`.
- `PARSERDOC_REQUEST_TIMEOUT_SECONDS` - таймаут запроса, по умолчанию `120`.

В `docker-compose.yml` сервис подключается к внешней сети Docker и получает alias `parserdoc`. Благодаря этому из контейнера n8n можно обращаться к сервису по адресу:

```text
http://parserdoc:8000
```

Если n8n запущен не в той же Docker-сети, адрес `http://parserdoc:8000` работать не будет. В этом случае используйте внешний адрес сервиса, например:

```text
http://localhost:8000
http://IP_СЕРВЕРА:8000
https://ваш-домен.example
```

## API

### `GET /health`

Проверка состояния сервиса.

```text
GET http://parserdoc:8000/health
```

Ответ:

```json
{"status":"ok"}
```

### `POST /parse`

Основной endpoint для n8n. Принимает `multipart/form-data` с файлом в поле `file`.

```text
POST http://parserdoc:8000/parse
```

Форма:

```text
file = binary file
```

### `POST /parse/raw`

Альтернативный endpoint для отправки файла сырым бинарным телом запроса.

```text
POST http://parserdoc:8000/parse/raw?filename=document.pdf&mime_type=application/pdf
```

Параметры:

- `filename` - имя файла, нужно для определения типа документа.
- `mime_type` - MIME-тип файла, необязательный, но полезный для точного выбора парсера.

## Настройка n8n HTTP Request node

Рекомендуемый способ - отправлять файл как `multipart/form-data` на endpoint `/parse`.

### Вариант 1: отправка файла через Form-Data

Используйте этот вариант, если файл в n8n лежит в binary-поле после ноды Telegram, Email, Google Drive, Read Binary File, HTTP Request или другой файловой ноды.

Настройки ноды `HTTP Request`:

- **Method:** `POST`
- **URL:** `http://parserdoc:8000/parse`
- **Authentication:** `None`
- **Send Body:** `On`
- **Body Content Type:** `Form-Data`
- **Response Format:** `JSON`

В разделе **Body Parameters** добавьте параметр:

- **Parameter Type:** `n8n Binary File`
- **Name:** `file`
- **Input Data Field Name:** `data`

Итоговая логика запроса:

```text
POST http://parserdoc:8000/parse

multipart/form-data:
file = {{$binary.data}}
```

Важно: `data` - это стандартное имя binary-поля в n8n, но оно может отличаться. Если предыдущая нода записала файл в другое binary-поле, укажите его имя в **Input Data Field Name**.

Примеры возможных имен binary-поля:

- `data`
- `file`
- `document`
- `attachment_0`

Посмотреть имя binary-поля можно в output предыдущей ноды во вкладке **Binary**.

Не добавляйте header `Content-Type: multipart/form-data` вручную. n8n сам сформирует этот заголовок вместе с `boundary`.

### Вариант 2: отправка raw binary

Используйте этот вариант только если workflow удобнее отправлять тело запроса напрямую как бинарные данные.

Настройки ноды `HTTP Request`:

- **Method:** `POST`
- **URL:** `http://parserdoc:8000/parse/raw`
- **Authentication:** `None`
- **Send Body:** `On`
- **Body Content Type:** `Binary Data`
- **Input Data Field Name:** `data`
- **Response Format:** `JSON`

Добавьте query parameters:

- `filename` = `{{$binary.data.fileName}}`
- `mime_type` = `{{$binary.data.mimeType}}`

Итоговый URL можно собрать так:

```text
http://parserdoc:8000/parse/raw?filename={{$binary.data.fileName}}&mime_type={{$binary.data.mimeType}}
```

Если binary-поле называется не `data`, замените `data` в выражениях на фактическое имя поля.

## Пример использования результата в n8n

После успешного запроса ParserDoc вернет JSON. Основной текст документа находится в поле:

```text
{{$json.text}}
```

Его можно передать дальше в AI Agent, OpenAI node, базу данных, поиск или любую другую ноду.

Пример полей ответа:

```json
{
  "status": "ok",
  "filename": "document.pdf",
  "mime_type": "application/pdf",
  "source_type": "pdf",
  "characters": 12345,
  "text": "Извлеченный текст документа...",
  "warnings": []
}
```

## Настройка Docker-сети для n8n

Чтобы адрес `http://parserdoc:8000` работал из n8n, контейнеры `n8n` и `parserdoc` должны быть в одной Docker-сети.

В текущем `docker-compose.yml` используется внешняя сеть:

```yaml
networks:
  parserdoc_net:
    name: n8n-n8n-9hh60z
    external: true
```

Если ваша сеть n8n называется иначе, замените значение в поле `name`

Имя сети можно посмотреть командой:

```powershell
docker network ls
```

## Развертывание в Dokploy

Используйте GitHub-репозиторий как источник проекта и деплойте через Docker Compose.

Рекомендуемые настройки:

- **Compose file:** `docker-compose.yml`
- **Service:** `parserdoc`
- **Internal container port:** `8000`
- **Health check path:** `/health`
- **Public route:** ваш домен или поддомен

Переменные окружения задавайте только если нужно переопределить значения по умолчанию:

```env
PORT=8000
PARSERDOC_MAX_UPLOAD_BYTES=20971520
PARSERDOC_REQUEST_TIMEOUT_SECONDS=120
```

После деплоя проверьте:

```text
GET https://your-domain.example/health
```

Ожидаемый ответ:

```json
{"status":"ok"}
```

Если n8n обращается к ParserDoc через публичный домен, используйте в HTTP Request node URL вида:

```text
https://your-domain.example/parse
```

## Зависимости парсеров

Docker-образ включает основные зависимости для парсинга:

- PyMuPDF для PDF
- striprtf для RTF
- xlrd для XLS
- antiword, catdoc и LibreOffice Writer для legacy DOC

Если формат не поддерживается или для него не хватает зависимости, сервис вернет понятную ошибку в JSON.
