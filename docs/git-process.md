# Git-процесс и история версий

## Путь функции списка лотов

Функция `GET /api/v1/auctions/{auction_id}/lots` прошла полный цикл:

1. issue с критериями готовности;
2. ветка `feature/auction-lots-list`;
3. `9426881 feat: add auction lots list endpoint`;
4. `942859c test: cover auction lots listing`;
5. `ae3b37e docs: describe auction lots list endpoint`;
6. Pull Request #2;
7. merge-коммит `ebabd6b` в `main`;
8. успешный `make verify`.

## Конфликт слияния

Две документационные ветки изменили один фрагмент README:

- `docs/readme-purpose` — коммит `06e4fbe`, Pull Request #3;
- `docs/readme-overview` — коммит `f2b3f07`, Pull Request #4.

После слияния PR #3 во второй ветке появился конфликт. Мы объединили смысл
обеих формулировок, удалили маркеры конфликта, выполнили `make verify` и
зафиксировали решение коммитом
`c7cd5c0 merge: resolve README description conflict`. PR #4 вошёл в
`main` merge-коммитом `7f227ae`.

## Версия v0.1.0

Аннотированный тег `v0.1.0` указывает на `7f227ae`. История содержит issue,
отдельные ветки, тематические коммиты, Pull Request и merge-коммиты.

```bash
git show --no-patch --decorate v0.1.0
git log --graph --oneline --decorate --all -15
```

## Изменение v0.1.1

Аутентификацию и веб-интерфейс оформляем как отдельное изменение:

- задача: добавить базовую аутентификацию и веб-интерфейс;
- ветка: `feature/auth-web-interface`;
- коммиты разделяются на серверную аутентификацию, интерфейс и документацию;
- перед отправкой и после слияния выполняется `make verify`;
- версия создаётся только после слияния Pull Request в `main`.

```bash
git switch main
git pull --ff-only
git switch -c feature/auth-web-interface

# изменения и осмысленные коммиты
make verify
git push -u origin feature/auth-web-interface

# после слияния Pull Request
git switch main
git pull --ff-only
make verify
git tag -a v0.1.1 -m "Auction Service v0.1.1"
git push origin v0.1.1
```

Тег `v0.1.0` остаётся неизменным и продолжает обозначать исходную версию.
