# TODO

## Bugs (знайдено при код-рев'ю 2026-07-07)

- [x] **`eveus.set_ai_mode` зламаний як задокументований** — `services.yaml` пропонує опції `Off`, `Voltage`, `Tesla (auto)`, `Power`, але сервіс проксює їх у `select.select_option`, а у селекта опції — lowercase-ключі `off`, `voltage`, `tesla_auto`, `power` (`select.py`, `options` = ключі `charger.ai_modes`). Виклик з "Off" падає (option not in options). Фікс: привести опції в `services.yaml` до lowercase-ключів або мапити label→key у хендлері сервісу в `__init__.py`. Заодно: у `set_current` захардкожено `min: 7`, а у V2 мінімум 6A.
- [x] **Re-auth flow — мертвий код** — `config_flow.py` має `async_step_reauth`, але ніхто не кидає `ConfigEntryAuthFailed`: 401 від зарядки → `ClientResponseError` → загальний `except` у `coordinator.py` → repair issue. HA ніколи не покаже форму переавторизації. Фікс: у `coordinator._async_update_data` ловити `aiohttp.ClientResponseError` зі `status == 401` і кидати `ConfigEntryAuthFailed`. У TODO нижче пункт позначений виконаним — фактично не працює.
- [x] **Diagnostics зливає серійники** — `diagnostics.py` редагує лише `config`, а `coordinator_data` віддає як є; у V2-відповіді є `serialNum`, `serialNumCPU` (підтверджено по mockData). Люди прикладають диагностику до GitHub issues. Фікс: пропустити `coordinator_data` через `async_redact_data` з ключами `serialNum`, `serialNumCPU`, MAC/SSID якщо є. Пункт «repairs/diagnostics» нижче заявляє редакцію serial/MAC — зроблено тільки для пароля/IP у config.
- [x] **Витік aiohttp-сесії у config flow** — `config_flow._test_connection`: якщо `get_status()` кидає виняток, `charger.close()` не викликається → незакрита `ClientSession` на кожну невдалу спробу підключення (warning у логах HA). Фікс: `try/finally`. Ширше: за гайдлайнами HA краще використовувати спільну `async_get_clientsession(hass)` замість власної сесії у `charger/base.py`.
- [x] **Prefix не перевіряється на унікальність** — unique_id сутностей = `{prefix}_{name}` (усі платформи). Дві зарядки з однаковим prefix → сутності другої мовчки не зареєструються через дублікати unique_id. Фікс: у config flow перевіряти prefix проти існуючих entries і повертати помилку `prefix_taken`.
- [x] **Сервіси не знімаються при вивантаженні** — `set_current`/`set_ai_mode` реєструються у `async_setup_entry`: при видаленні інтеграції лишаються висіти, при двох entries реєструються двічі (друга мовчки перезаписує першу). Фікс: реєструвати один раз на домен (в `async_setup`) або знімати в `async_unload_entry`, коли entry останній.
- [x] **V1 select може отримати невалідний current_option** — `AI_MODE_MAP` у `charger/v1.py` мапить також `tesla_auto`/`power`, але options селекта для V1 — лише `off`/`voltage` (`ai_modes`). Якщо прошивка поверне aiStatus=2/3, HA логуватиме помилку стану. Фікс: повертати `None`, якщо значення не в options, або розширити `ai_modes` V1.
- [x] **Switch не оптимістичний** — після toggle стан оновиться лише з наступним poll'ом; у UI перемикач може «відстрибувати» на кілька секунд. Косметика. Фікс: виставляти очікуваний стан локально до підтвердження від координатора.
- [x] **`Dict[str, Any]` без імпорту в `charger/base.py`** (сигнатура `get_status`) — не падає лише завдяки `from __future__ import annotations`; неконсистентно з рештою файлу. Фікс: замінити на `dict`.
- [x] **Тест-інфраструктура рудиментарна** — `tests/test_init.py` перевіряє `async_setup_component` для config-flow-only інтеграції: проходить тривіально, нічого не покриває. Або прибрати, або написати справжні тести на `transform_data` (v1/v2) з mockData як фікстурами.
- [x] **`services.yaml` російською** — вибивається з курсу на EN/UA-локалізацію; описи сервісів не перекладаються через translations у цій схемі. Перекласти на EN.

## High priority

- [x] `state_class=MEASUREMENT` на сенсорах — voltage, current, power, температури його не мають; без нього HA не пише history statistics і Energy Dashboard не працює коректно
- [x] `sessionEnergy` state_class — має бути `TOTAL` з `last_reset` при зміні сесії, інакше HA неправильно підсумовує у статистиці
- [x] Прибрати `newsessiontime` — надлишковий сенсор; `sessionTime` у секундах з `device_class=DURATION` достатньо, HA форматує сам
- [x] `systemTime` як `datetime` — зараз рядок "DD.MM.YYYY HH:MM:SS", має бути `device_class=TIMESTAMP` з об'єктом datetime
- [x] `translations/` директорія — рядки станів захардкоджені англійською; без strings.json інтеграція не пройде HACS quality checks вище базового рівня
- [x] `async_migrate_entry()` — при зміні схеми конфіга старі записи зламаються; потрібна функція міграції

## Medium priority

- [x] Re-auth flow — переавторизація без перестворення інтеграції (стандарт HA для інтеграцій з паролем)
- [x] Dynamic polling — активна зарядка: 30s, очікування: 60s, offline: 60s (зараз фіксований інтервал з options flow)
- [x] diagnostics.py — стандартна HA diagnostics panel з редакцією чутливих полів (пароль, IP, serial, MAC)
- [x] repairs.py — HA Repairs framework: реєстрація issue при невалідній конфігурації
- [x] Safety debouncing — 14 станів безпеки з debounce (N послідовних читань перед алертом); firmware faults обходять debounce одразу
- [ ] Локалізація UA / EN / RU — додати `translation_key` на всі сутності, `_attr_has_entity_name = True`, перенести імена сутностей і значення станів з Python-коду до `strings.json` + `translations/uk.json` + `translations/ru.json`
- [x] +toNextRelease: `sessionTime` — додати `state_class=MEASUREMENT`; без нього HA не пише довгострокову статистику для цього сенсора (виявлено: вже реалізовано раніше, код у `sensor.py` містить `state_class=MEASUREMENT`)
- [x] `systemTime` спамить recorder — TIMESTAMP-сенсор змінюється кожен poll → ~1500–3000 рядків recorder на день. ABovsh у v4.14 через це взагалі випиляв clock-сенсор і замінив на "time drift" (на скільки секунд годинник зарядки відстає від HA; пишеться лише при реальному дрейфі >30s, ціла година дрейфу = підказка про неправильний Time Zone). Розглянути: drift-сенсор замість/поруч із systemTime, або хоча б викинути systemTime з recorder

## Low-Medium priority

- [ ] Binary sensor "Is Charging" — `state == "Charging"`, потрібен для автоматизацій "коли зарядка почалася/закінчилася"
- [ ] Binary sensor "Has Error" — `state == "Error"`, для алертів
- [ ] Binary sensor "Is Limited" — `subState != "No Limits"` за відсутності помилки; сигналізує що зарядка йде але обмежена
- [ ] Binary sensor "Connectivity" — `is_on = coordinator.last_update_success`; стандартний HA спосіб показувати онлайн/офлайн статус пристрою
- [x] +toNextRelease: Event `eveus_session_ended` — стріляти при переході Charging/Paused → Standby/Complete з даними session_energy, session_time. Шпаргалка — ABovsh v4.18: у payload session summary (energy/duration/reason), НЕ реплеїти переходи, що сталися поки зарядка/HA були офлайн; device triggers у UI автоматизацій — щоб тригер обирався з дропдауна без YAML
- [x] +toNextRelease: Event `eveus_charging_started` — симетрія до session_ended для автоматизацій
- [x] +toNextRelease: Last Session сенсори — прошивка стирає лічильники сесії при старті наступної, тож фінальні цифри минулої сесії зникають щойно встромив кабель. Сенсори-фіксатори (energy, duration; RestoreEntity) захоплюють значення в момент завершення сесії і тримають до наступного завершення. ABovsh додав у v4.18 — підтверджений попит; мотивація для нас: тригер для сповіщень про завершення сесії (енергія/вартість/тривалість) без polling, корисно і для майбутньої логіки адаптивного струму (реакція на зміну стану)

## Low priority

- [ ] Session cost sensor — вартість сесії в UAH; реалізувати через Options Flow: додати поле "тариф (UAH/кВт·год)", тоді вартість = sessionEnergy × тариф, окремий сенсор не потрібен
- [x] Стабільний ідентифікатор пристрою замість IP — IP змінюється при зміні DHCP, HA дублює пристрій. Серійник НЕ підходить: у V1 API поля `serialNum` немає взагалі (підтверджено mockData Bolt), а старі V2-прошивки повертають у ньому сміттєві байти (ABovsh v4.18, бачено на GRM070A-R3.01.8). Рішення: `entry_id` як `identifiers` — стабільний і однаковий для обох моделей + reconfigure flow для зміни IP
- [ ] Auto sync time при старті (V2) — зараз лише по кнопці; при `async_setup_entry` автоматично викликати `sync_time` щоб годинник зарядки не збивався
- [ ] SOC system — розрахунок стану батареї EV (SOC%, час до цілі, вартість до цілі). Сумнівна фіча: дані або вводить юзер, або непрямі розрахунки. Реалізація: ABovsh/eveus (ev_sensors.py).
- [ ] 40A/48A model support — зараз max 32A, додати моделі 40A (EVEUS Pro, hardware max 40A — ABovsh додав у v4.16) та 48A до config flow
- [ ] Ліміти Time/Energy/Cost (V2-only) — станція вже віддає ці поля, ми їх просто не реалізували: `timeLimitS`/`energyLimitS`/`moneyLimitS` (switch увімкнення), `moneyLimit` (number, значення), `suspendLimits` (master switch — вимкнути всі). Підтверджено по власному mockData VW: поля вже присутні в `/main`, а `V2_SUBSTATE_LIMIT_MAP` у `charger/v2.py` вже розпізнає `time_limit`/`energy_limit`/`cost_limit` як substate — тобто ми вже бачимо, що лімІт спрацював, але не даємо його налаштувати. Це НЕ нова прошивка/API — поля лежать у capabilities-непокритому вигляді щонайменше з 12.06.2026. У V1 (Bolt) цих полів немає — реалізовувати тільки для V2.

## Backlog / дослідити

- [ ] **Live API capture (коли будемо в одній мережі із зарядкою)** — зняти живі відповіді всіх read-only ендпоінтів (локальний скрипт-снімалка лежить поза гітом, у `.claude/tools/`). Джерело правди для очікуваного контракту — API-репо [eveus-api-doc](https://github.com/Soundistor/eveus-api-doc). Закрити: наявність `pemErr`, `RSSI` у `/main`, `typeEvse` vs `evseType`, невідомі ключі (`rfData`/`SNflag`/`tmp`/`minV`), структуру `/debug` та `/init`, ненульові фази на 3-фазнику. Після зняття — оновити публічний репо `eveus-api-doc` (`API.md`, `openapi.yaml`).
- [ ] **Read-only сенсори з розбору прошивки (блок 🔴)** — станція віддає в `/main`, ми ігноруємо; безпечні (не пишуть у пристрій): `pilot` (Control Pilot / стан підключення), `pemErr` (помилка землі/PEM — спершу підтвердити на живому), `leakValueH` (поріг УЗО), `sessionMoney` (вартість поточної сесії — на відміну від обчислюваного через тариф, це власне значення пристрою), `IEM1_money`/`IEM2_money` (гроші по двох лічильниках), `activeTarif`. Однофазні — `curMeas2/3`, `voltMeas2/3` НЕ додавати (завжди 0, див. [[single-phase-only]]). Деталі й одиниці — API-репо [eveus-api-doc](https://github.com/Soundistor/eveus-api-doc) (`API.md`).
- [ ] **Діагностичні/ідентифікаційні сенсори** — `verFWMain`/`verFWWifi`/`verFWStatus`, `fwCRC32`, `stationId` для `device_info` та діагностики; OCPP-статус (`ocppEnabled`/`ocppconnected`/`ocppOfflineAva`) як `binary_sensor`. Читаємо з `/main`, зараз не використовуємо.
- [ ] IEM1 / IEM2 призначення — з'ясувати що саме рахують два лічильники; якщо IEM1=мережа, IEM2=сонце — можливий сенсор "частка сонячної енергії в сесії"
- [ ] Адаптивне керування струмом зарядки — НЕ одна voltage-aware фіча, а механізм під кілька сценаріїв з різними тригерами і різною логікою:
    - **Мережа:** тригер — зовнішній сенсор напруги на вводі в дім (вбудований `aiMode=voltage` марний: розетка за стабілізатором, зарядка завжди бачить ~230В). Низька напруга → скид струму, висока → плавний підйом +1A із затримкою.
    - **СЕС / гібридний інвертор:** керувати дозволеним струмом від роботи сонячної станції. Тригер — витрата з АКБ інвертора / достатність генерації. Не вистачає сонця, пішов розряд батареї → скид струму (можливо пауза). Якщо ~хвилину немає витрати з АКБ → плавний підйом, щоб вибрати максимум генерації не чіпаючи батарею. З настанням сезону стане затребуваним; потенційно цікаво не лише нам — кандидат на «фічу з коробки».
  - **Мотивація в інтеграції:** два зарядні пристрої, дублювати/правити автоматизації під кожен боляче.
  - **Напрямок (схиляємось, не фіналізовано):** інтеграція дає МЕХАНІЗМ — стейтлес-сервіси `eveus.ramp_current` (крок до стелі, затиснутий стелею і `min_current`) та `eveus.drop_current` (миттєво до мінімуму); паузу беремо з наявного switch. ПОЛІТИКА (тригери, умови, кеданс) лишається в HA-автоматизаціях, таргет — конкретна зарядка. Повний вбудований рушій правил відкинуто як дублювання HA-автоматизацій.
  - **Стеля:** сутність `number.*_eveus_max_charging_current` (RestoreEntity, зберігається локально в HA, на пристрій не пишеться). НЕ жорсткий затиск — ручний `number.current_set` (max 32A) може бути вищим. Стеля = максимум, до якого піднімає адаптивне відновлення: після скиду підйом дійде лише до стелі, «пам'ять» про високе ручне значення втрачається. До реалізації живе як `input_number.*_charge_max_limit`.
  - **План фазами:** (1) сутність-стеля — низький ризик, цінна сама по собі; (2) сервіси `ramp_current`/`drop_current`; (3) опц. тонкий вбудований voltage/СЕС-контролер «з коробки».
- [x] +toNextRelease: Device name з prefix — зараз `DeviceInfo.name = f"Eveus {IP}"`, тому friendly_name сутностей у HA = "Eveus [IP] Current". Замінити на prefix (напр. "eveus_home" → "Eveus Home"), тоді імена будуть "Eveus Home Current". Потрібно оновити всі файли з DeviceInfo: sensor.py, binary_sensor.py, switch.py, number.py, select.py, button.py. Ризик знято: з 0.4.0 identity пристрою тримається на entry_id, ім'я оновлюється на місці (якщо юзер перейменував пристрій вручну — його ім'я має пріоритет, це коректно).
