# ЛР5. Continuous Integration

Система — GitHub Actions, реестр образов — GitHub Container Registry (GHCR).
Задача: [#9](https://github.com/nopopjustrap/devops_auction/issues/9).
[Фактические результаты и ссылки на CI-демонстрации](verification-lr5.md).
Workflow: `.github/workflows/ci.yml`.

## Запуск и единые команды

CI запускается при push в любую ветку, создании/обновлении PR и вручную через
workflow_dispatch. Push в main также запускает CI и после всех проверок —
публикацию. В PR публикации нет. Отмена старого запуска не разрешает публикацию.

Требования для локальной полной проверки: Linux/WSL, Python 3.12, GNU Make,
Git, Docker Engine (либо Docker Desktop с интеграцией WSL), доступ к PyPI,
GitHub/GHCR и источникам баз уязвимостей. Docker должен быть доступен без sudo.

```bash
make setup PYTHON="$(uv python find 3.12)"
docker version
make verify
```

`uv` нужен только если Python 3.12 установлен через него. При системном 3.12
достаточно `make setup`. Запуск приложения не изменился: `make run`.
Новые сетевые проверки не подменяются успешными заглушками при недоступности сервиса.

| Этап CI | Локальная команда | Проверка и отчёты |
| --- | --- | --- |
| policy | `make policy-check` | Состав проверок, пороги и удаление тестов относительно BASE_REF; acceptance.json |
| style | `.venv/bin/python -m pip check`, `make quality` | Совместимость зависимостей, Ruff lint/format; style.log |
| tests | `make test`, `make mutation-check` | Полный pytest, JUnit, coverage XML/HTML, FR JSON, mutations.json |
| migrations | `make migration-check` | Чистая/заполненная БД, сохранность данных, откат; migrations.xml |
| backup | `make backup-check`, `make backup-demo` | Восстановление после изменения/удаления, WAL; backup.xml и лог |
| security | `make security` | Bandit для app и migrations; bandit.json |
| dependencies | `make dependencies-check` | pip-audit по всем пакетам requirements.lock; dependencies.json |
| secrets | `make secrets-check` | Gitleaks: история HEAD и текущие неигнорируемые файлы; два редактированных JSON |
| build | `make container-build` | Сборка образа только после всех предыдущих этапов |
| container-smoke | `make container-check` | Непривилегированный запуск, read-only root, /health, /ready, UI |
| container-scan | `make container-scan` | Trivy: HIGH/CRITICAL уязвимости ОС и библиотек, без ignore-unfixed |
| ci-gate | Проверка результатов всех заданий | Ошибка при failed, cancelled или skipped обязательного задания |
| publish | Только GitHub Actions на push в main | Публикация уже проверенного образа без повторной сборки |

`make verify` вызывает все перечисленные локальные проверки, включая Docker.
Отдельные этапы migrations/backup повторяют профильные тесты общего набора,
чтобы на защите и в CI было видно, какой именно этап остановился.
Все базовые проверки матрицы независимы и могут работать параллельно; build
зависит от успеха всей матрицы, контейнерные проверки — от build, а publish —
от ci-gate. CI не содержит continue-on-error для обязательных проверок.

Для локального сравнения с основной веткой:

```bash
git fetch origin main
BASE_REF="$(git rev-parse origin/main)" make policy-check
```

## Изоляция, отчёты и кэш

Каждая проверка работает на отдельном GitHub-hosted runner. DATABASE_PATH
указывает на RUNNER_TEMP; pytest использует tmp_path. Данные рабочей SQLite,
.env и резервные копии не загружаются в CI. Контейнерный smoke-тест использует
отдельную tmpfs /data; контейнер удаляется после проверки.

Отчёты сохраняются через upload-artifact с `if: always()`, включая ошибочные
прогоны. Срок хранения отчётов — 14 дней, промежуточного образа — 3 дня.
Поиск секретов использует полное редактирование найденных значений; настоящие
пароли и токены в демонстрации не используются. Каталог reports исключён из Git.

setup-python кэширует загрузки pip по requirements-файлам. Trivy кэширует базу
уязвимостей, но выполняет её штатное обновление. Виртуальное окружение не
переносится между runner. Версии Actions зафиксированы полными commit SHA;
версии сканеров заданы в `.ci/tools.env`. Изменение этих файлов критическое.

## Сборка и публикация

Dockerfile использует отдельную стадию установки зависимостей и runtime без
тестов, отчётов, исходной .git, .env и БД. Контейнер работает под UID 10001.
Образ Python берётся из `python:3.12.15-alpine3.24`; тег обновляемый, поэтому
это не побитовая воспроизводимость между разными запусками. В одном pipeline
образ строится один раз, сохраняется в tar с SHA-256 и именно этот tar
проверяется и публикуется. Повторной сборки перед push нет.

Тег результата:

```text
ghcr.io/nopopjustrap/devops_auction:sha-<полный commit SHA>
```

Право `packages: write` выдано только заданию publish. Остальные задания имеют
`contents: read`. Для входа в GHCR используется временный `secrets.GITHUB_TOKEN`,
передаваемый docker login через stdin. PAT в код и .env добавлять не требуется.
Публикация пакетов должна быть разрешена политиками GitHub аккаунта/репозитория.
Развёртывание приложения на сервере в этой ЛР не настраивается.

## Защита приёмки: обязательная настройка владельцем

**Файлы конфигурации сами по себе не включают защиту GitHub.** Для завершения
ЛР необходимо активировать server-side правила. До этого CI не является
обязательным барьером слияния: владелец может вручную слить красный PR.

`.github/CODEOWNERS` назначает владельца критическим файлам: tests, Makefile,
настройкам анализаторов, requirements, migrations, scripts, Dockerfile,
workflow и самому CODEOWNERS. Сейчас указан реальный владелец @nopopjustrap.

**Автор не может одобрить собственный PR.** Для PR самого владельца нужен
второй реальный участник с write-доступом, добавленный в соответствующие строки
CODEOWNERS (например преподаватель/напарник). Не следует выдумывать аккаунт,
отключать обязательные approvals или использовать admin bypass для демонстрации.

Дополнительный workflow `critical-review.yml` работает на pull_request_target:
он читает только код доверенной base-ветки и метаданные PR через API. Код PR,
его зависимости, Dockerfile и artifacts в этом workflow НЕ выполняются.
При изменении критического файла требуется approval независимого владельца
из CODEOWNERS для текущего head SHA. После review нужно повторно запустить
этот workflow через Re-run jobs; новый push требует нового approval.

При первоначальном внедрении workflow ещё отсутствует в main: независимый
барьер начинает работать только после принятия этой конфигурации в main.
Первоначальный PR следует отдельно проверить полностью; нельзя объявлять его
защищённым механизмом, который ещё не установлен в доверенную ветку.

После первоначального внедрения:

1. Добавить второго проверяющего с write-доступом и в CODEOWNERS.
2. Settings → Branches → Add branch protection rule, шаблон `main`.
3. Require a pull request before merging; минимум один approval.
4. Require review from Code Owners; Dismiss stale approvals;
   Require approval of the most recent reviewable push.
5. Require status checks to pass; Require branches to be up to date.
6. Обязательные checks: **ci-gate** и **critical-review** (GitHub Actions).
7. Require conversation resolution; Do not allow bypassing the above settings.
8. Не разрешать force push и удаление main.

Эквивалентная конфигурация подготовлена в `.ci/main-protection.json`.
Владелец может применить её из локального GitHub CLI после `gh auth login`
(учётная запись должна иметь administration-доступ):

```bash
gh api --method PUT repos/nopopjustrap/devops_auction/branches/main/protection \
  --input .ci/main-protection.json

gh api repos/nopopjustrap/devops_auction/branches/main/protection
```

В JSON указан app_id 15368 (GitHub Actions). Проверьте привязку к GitHub Actions
в интерфейсе. Для другого GitHub-инстанса идентификатор приложения отличается.
Токен CLI хранится средствами gh, не в репозитории.

`policy-check` дополнительно ловит удалённые/переименованные test_* функции
относительно base, снятие этапов и понижение порога. Это защита от типичных
ошибок, а не полный семантический анализ тестов. Намеренное ослабление assert
или изменение самого checker требует независимого ревью и защиты ветки.

## Демонстрации для защиты

Все дефектные изменения создаются в отдельных ветках от установленной ЛР5.
Их нельзя сливать в main. Корректная основная ветка остаётся без дефектов.

### Корректное изменение

В отдельной ветке добавить пояснение в README, выполнить make verify,
создать PR. Показать зелёные проверки. После согласования и слияния показать
зелёный main-run и пакет с тегом sha-<merge commit>.

### Ошибка бизнес-логики

В `app/services.py` заменить `<` на `<=` в сравнении final_price со starting_price.
Отправить отдельную ветку и создать PR. check-tests должен упасть на продаже
по стартовой цене; build, container и publish не должны выполняться;
ci-gate должен быть красным. Не удалять тест для получения зелёного результата.

### Ошибка миграции

В отдельной демонстрационной ветке внести ошибочный SQL в одну миграцию.
Показать падение check-migrations/check-tests и остановку зависимых этапов.
Изменение migrations также требует critical-review. Не переносить изменённую
историческую миграцию в main.

### Безопасный тестовый секрет

Создать только демонстрационный, неработающий маркер:

```bash
python3 - <<'PY'
from pathlib import Path
Path('demo-secret.txt').write_text('LR5_DEMO_SECRET_' + 'A1B2C3D4' * 4 + '\n')
PY
git add demo-secret.txt
git commit -m "test: demonstrate secret scanner rejection"
git push -u origin HEAD
```

Создать PR. check-secrets должен упасть по правилу lr5-demonstration-secret;
значение в отчёте редактируется. Встроенные стандартные правила Gitleaks тоже
включены: учебный маркер дополняет их. Так как сканируется история, простое
удаление файла следующим коммитом не очищает дефектную ветку. Закрыть PR и
использовать новую ветку от main для следующих изменений.

### Попытки ослабления приёмки

В отдельных ветках: удалить один тест; удалить вызов security из verify;
изменить --cov-fail-under=85 на 20. Показать красный check-policy и/или tests,
critical-review без независимого approval и заблокированную кнопку слияния.
Затем вернуть изменения. Настройки защиты GitHub должны быть включены заранее.

### Отсутствие публикации

В красном run показать job publish со статусом skipped и красный ci-gate.
В PR publish пропускается также по ограничению события, поэтому одного такого
скриншота недостаточно для доказательства зависимости: показать `needs: gate`,
проверку всех needs в gate и успешный main-run с публикацией. Нельзя ради
демонстрации отправлять дефект напрямую в защищённый main.

## Почему локальные и серверные проверки совпадают

В CI вызываются цели Makefile, используемые make verify локально. Правила и
пороги не копируются в отдельные команды pytest в YAML. Это снижает риск,
что локально проверена одна логика, а сервер принял другую. Однако серверный
запуск независим от сообщения автора «у меня всё прошло»: runner получает
код из Git, создаёт окружение и заново выполняет проверки. Защищённая ветка
делает их обязательными для слияния, зависимости pipeline — для публикации.

## Исправление, найденное при внедрении CI

Первый pip-audit выявил CVE-2025-71176 в pytest 8.4.2: небезопасное обращение
с временными каталогами. pytest обновлён до 9.0.3 в requirements-dev.txt
и requirements.lock. Повторный аудит завершился без известных уязвимостей.
Исключение для уязвимости не добавлялось.

Источники:

- [GitHub Advisory: CVE-2025-71176](https://github.com/advisories/GHSA-6w46-j5rx-g56g).
- [GitHub Actions: публикация Docker-образов](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images).
- [Защищённые ветки](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
- [CODEOWNERS](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners).

Первый контейнер на Debian 12 был заблокирован Trivy из-за HIGH/CRITICAL
в системных пакетах. База заменена на официальный Python 3.12.15 / Alpine 3.24
с обновлением пакетов. Порог сканера и проверка неисправленных уязвимостей
сохранены; окончательный результат фиксируется по повторному CI-прогону.
