# Сторонние библиотеки в коде прошивки

Опознаны по строкам из `work/ghidra/kernel_funcs.jsonl` + `user_funcs.jsonl` (массивы `str` у каждой функции —
это отладочные строки и пути к `.c`-файлам) и по сырым образам `EXEC_KERNEL_IMAGE.bin` / `EXEC_USER_IMAGE.bin`
(поиск ASCII-строк версий, не попавших в функции). База — 11.00.17.00 HK. Статус «измерено» — строка/путь найден
в образе; «оценка» — вывод из косвенных признаков.

## Сводка

| Библиотека | Версия | Статус версии | Где | Назначение |
|---|---|---|---|---|
| **zlib** | **1.2.11** | измерено (строка) | USER | gzip в браузере (`BRWUtil_DecodeGzip`) |
| **libpng** | **1.2.7** | измерено (строка) | KERNEL | декодирование PNG |
| **Expat** | **2.0.1** | измерено (строка) | USER | разбор XML (WAP/XCAP) |
| **Opera Mini** | **4.4** (build 34891) | измерено (строка) | USER | браузер Opera Mini |
| **mbedTLS** | 2.0.6 | оценка (папка `V206`, префикс `[mbedtls206]`) | USER | TLS в «socket ssl» |
| **MatrixSSL** (+ MatrixWTLS) | **3.7.2** (3.7.2b-open) | оценка (файлы `pstm_mul_comba.c`/`pstm_sqr_comba.c` из `matrixssl-3-7-2b-open`) | USER (DAPS) | TLS/WTLS стека WAP |
| **libcss** (NetSurf) | 0.6–0.9 | оценка (файлы `select/computed.c`, `select/propset.h`) | USER (PARSER) | CSS-движок браузера |
| **libparserutils / libwapcaplet** (NetSurf) | ~0.x | оценка (спутники libcss) | USER (PARSER) | спутники libcss |
| **nghttp2** | ≈1.46 | оценка (строка `NGHTTP2_DATA_FLAG_NO_COPY requires send_data_callback set` verbatim из v1.46.0) | USER (DAPS) | HTTP/2 клиент |
| **Brotli** (Google) | — | не определена | USER | декомпрессия (`frdec`) |
| **FreeType** | — | только автохинтер (порт) | USER (SPML) | хинтинг шрифтов |
| **JPEG-кодек** | свой (Unisoc) | не libjpeg | KERNEL | JPEG/SJPG-обои |
| **T9 (Nuance)** | T9AW V07.04.04.01 | измерено (строка) | данные | словари T9 (закрытый формат) |

## Подробности и доказательства

### zlib 1.2.11 — измерено
- Строка ` inflate 1.2.11 Copyright 1995-2017 Mark Adler ` (дословно из `inflate.c` zlib) — в `EXEC_USER_IMAGE.bin`.
- Исходники с именами zlib: `img_gzip_inflate.c`, `img_gzip_deflate.c`, `img_gzip_trees.c` (классический файл zlib),
  `img_gzip_gzip.c`, `img_gzip_zip.c`, `img_gzip_unpack.c`.
- Используется в браузере: `BRWUtil_DecodeGzip`, `IMGGZIP_Decode`. zlib 1.2.11 — релиз 2017 г.

### libpng 1.2.7 — измерено
- Строка ` libpng version 1.2.7 - September 12, 2004 ` и `(header)` — дословно из `png.c`/`png.h` libpng, в `EXEC_KERNEL_IMAGE.bin`.
- Файлы `png.c`, `pngmem.c` (имя из libpng), `png_decode.c`, `png_app.c`, `png_app_ctrl.c`.
- libpng 1.2.7 — релиз 2004 г. (очень старая ветка 1.2).

### Expat 2.0.1 — измерено
- Строка `expat_2.0.1` и `requested feature requires XML_DTD support in Expat` (дословная ошибка Expat) — в `EXEC_USER_IMAGE.bin`.
- Файлы `xmlparse.c` (главный файл Expat), `xmlexpatif.c` (обёртка). Рядом собственный WBXML-парсер (`wbxml_parser.c`).

### Opera Mini 4.4 (build 34891) — измерено
- Строки `Native Opera Mini/4.4.34891` и `Browser Version(Opera Mini): `.
- Пути интеграции: `MS_MMI_Main/source/mmi_app/app/operamini4/OpDev*.c` (`OpDevMain.c`, `OpDevGDI.c`, `OpDevFont.c`,
  `OpDevIME.c`, `OpDevBookmarkImport.c`, `OpDevDownload.c`, `OpDevFile.c`, `OpDevKeyPenTracker.c`, `OpDevDebug.c`),
  а также `OperaMini.c`, `opera_api_adapt_platform.c`, `eramini_api_adapt_platform.c`.
- Соответствует нашему выводу `docs/formats/nv-map.md`: запись NV 646 переключает Opera Mini ↔ стоковый браузер.

### mbedTLS 2.0.6 — оценка
- Пути `Third-party/mbedtls/V206/src/ssl_cli.c`, `Third-party/mbedtls/V206/src/ssl_tls.c`.
- Отладочный префикс `[mbedtls206 ...]`, обёртка `[socket ssl]` (`mbedtls_ssl_handshake`, `mbedtls_ctr_drbg_seed`,
  `mbedtls_ssl_config_defaults`, `mbedtls version: %s`).
- Самой строки `mbed TLS x.y.z` в образе нет — версия выведена из тега `V206` (= 2.0.6) и `[mbedtls206]`. Это **оценка**.

### MatrixSSL + MatrixWTLS — 3.7.2 (3.7.2b-open), оценка
- Пути `DAPS/source/matrix_ssl/src/...`: `crypto/digest/{hmac,matrix_md5,md2,sha1,sha256,sha384,sha512}.c`,
  `crypto/keyformat/{asn1,x509}.c`, `crypto/math/pstm.c` (бигнум MatrixSSL), `crypto/pubkey/{dh,ecc,pkcs,pubkey,rsa}.c`,
  `matrixssl/{cipherSuite,prf,matrixssl}.c`, `sslwrapper/c/ssl_*.c`.
- Рядом `DAPS/source/matrix_wtls/src/wtls_*.c` — WTLS (Wireless TLS для WAP).
- Структура каталогов соответствует MatrixSSL 3.x; строки версии в образе нет. Два TLS-стека одновременно
  (MatrixSSL в WAP-стеке DAPS, mbedTLS в «socket ssl») — норма для этой платформы.
- **Версия**: в образе есть файлы `pstm_mul_comba.c`, `pstm_sqr_comba.c`, `pstm_montgomery_reduce.c` и
  `crypto/math/` — по busybox-репозиторию эти файлы «взяты почти дословно из **matrixssl-3-7-2b-open**/crypto/math/»
  (тег `MATRIXSSL-3-7-2-OPEN`). → MatrixSSL **3.7.2** (вариант `3.7.2b-open`), оценка.

### libcss / libparserutils / libwapcaplet (NetSurf) — 0.6–0.9, оценка
- Пути `PARSER/source/libcss/libcss_src/src/...`: `lex/lex.c`, `parse/{parse,language}.c`,
  `parse/properties/properties_utils.c`, `select/{computed,hash,select,select_properties,propset.h}.c`, `stylesheet.c`.
- Спутники: `PARSER/source/libcss/libparserutils_src/src/...` (charset/кодеки utf8/utf16/8859/ascii/ext8, `input/filter.c`,
  `utils/{buffer,stack,vector}.c`) и `PARSER/source/libcss/libwapcaplet_src/src/libwapcaplet.c`.
- Строки `-libcss-center`, `-libcss-left`, `-libcss-right` (CSS-ключевые слова). Это CSS-движок NetSurf (libcss),
  т.е. браузер рендерит CSS через него, а не самописным парсером.
- **Версия**: файлы `select/computed.c`, `select/propset.h`, `parse/properties/properties_utils.c` — из переписанного
  движка libcss (0.6+); спутники libparserutils+libwapcaplet отдельными библиотеками (архитектура до 2017). → 0.6–0.9, оценка.

### nghttp2 — ≈1.46, оценка
- Путь `DAPS/source/http2/src/nghttp2/nghttp2_mem.c` (файл nghttp2).
- Дословная ошибка nghttp2 `NGHTTP2_DATA_FLAG_NO_COPY requires send_data_callback set`, вызовы
  `nghttp2_session_client_new`, `nghttp2_submit_request`, `nghttp2_submit_settings`, `nghttp2_session_upgrade`.
- HTTP/2-стек `DAPS/source/http2/src/http_*.c` использует nghttp2 как клиент (ALPN `h2`).
- **Версия**: строка `NGHTTP2_DATA_FLAG_NO_COPY requires send_data_callback set` дословно из
  `nghttp2_session.c` nghttp2 (видна в v1.46.0 и соседних 1.x). → ≈1.46, оценка.

### Brotli (Google) — версия не определена
- Путь сборки `/builds/gitlab/engineers/lycoris-unisoc/lycoris-client/src/base/brotli.cpp`.
- Строки `[frdec] brotli error`, `[frdec] Brotli checksum error`, `frdec_compare_brotli_checksum`,
  `bm_iterations.brotli_benchmark_*`. Используется в `frdec` (frame decoder) — декомпрессия ресурсов/анимаций.

### FreeType — только автохинтер (не полная библиотека)
- Файлы `spml_autofit.c` (и по `docs/formats/sfon-format.md` — `spml_afhints.c`): это порт автохинтера FreeType в движок
  шрифтов SPML. Полного FreeType (ftbase/ftglyph/ftinit…) в образах **нет**, строки версии нет.
- Т.е. «FreeType» в прошивке — не библиотека целиком, а заимствованный автохинтер внутри SPML.

### JPEG — собственный кодек Unisoc, не libjpeg
- Строки «Independent JPEG Group»/`IJG` в образах нет → это не libjpeg.
- Свои файлы: `jpeg*.c` (`jpeg_algorithm`, `jpeg_head_info`, `jpegdec_{dequant,interface,malloc,vld}`,
  `jpegenc_{header,init,interface,malloc}`), `jpeg_res_decoder.c` (SJPG-обои, см. `docs/formats/sres-format.md`).

### Прочее, найденное попутно
- `T9AW V07.04.04.01` — версия движка T9 (Nuance); словари T9 в ресурсах — закрытый формат (см. `README.md`).
- `Dorado WAP-Browser/1.0.0` и UA `Nokia 3210;Dorado WAP-Browser/1.0.0` — стоковый WAP-браузер (вендор Dorado).
- `@(#)Common Core version 1.3.11 (Debug)` — версия «common core» (код Unisoc).
- В образе USER есть полные тексты лицензий: **LGPL** и **SIL Open Font License** («Font Software», «Reserved Font Name») —
  след GPL-совместимых компонентов (MatrixSSL распространяется GPL/коммерчески) и встроенных открытых шрифтов (Noto-подобные).

## Что НЕ найдено (важно, чтобы не искать зря)

- **OpenSSL** — нет; TLS закрыт MatrixSSL + mbedTLS.
- **lwIP, sqlite, cJSON** — нет (сетевой стек и хранилища собственные Unisoc).
- **libjpeg** — нет (свой JPEG-кодек).
- **Полный FreeType** — нет (только автохинтер в SPML).

## Границы адресов и пометка функций

Функции помечены по путям исходников в строках (`__FILE__`) и по именам файлов из карты модулей.
Файл `work/ghidra/thirdparty_funcs.json` = `{адрес Ghidra: библиотека}` (600 функций). Это **нижняя граница**:
помечены только «анкерные» функции (со строкой пути); соседние функции того же файла (inferred) не включены.

| Библиотека | Функций | Байт | Диапазон (Ghidra) | Образ |
|---|---|---|---|---|
| MatrixSSL (+ MatrixWTLS) | 181 | 43 322 | `0x88000180…0x88abec0e` (разбросан) | USER |
| JPEG (свой Unisoc) | 169 | 34 402 | `0x80b6118e…0x810f57fc` | KERNEL |
| libpng | 52 | 15 040 | `0x8129a81a…0x812f7430` | KERNEL |
| mbedTLS | 38 | 11 202 | `0x880cc08e…0x883079d2` | USER |
| libcss + libparserutils + libwapcaplet | 69 | 8 914 | `0x880c2712…0x88ae033e` | USER |
| zlib (gzip) | 24 | 6 748 | `0x8815d57c…0x88acc4f0` | USER |
| Expat | 45 | 4 986 | `0x880cad34…0x88a80c62` | USER |
| FreeType (автохинтер) | 17 | 4 098 | `0x882b21ae…0x882b5738` | USER |
| Opera Mini | 4 | 758 | `0x880a8434…0x880aa512` | USER |
| Brotli | 1 | 364 | `0x88a31648…0x88a317b4` | USER |

- **nghttp2 — 0 анкерных функций**: пути `DAPS/source/http2/src/nghttp2/…` в строках функций не встретились
  (сам путь найден в образе, но не как `__FILE__`-строка функции) → в карту не попал.
- Диапазоны не сплошные: код библиотек разбросан по образу (особенно MatrixSSL в стеке DAPS).

## Примечание к методу

Версии «измерено» — это дословные строки в образах (надёжно). «Оценка» (mbedTLS 2.0.6) — вывод из тега каталога
`V206`; самой строки версии в образе нет, поэтому стоит перепроверить при необходимости (сравнить с релизом mbedTLS,
где есть `ssl_cli.c`+`ssl_tls.c` и `mbedtls_ctr_drbg` — это ветка 2.0.x). Для MatrixSSL/libcss/nghttp2/Brotli версии
не зашиты вообще — при желании их можно уточнить сверкой с открытыми репозиториями по сигнатурам функций
(отдельная задача).
