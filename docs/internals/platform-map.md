# Карта платформы Mocor (UMS9117 / S30+)

Справочник: подсистема → `.c`-файлы → ключевые функции (настоящие адреса) → связи. Собран из
`docs/internals/runtime.md`, `docs/internals/hardware.md`, карты модулей `work/ghidra/*_modmap.json` и покрытия эмулятора
(`docs/internals/platform-map.md`). Адреса ядра — настоящие; адреса USER — **настоящие** (в Ghidra-проекте на 0x200 меньше).

## Слои (снизу вверх)

```
железо (регистры)            docs/internals/hardware.md
ядро KERNEL 0x80a06000        драйверы + RTOS ThreadX + службы + стек связи
платформа MMI (USER 0x88000200) сервисы (T_*_SRV) + MMK-окна + приложения mmi*
```

## Подсистемы ядра (KERNEL)

| Подсистема | `.c`-файлы | Ключевое (адрес) |
|---|---|---|
| ОС/RTOS | `threadx_os.c`, `threadx_mem.c`, `threadx_appmem.c`, `osa_threadx_timer.c`, `os_cfg.c` | вход ядра `0x80a061f4`; тик — `TB_AP_TMR0_INT` линия 61; журнал `0x810c070e` (printf), assert `0x810bdf60`/`0x810bfc4a`; выключение `0x80a06aec` |
| Связь SCI | `sci_api.c`, `sci_log.c` | сигналы/очереди между службами (см. «Связи») |
| Драйверы платформы | `gpio_phy.c`, `spi_phy_v5.c`, `dma_hal.c`, `ldo_phy.c`, `clock_cfg.c`, `usim_drv.c`, `sim_uicc_*.c`, `simat_*.c` | GPIO `0x40280000`, PIN `0x402a0000`, PMU `0x402b0000` |
| Экран | `lcd.c`, `lcd_if_spi.c`, `tft_hal.c`, `lcdc_drv_ums9117.c`, `lcdc_app.c`, `layer_blend.c`, `ui_special_effect.c` | панель ST7789P3_YH_BOE; кадр `0x20b0eb40` (240×320 RGB565); LCDC `0x20800000`; обновление `guilcd.c InvalidateLcdRect` → `LCD_InvalidateRect` `0x80b4d7ec`; слои на входе `layer_blend.c` `0x80dc6a28` |
| Клавиатура | `kpd_phy.c`, `keypad.c` | прерывание логич. 0x24 (линия 68), регистры `0x40250000`; код клавиши → таблица раскладки ядра |
| NV | `nvitem.c`, `usernv.c` | чтение `0x80a2ef90`, запись `0x80a2f016`, длина `0x80a2ef6e`; `EFS_NvitemRead/Write` `0x81184010/20` |
| Флеш (BSD) | `nfc_drv.c`, BSD-слой | открыть раздел `0x80e07adc`, сведения `0x80e08306`, чтение `0x80e07bea`, закрыть `0x80e07b80` |
| Заряд/PMIC | `charge.c`, `adi_phy.c`, `analog_hal.c` | ADI `0x40600028` (адрес) / `0x4060002c` (данные); медиана Vbat `0x80a27e50`, сглаживание `0x80a28e64` |
| RTC/таймеры | `rtc_phy.c`, `timer_hal.c` | мс `0x4023000c`, быстрый счётчик `0x40040004` |
| Модем | `hal.c`, `drv_bb_*`, `drv_rf_*`, `mbox_phy.c` | ID чипа `0x98180000`, `hal.c` `0x80ce33da`; стек связи `0x80cc35c8` |
| Медиа/картинки | `jpeg_*.c`, `png_decode.c`, `img_proc.c`, `midi_adp.c`, `armvb_as.c`, `libmp4_opt2.c` | JPEG аппаратный `JPEG_VspOpen`; обои SJPG декодируются им |
| Файловые системы | `sfs_api.c`, `fat_*.c`, `sd_ops.c`, `block_mem.c`, `pktalloc.c` | диски C:/D: (FAT12), системный SFS |
| Отладка | `sio.c`, `diag.c`, `logsave_*.c`, `datadump.c` | UART1 `0x70100000`, кадры `7E…7E` |

## Подсистемы USER (MMI)

| Подсистема | `.c`-файлы | Ключевое |
|---|---|---|
| GUI-библиотека MMK | `mmk_window.c`, `mmk_ctrl.c`, `ctrllistbox.c`, `ctrltext.c`, `ctrlbutton.c`, `ctrlsetlist.c`, `ctrlform_layout.c`, `ctrlanim.c`, `ctrlrichtext.c`, `ctrlmenu_export.c` | окна/сообщения (`MSG_OPEN_WINDOW`, `MSG_GET_FOCUS`), контролы, меню-экспорт |
| Приложения | `mmicc_app.c` (вызовы), `mmi_pubwin.c`, `mmipb_view.c` (контакты), `mmimms_editwin.c` (SMS), `mmischedule.c` (календарь), `mmiconn_manager_wintab.c` (сеть/APN), `mmistk_win.c` (SIM-меню), `mmiap_play.c` (плеер), `mmibrowser_setting.c`, `mmiset_security.c`, `mmidc_flow.c` (счётчик) | по одному на приложение главного меню |
| Шрифты SPML | `spml_font.c`, `spml_api.c`, `spml_line.c`, `spml_run.c`, `spml_image.c`, `spml_afhints.c`, `spml_otf_*.c`, `spml_resolve_*.c` | кеши `vector/store/advance font cache`; глифы `sfon` |
| Камера | `dcamera_app.c`, `dcwg_handlewtask.c`, `dclg_handlegtask.c`, `isp_service.c` | сенсор GC032A по I2C |

## Связи (сигналы и сообщения)

| От | Кому | Через | Что |
|---|---|---|---|
| `keypad.c` (ядро) | служба `T_KPDSVR` | сигнал `0x201` (нажата) / `0x202` (отпущена) | клавиша |
| `T_KPDSVR` (цикл `0x80ba2d2a`, фильтр состояния `0x81752240` ∈ {3,4}) | клиенты службы 3 | `0x80c96378(3, 0x201/0x202, код)` (server.c) | рассылка события |
| клиент интерфейса (Ghidra `0x882c382c`) | задача 21 = `T_P_APP` | `SCI_SendSignal(сигнал типа 2, 21)` `0x810b827c` | клавиша в очередь интерфейса |
| цикл MMI (`mmi_osbridge.c`) | окно | `mmk_kbd.c` (Ghidra `0x8856c7bc`) → `MMK_DispatchMSGKbd` | клавиша → окно |
| `MMK` | приложение | сообщения окна (`MSG_OPEN_WINDOW`, `MSG_GET_FOCUS`, …) | жизненный цикл окна |
| `guilcd.c` (интерфейс) | ядро `lcd.c` | `InvalidateLcdRect` → `LCD_InvalidateRect` `0x80b4d7ec` | перерисовка |
| интерфейс (слои) | ядро `layer_blend.c` `0x80dc6a28` | описание слоя | композиция слоёв → LCDC → SPI |
| `charge.c` (ядро) | клиенты службы 5 → задача 21 | `0x80c96378(5, 0xa401, …)` → `SCI_SendSignal` | индикация заряда (в эмуляторе прореживается) |
| автомат Startup (USER) | окна мастера | `Startup,Current State/Event` → `call enter win` | первое включение |
| службы (SCI) | друг другу | `SCI_SendSignal` + очереди | межзадачная связь |

## Потоки ThreadX (59, приоритет меньше = важнее)

- 0–2: `hisr0/1/2`, `mbox_send_thread`, `System Timer Thread`
- 4–30: `T_P_CHNG_FREQ`, `RTOS_Manage`, `LTE_layer1_adx`, `Mux RECV TASK1/2`
- 58–101: `THERMAL_SRV`, калибровки GSM/TD, `T_TIMESVR`, `T_P_ODM`, `CHGMNG_SRV` (заряд), `T_KPDSVR` (клавиатура), `T_VOICE_PROCESS`
- 179–231: связь/сервисы (`T_P_LTE_OM`, `AUDIO_HAL_TASK`, `SPRD_CODEC_TASK`, `T_CM`, `T_DIAG`, `T_BT_SCHED`, `T_P_ATC`, `SCM_TASK`, `T_LCD`, `TASK_ISP_SERVICE`, `T_JPEG`, `T_IMG_DEC`, **`T_P_APP`**, FAT, `NETMGR`, DRM, SNTP)
- 247–250: `MMIPB_PB_TASK` (контакты), `T_P_IKEYBACKUP`, `CM4_LOG_Task`, `MTA Task`, `T_P_LOGSAVE`, `T_P_DRM_DH`

## Условие запуска интерфейса

Глобальная ядра `0x8175c608`: **1** — обычное включение, **3** — зарядка (выключенный телефон на зарядке).
Рабочий NV интерфейса (id ≥ 50000) — отдельное хранилище, у свежего телефона пустое → мастер первого включения.
