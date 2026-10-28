# voice-dictate

Локальне push-to-talk диктування для macOS (Apple Silicon). Тримаєш клавішу, говориш, відпускаєш — текст розпізнається локально (Whisper через MLX) і вставляється в поле, де стоїть курсор. Інтернет потрібен лише для першого завантаження моделі.

## Встановлення

Потрібен Python **3.11–3.12** (системний `/usr/bin/python3` 3.9 не підходить: немає готових wheel-ів для pyobjc/mlx). Найпростіше через [uv](https://docs.astral.sh/uv/):

```bash
brew install uv
cd voice-dictate
rm -rf .venv
uv venv -p 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
```

## Застосунок у menu bar (Wisper.app)

```bash
source .venv/bin/activate
uv pip install -r requirements.txt   # додає rumps
./build_app.sh                        # створює /Applications/Wisper.app
open /Applications/Wisper.app
```

У верхньому барі з'явиться іконка: ⏳ модель вантажиться → 🎙 готово → 🔴 запис → 💭 розпізнавання.
У меню: мова, модель (Turbo / Large), клавіша, авто-Enter, посимвольний друк, звуки, автозапуск при вході, лог.
Налаштування зберігаються в `~/Library/Application Support/Wisper/settings.json`, лог — `~/Library/Logs/Wisper.log`.

**Дозволи:** застосунок — це нова «програма» для macOS, тож дозволи треба дати саме **Wisper** (не терміналу): Microphone (спитає сам), Accessibility та Input Monitoring. Пункт меню «⚠️ Немає дозволу Accessibility» відкриє потрібну сторінку налаштувань. Після видачі — Вийти з Wisper і запустити знову.

`Wisper.app` — лише лаунчер: маленький нативний бінарник (компілюється `clang` під час `build_app.sh`, потрібні Xcode Command Line Tools), який вбудовує Python з `.venv` і запускає `menubar.py` з цієї папки. Тому macOS бачить процес як **Wisper**, а не python. Якщо перенесеш папку — перезапусти `build_app.sh`. Після змін у коді перезбирати не треба, достатньо перезапустити Wisper.

## Поділитися застосунком (автономна збірка)

```bash
./package_app.sh      # -> dist/Wisper.app і dist/Wisper.zip
```

`Wisper.zip` (~200–300 MB) містить усе: Python, бібліотеки й код. Надсилай цей файл. Модель (~3 GB) завантажиться під час першого запуску.

Для отримувача:
- Потрібен Mac на Apple Silicon (M1 і новіше) з macOS 13+.
- Розпакувати й перетягнути `Wisper.app` у `/Applications`.
- Застосунок не нотаризований Apple, тому при першому запуску macOS його заблокує. Тоді: System Settings → Privacy & Security → внизу «Wisper was blocked…» → **Open Anyway**. Або в терміналі: `xattr -dr com.apple.quarantine /Applications/Wisper.app`.
- Дати дозволи: Microphone, Accessibility, Input Monitoring.

## Запуск з терміналу

```bash
python dictate.py
```

Перший запуск завантажує модель `whisper-large-v3-turbo` (~1.6 GB) у `~/.cache/huggingface`.

За замовчуванням: **тримай правий Option** → говори → відпусти. Esc під час запису — скасувати.

### Дозволи macOS (обов'язково)

System Settings → Privacy & Security, додай **свій термінал** (Terminal / iTerm / Warp) у:
- **Microphone**
- **Accessibility** (щоб вставляти текст)
- **Input Monitoring** (щоб ловити хоткей)

Після видачі дозволів перезапусти термінал.

## Опції

| Прапорець | Що робить |
|---|---|
| `--key alt_r` | клавіша: `alt_r`, `ctrl_r`, `cmd_r`, `shift_r`, `f13`… |
| `--lang uk,en` | дозволені мови (за замовчуванням `uk,en` — модель обирає тільки між ними). `--lang uk` — завжди українська, `--lang ""` — будь-яка мова |
| `--enter` | натиснути Enter після вставки (одразу відправка в чат) |
| `--mode type` | друкувати посимвольно замість Cmd+V |
| `--prompt "ганк, мід, джангл, Xerath"` | підказка зі словником — краще розпізнає терміни |
| `--model large` | модель: `turbo` (за замовчуванням, швидка), `large` (найточніша, краще визначає мову, ~3 GB, у 2–4 рази повільніша), `medium`, `small`, або будь-який MLX-репозиторій з Hugging Face |
| `--no-sounds` | без звуків старт/стоп |

## Для League of Legends

```bash
python dictate.py --enter
```

Enter (відкрити чат) → тримай правий Option, говори → відпусти → текст вставиться і відправиться.

Якщо в грі Cmd+V не спрацює — спробуй `--mode type`.
