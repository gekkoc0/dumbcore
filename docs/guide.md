# С чего начать: бэкап → правка → проверка → сборка

> ⚠️ **Запись на телефон изменённых файлов пока не проверялась.** Всё ниже до шага 5 безопасно (только чтение
> и работа с файлами на компьютере). Шаг 6 — на свой риск, только со своим бэкапом.

## 0. Что понадобится

- Python 3 и `python3 -m pip install -r requirements.txt`.
- Для бэкапа: `spd_dump` (собирается скриптом) и USB-кабель с передачей данных — [backup.md](backup.md).
- Для пересборки `.pac`: официальный `.pac` **той же версии ПО**, что на телефоне.

## 1. Снять бэкап

[backup.md](backup.md). Это обязательно: бэкап — единственный способ вернуть всё как было, и из него же берутся
файлы для правки. В бэкапе IMEI, серийный номер и калибровки — никуда его не выкладывайте.

## 2. Разобраться, что внутри

```sh
python3 -I tools/dumbcore.py inspect backup/…/mmi_res.bin        # модули, типы, языки
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

## 5. Собрать `.pac`

```sh
python3 -I tools/dumbcore.py pac official.pac my.pac MMIRes=new.bin
python3 -I tools/pacwrite.py my.pac --verify      # проверить контрольные суммы
```

Меняются только неподписанные разделы (ресурсы, NV, APN…); образы кода с подписью сборщик трогать отказывается.

## 6. Ставить на телефон (на свой риск)

Прошивальщики и их настройки — в [links.md](links.md) (4PDA). Перед этим прочтите про ревизии телефона:
у части аппаратов второй ревизии старые загрузчики дают ошибку `UB1132`. Вернуть стоковое состояние можно
только из своего бэкапа или официального `.pac` той же версии.
