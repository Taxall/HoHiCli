# HoHiCli

Климатическая платформа Home Assistant для кондиционера Hisense Smart DC Inverter. Отправляет ИК-коды из встроенной таблицы через MQTT на ИК-передатчик с форматом Tuya `ir_code_to_send`.

Проверено с Home Assistant Core 2026.9.3. Для работы нужна настроенная интеграция MQTT и передатчик, принимающий указанный формат сообщений.

## Установка

Скопируйте каталог `custom_components/hohicli` в каталог `custom_components` вашей конфигурации Home Assistant или добавьте репозиторий как пользовательский в HACS. Затем добавьте в `configuration.yaml`:

```yaml
climate:
  - platform: hohicli
    name: Кондиционер
    unique_id: hisense_living_room
    ir_mqtt_topic: zigbee2mqtt/living_room_ir/set
    temperature_sensor: sensor.living_room_temperature
    humidity_sensor: sensor.living_room_humidity
```

`ir_mqtt_topic` — MQTT-тема передатчика. `temperature_sensor` и `humidity_sensor` необязательны. Для сохранения существующих сущностей оставьте прежние значения `unique_id` и `name`. После изменения YAML перезапустите Home Assistant.

Платформа поддерживает нагрев, охлаждение, выключение, скорость вентилятора и режимы boost/sleep. ИК-таблица рассчитана на 16–30 °C; Home Assistant преобразует температуру из единиц интерфейса в °C перед отправкой команды. Устройство управляется ИК-сигналами без обратной связи, поэтому состояние в Home Assistant отражает отправленные команды.

## Проверка

В окружении с установленными `homeassistant` и MQTT-зависимостью `paho-mqtt` выполните:

```bash
python -m unittest discover -s tests -v
```
