# Публикация на GitHub

Репозиторий уже инициализирован, текущая ветка — `main`. В индексе нет `.env`,
баз SQLite, ключей и portable-архивов: они перечислены в `.gitignore`.

## Первый push

```powershell
cd D:\ds\progy\statlab
git status
git remote add origin https://github.com/<аккаунт>/<репозиторий>.git
git push -u origin main
```

Если remote уже добавлен, достаточно `git push`.

## CI

Файл `.github/workflows/ci.yml` запускает на каждый push и pull request:

1. установку Python-зависимостей;
2. `pytest web/tests`;
3. `npm ci`, `npm run build` и `npm run lint` во фронтенде.

Локально те же проверки:

```powershell
$env:PYTHONPATH = "src"
web\.venv\Scripts\python -m pytest web\tests -q
python -m pytest tests -q

cd web\frontend
npm.cmd run build
npm.cmd run lint
```

## Что не попадает в репозиторий

- `web/*.db` — локальная база;
- `web/data/` — загруженные наборы;
- `web/frontend/dist/` и `node_modules/`;
- `build/`, `dist/`, `dist-web/`, `*.exe`;
- `build/openrouter.key.txt` (локальный ключ OpenRouter).

Перед публикацией полезно проверить:

```powershell
git status --short
git ls-files | Select-String -Pattern '\.env|\.key|\.db$|openrouter.key'
```

Команда должна не найти секретов и локальных баз.

## Для наставника

- Веб-версия: `web\run.cmd`, затем <http://127.0.0.1:8000/>.
- Переносная сборка: `dist-web\Winnow-web-portable.zip` (не коммитится,
  собирается `tools\build_web_portable.ps1`).
- Архитектура и функции: `README.md`, `web/README.md`, `docs/`.
