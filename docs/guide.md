# С чего начать: бэкап → правка → проверка → запись

> Шаги 1–4 безопасны: только чтение телефона и работа с файлами на компьютере. Шаг 5 меняет телефон — он проверен
> на Nokia 3210 4G с ПО 16.00 (замена иконки), но делайте его только со своим бэкапом и на свой риск.

## 0. Что понадобится

- Python 3 и `python3 -m pip install -r requirements.txt`.
- Для бэкапа: `spd_dump` (собирается скриптом) и USB-кабель с передачей данных — [backup.md](backup.md).
- Для пересборки `.pac`: официальный `.pac` **той же версии ПО**, что на телефоне.

## 1. Снять бэкап

[backup.md](backup.md). Это обязательно: бэкап — единственный способ вернуть всё как было, и из него же берутся
файлы для правки. В бэкапе IMEI, серийный номер и калибровки — никуда его не выкладывайте.

## 2. Разобраться, что внутри

```sh
python3 -I tools/dumbcore.py trim    backup/…/mmi_res.bin mmi_res.bin   # убрать заполнитель 0xFF до конца раздела
python3 -I tools/dumbcore.py inspect mmi_res.bin                 # модули, типы, языки
python3 -I tools/dumbcore.py images  backup/…/mmi_res.bin out/   # все картинки в PNG/GIF + index.html
python3 -I tools/sresedit.py backup/…/mmi_res.bin --names MAINMENU   # официальные имена картинок
python3 -I tools/sresedit.py backup/…/mmi_res.bin --find "Меню" Russian   # где лежит строка
python3 -I tools/dumbcore.py menu    backup/…/nv_fixed.bin       # главное меню
```

**Важно:** номера картинок и текстов **разные в разных сборках** (например, 76 картинок главного меню
перенумерованы между 11.00 и 16.00). Правьте ресурсы только своей версии и не переносите готовые моды между версиями.

## 3. Поменять

```sh
# иконка: PNG того же размера, по имени или по номеру МОДУЛЬ:ИНДЕКС
python3 -I tools/dumbcore.py edit mmi_res.bin new.bin IMAGE_MAINMENU_ICON_CALCULATOR=calc.png
# текст (все языки или один), цвет, звук
python3 -I tools/dumbcore.py edit mmi_res.bin new.bin "text:0:13@Russian=Меню!" COLOR_RES_IDLE_TIME=#FF8800
# свой шрифт для латиницы и кириллицы
python3 -I tools/dumbcore.py font mmi_res.bin new.bin MyFont.ttf
```

Обои (SJPG) заменяются картинкой того же размера, анимации SMOV — GIF с тем же размером кадра. Полный список
правок — `python3 -I tools/sresedit.py` без аргументов; формат — [formats/sres-format.md](formats/sres-format.md).

## 4. Проверить в макете

```sh
python3 -I tools/dumbcore.py mockup new.bin backup/…/nv_fixed.bin backup/…/user.bin mockup/
python3 -m http.server -d mockup 8000     # и открыть http://localhost:8000
```

Макет рисует окна сам, но все картинки, подписи и порядок меню берёт из ваших файлов. Это не эмулятор:
внешний вид окон приложений приблизительный.

## 5. Записать в телефон

```sh
export SPD=<путь к spd_dump> FDL_DIR=<папка с fdl1.bin и fdl2.bin>      # как для бэкапа
python3 -I tools/dumbcore.py write 0x90000004 new.bin
```

Скрипт покажет, что и куда пишет, попросит набрать `WRITE`, затем ждёт телефон: выключенный телефон, зажать `*`,
воткнуть кабель. Пишется **только раздел ресурсов**; после записи раздел читается обратно и сравнивается с файлом.
При «OK: read-back matches» выдерните кабель и включите телефон.

**Откат** — та же команда с исходным файлом (`trim` от бэкапа): `python3 -I tools/dumbcore.py write 0x90000004 mmi_res.bin`.
Загрузчик в ПЗУ телефона записью не испортить: режим `*` + кабель доступен всегда. На время экспериментов лучше
вынуть SIM-карту и карту памяти.

## 6. Альтернатива: собрать `.pac` (не проверялось)

```sh
python3 -I tools/dumbcore.py pac official.pac my.pac MMIRes=new.bin
python3 -I tools/pacwrite.py my.pac --verify      # проверить контрольные суммы
```

Меняются только неподписанные разделы; образы кода с подписью сборщик трогать отказывается. Прошивка такого `.pac`
официальными программами (см. [links.md](links.md)) авторами не проверялась. Перед этим прочтите про ревизии
телефона: у части аппаратов второй ревизии старые загрузчики дают ошибку `UB1132`.
