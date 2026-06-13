# TODO

## High priority

- [x] `state_class=MEASUREMENT` на сенсорах — voltage, current, power, температуры его не имеют; без него HA не пишет history statistics и Energy Dashboard не работает корректно
- [x] `sessionEnergy` state_class — должен быть `TOTAL` с `last_reset` при смене сессии, иначе HA неправильно суммирует в статистике
- [x] Убрать `newsessiontime` — избыточный сенсор; `sessionTime` в секундах с `device_class=DURATION` достаточно, HA форматирует сам
- [x] `systemTime` как `datetime` — сейчас строка "DD.MM.YYYY HH:MM:SS", должен быть `device_class=TIMESTAMP` с объектом datetime
- [x] `translations/` директория — строки состояний захардкожены на английском; без strings.json интеграция не пройдёт HACS quality checks выше базового уровня
- [x] `async_migrate_entry()` — при изменении схемы конфига старые записи сломаются; нужна функция миграции

## Medium priority

- [x] Re-auth flow — переавторизация без пересоздания интеграции (стандарт HA для интеграций с паролем)
- [x] Dynamic polling — активная зарядка: 30s, ожидание: 60s, offline: 60s (сейчас фиксированный интервал из options flow)
- [x] diagnostics.py — стандартный HA diagnostics panel с редакцией чувствительных полей (пароль, IP, serial, MAC)
- [x] repairs.py — HA Repairs framework: регистрация issue при невалидной конфигурации
- [x] Safety debouncing — 14 состояний безопасности с debounce (N последовательных чтений перед алертом); firmware faults обходят debounce сразу
- [ ] Локализация EN / UA / RU — добавить `translation_key` на все сущности, `_attr_has_entity_name = True`, перенести имена сущностей и значения состояний из Python-кода в `strings.json` + `translations/uk.json` + `translations/ru.json`
- [ ] `sessionTime` — добавить `state_class=MEASUREMENT`; без него HA не пишет долгосрочную статистику для этого сенсора

## Low-Medium priority

- [ ] Binary sensor "Is Charging" — `state == "Charging"`, нужен для автоматизаций "когда зарядка началась/закончилась"
- [ ] Binary sensor "Has Error" — `state == "Error"`, для алертов
- [ ] Binary sensor "Is Limited" — `subState != "No Limits"` при отсутствии ошибки; сигнализирует что зарядка идёт но ограничена
- [ ] Binary sensor "Connectivity" — `is_on = coordinator.last_update_success`; стандартный HA способ показывать онлайн/офлайн статус устройства
- [ ] Event `eveus_session_ended` — стрелять при переходе Charging/Paused → Standby/Complete с данными session_energy, session_time
- [ ] Event `eveus_charging_started` — симметрия к session_ended для автоматизаций

## Low priority

- [ ] Session cost sensor — стоимость сессии в UAH; реализовать через Options Flow: добавить поле "тариф (UAH/кВт·ч)", тогда стоимость = sessionEnergy × тариф, отдельный сенсор не нужен
- [ ] Идентификатор устройства по серийнику/MAC вместо IP — IP меняется при смене DHCP, HA дублирует устройство; взять серийник из API-ответа как `identifiers`
- [ ] Auto sync time при старте (V2) — сейчас только по кнопке; при `async_setup_entry` автоматически вызывать `sync_time` чтобы часы зарядки не уходили
- [ ] SOC system — расчёт состояния батареи EV (SOC%, время до цели, стоимость до цели). Сомнительная фича: данные либо вводит юзер, либо косвенные расчёты. Реализация: ABovsh/eveus (ev_sensors.py).
- [ ] 48A model support — сейчас max 32A, добавить модель 48A в config flow

## Backlog / исследовать

- [ ] IEM1 / IEM2 назначение — выяснить что именно считают два счётчика; если IEM1=сеть, IEM2=солнце — возможен сенсор "доля солнечной энергии в сессии"
