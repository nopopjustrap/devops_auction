# ЛР5 — фактические результаты проверки

Дата: 17.10.2026. Проверенная реализация: `efcc63ecba97458473c896098b6b3e45f081d18a`.
Основной запрос: [PR #10](https://github.com/nopopjustrap/devops_auction/pull/10).

## Успешный прогон

[GitHub Actions, run 39017775142](https://github.com/nopopjustrap/devops_auction/actions/runs/39017775142).

Успешны все обязательные этапы: policy, style, tests, migrations, backup,
security, dependencies, secrets, build, container-smoke, container-scan, ci-gate.
Публикация пропущена штатно: событие pull_request, а не push в main.
Образ собран и передан между заданиями через artifact с проверкой SHA-256;
контейнерный smoke и Trivy выполнены на сервере GitHub.

Локально после обновления pytest: 88 тестов пройдены, покрытие приложения
94,78%; Ruff/Bandit, 7 миграционных тестов, 8 backup-тестов, демонстрация
восстановления и 3 контрольные мутации прошли. Аудит зависимостей — без
известных уязвимостей. Локального Docker Engine в среде подготовки не было,
поэтому полный контейнерный цикл подтверждён серверным запуском, а не заявлен
как локально выполненный `make verify`.

## Отрицательные демонстрации

Эти PR направлены в feature/lr5-ci, помечены DEMO и draft. Их нельзя сливать.

| Сценарий | PR / запуск | Подтверждённый результат |
| --- | --- | --- |
| `<` → `<=` в бизнес-правиле цены | [PR #11](https://github.com/nopopjustrap/devops_auction/pull/11), [run](https://github.com/nopopjustrap/devops_auction/actions/runs/39017816884) | check-tests: 2 failed, 86 passed; ci-gate failure; build и publish skipped |
| Неработающий тестовый секрет | [PR #12](https://github.com/nopopjustrap/devops_auction/pull/12), [run](https://github.com/nopopjustrap/devops_auction/actions/runs/39017846073) | check-secrets failure, маркер обнаружен в истории и рабочем дереве; build и publish skipped |
| Удаление тестов, снятие security, порог 20% | [PR #13](https://github.com/nopopjustrap/devops_auction/pull/13), [run](https://github.com/nopopjustrap/devops_auction/actions/runs/39017869373) | check-policy и check-tests failure; ci-gate failure; build и publish skipped |

Значения найденных секретов скрываются в отчётах. Демонстрационный маркер не
является действительным паролем или токеном какого-либо сервиса.

## Реальные проблемы, обнаруженные при внедрении

1. pip-audit обнаружил CVE-2025-71176 в pytest 8.4.2. Обновление до 9.0.3
   устранило замечание без исключений.
2. Первый образ Python/Debian 12 содержал HIGH/CRITICAL уязвимости пакетов ОС.
   [Исходный run](https://github.com/nopopjustrap/devops_auction/actions/runs/39017550135)
   остановился на container-scan, ci-gate завершился ошибкой, publish пропущен.
   После перехода на Python 3.12.15 / Alpine 3.24 с обновлением пакетов
   Trivy прошёл с тем же порогом HIGH/CRITICAL и без ignore-unfixed.

## Что ещё не подтверждено

- Защита main на стороне GitHub ещё не активирована: коннектор не имеет
  операций изменения административных настроек. Подготовлен JSON и точные
  шаги владельцу в docs/lr5.md.
- CODEOWNERS пока содержит владельца репозитория. Для его собственных PR
  требуется второй независимый участник с write-доступом.
- critical-review.yml ещё не установлен в main/default branch; серверный
  trusted-base workflow в этих прогонах не запускался. Локальные тесты
  проверили отказ при self-approval, устаревшем approval и changes requested.
- Блокировка кнопки Merge через обязательные checks/review пока не
  продемонстрирована. Красный CI и запрет слияния — разные механизмы.
- PR #10 не слит в main. Успешная публикация в GHCR на push в main пока
  не выполнялась; путь публикации подготовлен, но фактический пакет ещё
  не подтверждён.

Для завершения ЛР нужны первоначальное принятие конфигурации, назначение
проверяющего, активация защиты main и показ успешного main-run с публикацией.
До этого нельзя считать обязательный независимый барьер слияния полностью
настроенным. Администратор, способный менять сами настройки защиты, остаётся
доверенным участником системы.
