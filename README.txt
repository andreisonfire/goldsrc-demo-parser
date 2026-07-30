GoldSrc Demo Parser (GSDP) v2.0
By THUNDERGOD
================================================================

Инструмент для извлечения хайлайтов (мультикиллов) из демо-файлов
Counter-Strike 1.6. Работает локально, Python ставить не нужно.


КАК ПОЛЬЗОВАТЬСЯ
----------------
1. Дабл-клик на gsdp.exe (или run_ui.bat — то же самое)
2. Откроется окно приложения
3. Кидаешь .dem файлы в drag-drop зону (можно несколько сразу)
4. Видишь хайлайты в виде таблицы
5. Кликни ⭐ напротив тех, что хочешь оставить
6. Нажми "Export" → выбирай CSV или TXT
   Галочка "favourites only" выгрузит только отмеченные ⭐
7. После сохранения откроется проводник с выделенным файлом

Что нового в v2.0: приложение теперь запускается как настоящая
десктоп-программа, а не через браузер. Никакого localhost:8765
и подтверждений файрвола.

Также исправлена привязка киллов к раундам — раньше в редких
случаях киллы из разных раундов склеивались в один "хайлайт"
на 11+ киллов (и он молча прятался), а фраг, которым закрывали
раунд, мог уехать в следующий раунд и сломать 4k. Подробности
в README.md на GitHub.


ЧТО ОН УМЕЕТ
------------
* Парсит и POV (запись от лица игрока), и HLTV-демки CS 1.6
* Автоматически определяет тип демки
* В POV-демках выгружает только хайлайты записывающего игрока,
  остальные киллы игнорируются (как и должно быть)
* Восстанавливает структуру матча в HLTV-демках и учитывает только
  живую игру. Стороны находятся по пистолетным раундам (в начале
  стороны у всех $800, то есть только пистолеты, нож и гранаты),
  первая сторона это ровно 15 раундов, вторая идёт до 16-го раунда
  по счёту, при 15:15 начинаются овертаймы по 3 раунда на сторону.
  Отсекается разминка, фальстарты, пауза между сторонами и всё,
  что после конца матча. Если структура не стандартная — например
  записана только одна сторона — фильтр отключается и показывает
  всё, чтобы не потерять живой хайлайт.
  В POV-демках фильтр не применяется, т.к. запись может начаться
  с любого раунда.
* Чинит сломанные HLTV-демки с битой directory table
* Имена игроков берутся на момент килла, а не последнее имя
  в демке. Если игрок переименовался в "gg" / "kk" в конце матча —
  его хайлайты в начале остаются под нормальным ником.
* Тимкиллы исключаются из хайлайтов. Если игрок убил 4 врагов
  и 1 тиммейта — будет показано как 4k, а не ace. Команды
  определяются по графу киллов: в матче почти все киллы идут
  между командами, поэтому верное разделение это то, при котором
  внутри команд киллов меньше всего. Поле model в userinfo для
  этого ненадёжно — некоторые серверы не обновляют его при смене
  сторон, и один такой игрок ломает фильтр в обе стороны.

* Находит хайлайты по правилам:
    - ace (5 киллов за раунд) и 4k (4 килла за раунд)
    - triple with awp / triple with scout (3 килла одним выстрелом
      из снайперки)
    - double with awp / double with scout (2 килла одним выстрелом)
    - fast 3hs with deagle/ak47/m4a1 (3 хедшота за 5 секунд)

* Для 4k и ace показывает аннотации с подкатегориями:
    - "4k with awp, deagle (incl. triple with awp)"
    - "ace with awp (incl. 2x double with awp)"
    - "ace with awp, deagle, ak (incl. double with awp, fast 3hs)"

* Время киллов соответствует времени в игровом плеере демок
  (без необходимости вычитать офсет)


СЕТЬ И ФАЙРВОЛ
--------------
Начиная с v2.0 программа не поднимает веб-сервер, поэтому окна
файрвола больше нет. Всё считается локально, в сеть ничего
не уходит.


АНТИВИРУС
---------
Некоторые антивирусы могут ругаться на .exe файлы — это известная
ложная срабатываемость PyInstaller. Вирусов нет, это обычный
Python-скрипт упакованный в исполняемый файл. Можно добавить
в исключения или собрать самому из исходников через build_exe.bat.


ИСХОДНИКИ И ПОДРОБНОСТИ
-----------------------
GitHub: https://github.com/andreisonfire/goldsrc-demo-parser

На странице репозитория есть полная документация (README.md) с
техническими деталями, описанием формата CSV и историей версий.


ПРОБЛЕМЫ
--------
Если что-то не работает — открой issue на GitHub:
https://github.com/andreisonfire/goldsrc-demo-parser/issues

Или запусти из cmd чтобы увидеть ошибку:

    cd path\to\folder
    gsdp.exe


================================================================
                        ENGLISH
================================================================

GoldSrc Demo Parser (GSDP) v2.0
By THUNDERGOD

A tool for pulling highlights (multikills) out of Counter-Strike 1.6
demo files. Runs locally, no Python installation needed.


HOW TO USE
----------
1. Double-click gsdp.exe (or run_ui.bat — same thing)
2. An app window opens
3. Drop .dem files onto the drag-and-drop zone (several at once is fine)
4. Highlights appear as a table
5. Click the star next to the ones you want to keep
6. Hit "Export" and pick CSV or TXT
   The "favourites only" tick exports just the starred rows
7. Once saved, your file manager opens with the file selected


WHAT'S NEW IN v2.0
------------------
The app now runs as a real desktop program instead of going through a
browser. No localhost:8765, no firewall prompt.

Round bucketing was also fixed. Previously, in rare cases, kills from
different rounds got glued into a single "highlight" of 11+ kills (which
was then silently hidden), and the frag that ended a round could drift
into the next one and break a 4k. Full details in README.md on GitHub.


WHAT IT DOES
------------
* Parses both POV (player's own recording) and HLTV demos of CS 1.6
* Detects the demo type automatically
* In POV demos it only reports the recording player's highlights and
  ignores everyone else's kills, as it should
* Reconstructs the match structure in HLTV demos and keeps only live
  play. Halves are located by their pistol rounds — everyone starts a
  half on $800, so that round is pistols, knife and grenades only. The
  first half is always exactly 15 rounds; the second runs until a team
  reaches 16; at 15:15 overtime begins, 3 rounds per half. Warm-up,
  false starts, the break between halves and everything after the match
  ends are all excluded. When the structure isn't standard — only one
  side recorded, for instance — filtering switches off and everything is
  shown, so a real highlight is never lost.
  POV demos are never filtered, since a recording can start on any round.
* Repairs broken HLTV demos with a corrupt directory table
* Player names are taken as of the moment of the kill, not the last name
  in the demo. If someone renames themselves to "gg" at the end of a
  match, their earlier highlights keep their normal nickname.
* Team-kills are excluded from highlights. Kill 4 enemies and 1 teammate
  and it reads as a 4k, not an ace. Teams come from the kill graph: in a
  real match almost every kill crosses team lines, so the correct split
  is the one leaving the fewest kills inside a team. The userinfo `model`
  field is unreliable for this — some servers never refresh it after a
  side switch, and one such player breaks the filter in both directions.

* Highlight rules:
    - ace (5 kills in a round) and 4k (4 kills in a round)
    - triple with awp / triple with scout (3 kills from one sniper shot)
    - double with awp / double with scout (2 kills from one shot)
    - fast 3hs with deagle/ak47/m4a1 (3 headshots within 5 seconds)

* 4k and ace get sub-category annotations:
    - "4k with awp, deagle (incl. triple with awp)"
    - "ace with awp (incl. 2x double with awp)"
    - "ace with awp, deagle, ak (incl. double with awp, fast 3hs)"


NETWORK AND FIREWALL
--------------------
Since v2.0 the program doesn't start a web server, so there's no
firewall prompt any more. Everything is computed locally and nothing
leaves your machine.


ANTIVIRUS
---------
Some antivirus products complain about the .exe — that's a known
PyInstaller false positive. There's no malware; it's an ordinary Python
script packed into an executable. Add it to your exclusions, or build it
yourself from source with build_exe.bat.


SOURCE AND DETAILS
------------------
GitHub: https://github.com/andreisonfire/goldsrc-demo-parser

The repository page has the full documentation (README.md) with technical
details, the CSV format and version history.


PROBLEMS
--------
If something doesn't work, open an issue on GitHub:
https://github.com/andreisonfire/goldsrc-demo-parser/issues

Or run it from cmd to see the error:

    cd path\to\folder
    gsdp.exe
