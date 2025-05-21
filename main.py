import sqlite3
import asyncio
import logging
import os
from io import StringIO
from dotenv import load_dotenv
import pandas as pd
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Настройка логирования
logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Загрузка токена из .env
load_dotenv()
API_TOKEN = os.getenv("API_TOKEN")
if not API_TOKEN:
    logger.error("API_TOKEN не найден в .env файле")
    raise ValueError("API_TOKEN не задан в .env файле")

# Инициализация бота
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Путь к базе данных SQLite
DB_PATH = 'gym_bot.db'

# Инициализация базы данных
def init_db():
    """Инициализирует базу данных SQLite и создаёт таблицу users, если она не существует."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    bench_press REAL DEFAULT 0.0,
                    squat REAL DEFAULT 0.0,
                    deadlift REAL DEFAULT 0.0
                )
            ''')
            conn.commit()
            logger.info("База данных инициализирована")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}")
        raise

# Функции для работы с базой данных
def save_user_data(user_id: int, data: dict) -> None:
    """Сохраняет данные пользователя в базу данных."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, bench_press, squat, deadlift)
                VALUES (?, ?, ?, ?)
            ''', (
                user_id,
                data.get('bench_press', 0.0),
                data.get('squat', 0.0),
                data.get('deadlift', 0.0)
            ))
            conn.commit()
            logger.info(f"Данные пользователя {user_id} сохранены: {data}")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при сохранении данных пользователя {user_id}: {e}")
        raise

def load_user_data(user_id: int) -> dict:
    """Загружает данные пользователя из базы данных."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT bench_press, squat, deadlift FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            if result:
                return {
                    'bench_press': result[0],
                    'squat': result[1],
                    'deadlift': result[2]
                }
            return {'bench_press': 0.0, 'squat': 0.0, 'deadlift': 0.0}
    except sqlite3.Error as e:
        logger.error(f"Ошибка при загрузке данных пользователя {user_id}: {e}")
        return {'bench_press': 0.0, 'squat': 0.0, 'deadlift': 0.0}

def clear_user_data(user_id: int) -> None:
    """Очищает данные пользователя в базе данных."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
            conn.commit()
            logger.info(f"Данные пользователя {user_id} очищены")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при очистке данных пользователя {user_id}: {e}")
        raise

# Создание инлайн-клавиатуры для выбора недели
def get_week_keyboard() -> InlineKeyboardMarkup:
    """Создаёт инлайн-клавиатуру с кнопками для выбора недели (2x4)."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    row = []
    for i in range(1, 9):
        button = InlineKeyboardButton(text=f"Неделя {i}", callback_data=f"week_{i}")
        row.append(button)
        if len(row) == 2:  # 2 кнопки в строке
            keyboard.inline_keyboard.append(row)
            row = []
    if row:
        keyboard.inline_keyboard.append(row)
    return keyboard

# Определение машины состояний для ввода максимальных весов
class MaxLiftForm(StatesGroup):
    bench_press = State()
    squat = State()
    deadlift = State()

# Данные из файла в формате CSV (преобразовано из Excel)
CSV_DATA = """упражнения,интенсивность,подходы х повторения,день,неделя
жим лёжа,средняя,5х8-12,понедельник,1
тяга вертикального блока,средняя,5х8-12,понедельник,1
шраги с гантелями,легкая,3х8-12,понедельник,1
косичка,средняя,5х8-12,понедельник,1
сгибания на бицепс ez грифа,средняя,5х8-12,понедельник,1
молотки,легкая,3х8-12,понедельник,1
передняя дельта,легкая,3х12-15,понедельник,1
сгибание на предплечье,средняя,4х8-12,понедельник,1
присед со штангой,средняя,5х6-8,среда,1
классическая тяга,средняя,5х6-8,среда,1
разгибания ног в тренажере,легкая,3х8-12,среда,1
сгибания ног в тренажере,легкая,3х8-12,среда,1
махи на среднюю дельту,средняя,5х8-12,среда,1
отведения на дельты,легкая,3х8-12,среда,1
разгибание на предплечье,средняя,4х8-12,среда,1
присед со штангой,легкая,3х6-8,пятница,1
жим гантелей лёжа 30°,легкая,3х8-12,пятница,1
тяга горизонтального блока,средняя,5х8-12,пятница,1
подъем на бицепс с прямым грифом,легкая,3х12-15,пятница,1
подъем на носки в смите,легкая,3х12-15,пятница,1
сгибание на предплечье,средняя,4х8-12,пятница,1
французский жим лёжа,легкая,3х8-12,пятница,1
разгибание на предплечье,средняя,4х8-12,пятница,1
жим лёжа,тяжелая,7х8-12,понедельник,2
тяга вертикального блока,тяжелая,7х8-12,понедельник,2
шраги с гантелями,средняя,5х8-12,понедельник,2
косичка,средняя,5х8-12,понедельник,2
сгибания на бицепс ez грифа,средняя,5х8-12,понедельник,2
молотки,средняя,5х8-12,понедельник,2
передняя дельта,легкая,3х12-15,понедельник,2
сгибание на предплечье,средняя,4х8-12,понедельник,2
присед со штангой,средняя,5х6-8,среда,2
классическая тяга,тяжелая,7х6-8,среда,2
разгибания ног в тренажере,тяжелая,6х8-12,среда,2
сгибания ног в тренажере,средняя,5х8-12,среда,2
махи на среднюю дельту,легкая,3х8-12,среда,2
отведения на дельты,тяжелая,5х8-12,среда,2
разгибание на предплечье,средняя,4х8-12,среда,2
присед со штангой,легкая,3х6-8,пятница,2
жим гантелей лёжа 30°,тяжелая,7х8-12,пятница,2
тяга горизонтального блока,тяжелая,7х8-12,пятница,2
подъем на бицепс с прямым грифом,средняя,4х12-15,пятница,2
подъем на носки в смите,средняя,5х12-15,пятница,2
сгибание на предплечье,средняя,4х8-12,пятница,2
французский жим лёжа,легкая,3х8-12,пятница,2
разгибание на предплечье,средняя,4х8-12,пятница,2
жим лёжа,легкая,4х8-12,понедельник,3
тяга вертикального блока,легкая,4х8-12,понедельник,3
шраги с гантелями,тяжелая,7х8-12,понедельник,3
косичка,тяжелая,7х8-12,понедельник,3
сгибания на бицепс ez грифа,тяжелая,7х8-12,понедельник,3
молотки,средняя,5х8-12,понедельник,3
передняя дельта,тяжелая,6х12-15,понедельник,3
сгибание на предплечье,средняя,4х8-12,понедельник,3
присед со штангой,тяжелая,7х6-8,среда,3
классическая тяга,средняя,5х6-8,среда,3
разгибания ног в тренажере,средняя,4х8-12,среда,3
сгибания ног в тренажере,тяжелая,6х8-12,среда,3
махи на среднюю дельту,тяжелая,7х8-12,среда,3
отведения на дельты,средняя,5х8-12,среда,3
разгибание на предплечье,средняя,4х8-12,среда,3
присед со штангой,легкая,3х6-8,пятница,3
жим гантелей лёжа 30°,тяжелая,7х8-12,пятница,3
тяга горизонтального блока,тяжелая,7х8-12,пятница,3
подъем на бицепс с прямым грифом,средняя,4х12-15,пятница,3
подъем на носки в смите,средняя,5х8-12,пятница,3
сгибание на предплечье,средняя,4х8-12,пятница,3
французский жим лёжа,легкая,3х8-12,пятница,3
разгибание на предплечье,средняя,4х8-12,пятница,3
жим лёжа,средняя,5х8-12,понедельник,4
тяга вертикального блока,средняя,5х8-12,понедельник,4
шраги с гантелями,тяжелая,7х8-12,понедельник,4
косичка,средняя,5х8-12,понедельник,4
сгибания на бицепс ez грифа,средняя,5х8-12,понедельник,4
молотки,тяжелая,6х8-12,понедельник,4
передняя дельта,тяжелая,6х12-15,понедельник,4
сгибание на предплечье,средняя,4х8-12,понедельник,4
присед со штангой,средняя,5х6-8,среда,4
классическая тяга,тяжелая,7х6-8,среда,4
разгибания ног в тренажере,тяжелая,6х8-12,среда,4
сгибания ног в тренажере,средняя,5х8-12,среда,4
махи на среднюю дельту,средняя,5х8-12,среда,4
отведения на дельты,тяжелая,6х8-12,среда,4
разгибание на предплечье,средняя,4х8-12,среда,4
присед со штангой,легкая,3х6-8,пятница,4
жим гантелей лёжа 30°,средняя,5х8-12,пятница,4
тяга горизонтального блока,тяжелая,7х8-12,пятница,4
подъем на бицепс с прямым грифом,средняя,4х12-15,пятница,4
подъем на носки в смите,средняя,4х12-15,пятница,4
сгибание на предплечье,средняя,4х8-12,пятница,4
французский жим лёжа,легкая,3х8-12,пятница,4
разгибание на предплечье,средняя,4х8-12,пятница,4
жим лёжа,тяжелая,8х8-12,понедельник,5
тяга вертикального блока,средняя,6х8-12,понедельник,5
шраги с гантелями,тяжелая,8х8-12,понедельник,5
косичка,средняя,5х8-12,понедельник,5
сгибания на бицепс ez грифа,тяжелая,8х8-12,понедельник,5
молотки,средняя,5х8-12,понедельник,5
передняя дельта,тяжелая,7х8-12,понедельник,5
с médicale
присед со штангой,тяжелая,8х6-8,среда,5
классическая тяга,средняя,6х6-8,среда,5
разгибания ног в тренажере,средняя,5х8-12,среда,5
сгибания ног в тренажере,тяжелая,8х8-12,среда,5
махи на среднюю дельту,средняя,6х8-12,среда,5
отведения на дельты,тяжелая,7х8-12,среда,5
разгибание на предплечье,средняя,5х8-12,среда,5
присед со штангой,легкая,3х6-8,пятница,5
жим гантелей лёжа 30°,средняя,6х8-12,пятница,5
тяга горизонтального блока,средняя,6х8-12,пятница,5
подъем на бицепс с прямым грифом,тяжелая,6х12-15,пятница,5
подъем на носки в смите,средняя,5х12-15,пятница,5
сгибание на предплечье,средняя,5х8-12,пятница,5
французский жим лёжа,легкая,3х8-12,пятница,5
разгибание на предплечье,средняя,5х8-12,пятница,5
жим лёжа,средняя,6х8-12,понедельник,6
тяга вертикального блока,тяжелая,8х8-12,понедельник,6
шраги с гантелями,средняя,6х8-12,понедельник,6
косичка,тяжелая,7х8-12,понедельник,6
сгибания на бицепс ez грифа,средняя,6х8-12,понедельник,6
молотки,тяжелая,7х8-12,понедельник,6
передняя дельта,средняя,5х12-15,понедельник,6
сгибание на предплечье,тяжелая,6х8-12,понедельник,6
присед со штангой,средняя,6х6-8,среда,6
классическая тяга,средняя,6х6-8,среда,6
разгибания ног в тренажере,средняя,5х8-12,среда,6
сгибания ног в тренажере,средняя,5х8-12,среда,6
махи на среднюю дельту,тяжелая,8х8-12,среда,6
отведения на дельты,тяжелая,7х8-12,среда,6
разгибание на предплечье,тяжелая,6х8-12,среда,6
присед со штангой,легкая,3х6-8,пятница,6
жим гантелей лёжа 30°,средняя,6х8-12,пятница,6
тяга горизонтального блока,средняя,6х8-12,пятница,6
подъем на бицепс с прямым грифом,тяжелая,7х12-15,пятница,6
подъем на носки в смите,средняя,5х8-12,пятница,6
сгибание на предплечье,тяжелая,6х8-12,пятница,6
французский жим лёжа,легкая,3х8-12,пятница,6
разгибание на предплечье,средняя,5х8-12,пятница,6
жим лёжа,тяжелая,8х8-12,понедельник,7
тяга вертикального блока,тяжелая,8х8-12,понедельник,7
шраги с гантелями,средняя,6х8-12,понедельник,7
косичка,средняя,6х8-12,понедельник,7
сгибания на бицепс ez грифа,средняя,6х8-12,понедельник,7
молотки,тяжелая,8х8-12,понедельник,7
передняя дельта,средняя,5х12-15,понедельник,7
сгибание на предплечье,средняя,5х8-12,понедельник,7
присед со штангой,средняя,6х6-8,среда,7
классическая тяга,средняя,6х6-8,среда,7
разгибания ног в тренажере,тяжелая,8х8-12,среда,7
сгибания ног в тренажере,тяжелая,8х8-12,среда,7
махи на среднюю дельту,средняя,6х8-12,среда,7
отведения на дельты,тяжелая,7х8-12,среда,7
разгибание на предплечье,тяжелая,6х8-12,среда,7
присед со штангой,легкая,3х6-8,пятница,7
жим гантелей лёжа 30°,средняя,6х8-12,пятница,7
тяга горизонтального блока,средняя,6х8-12,пятница,7
подъем на бицепс с прямым грифом,тяжелая,7х12-15,пятница,7
подъем на носки в смите,тяжелая,7х8-12,пятница,7
сгибание на предплечье,тяжелая,6х8-12,пятница,7
французский жим лёжа,легкая,3х8-12,пятница,7
разгибание на предплечье,средняя,5х8-12,пятница,7
жим лёжа,средняя,6х8-12,понедельник,8
тяга вертикального блока,тяжелая,8х8-12,понедельник,8
шраги с гантелями,средняя,6х8-12,понедельник,8
косичка,тяжелая,8х8-12,понедельник,8
сгибания на бицепс ez грифа,тяжелая,8х8-12,понедельник,8
молотки,средняя,6х8-12,понедельник,8
передняя дельта,средняя,5х8-12,понедельник,8
сгибание на предплечье,средняя,5х8-12,понедельник,8
присед со штангой,средняя,6х6-8,среда,8
классическая тяга,средняя,6х6-8,среда,8
разгибания ног в тренажере,средняя,6х8-12,среда,8
сгибания ног в тренажере,средняя,6х8-12,среда,8
махи на среднюю дельту,тяжелая,8х8-12,среда,8
отведения на дельты,тяжелая,7х8-12,среда,8
разгибание на предплечье,тяжелая,7х8-12,среда,8
присед со штангой,легкая,3х6-8,пятница,8
жим гантелей лёжа 30°,тяжелая,8х8-12,пятница,8
тяга горизонтального блока,средняя,6х8-12,пятница,8
подъем на бицепс с прямым грифом,тяжелая,7х12-15,пятница,8
подъем на носки в смите,средняя,5х8-12,пятница,8
сгибание на предплечье,тяжелая,7х8-12,пятница,8
французский жим лёжа,легкая,3х8-12,пятница,8
разгибание на предплечье,средняя,5х8-12,пятница,8
"""

# Преобразование данных в DataFrame
try:
    df = pd.read_csv(StringIO(CSV_DATA))
    logger.info("CSV данные успешно загружены")
except Exception as e:
    logger.error(f"Ошибка при чтении CSV данных: {e}")
    raise

# Маппинг упражнений для расчёта весов с добавленными новыми упражнениями
EXERCISE_MAPPING = {
    "жим лёжа": {"main_lift": "bench_press", "scale": 1.0, "min_weight": 20.0, "max_weight": 500.0, "increment": 2.5},
    "присед со штангой": {"main_lift": "squat", "scale": 1.0, "min_weight": 20.0, "max_weight": 600.0, "increment": 2.5},
    "классическая тяга": {"main_lift": "deadlift", "scale": 1.0, "min_weight": 20.0, "max_weight": 700.0, "increment": 2.5},
    "тяга вертикального блока": {"main_lift": "bench_press", "scale": 0.55, "min_weight": 10.0, "max_weight": 120.0, "increment": 2.5},
    "тяга горизонтального блока": {"main_lift": "bench_press", "scale": 0.55, "min_weight": 10.0, "max_weight": 120.0, "increment": 2.5},
    "шраги с гантелями": {"main_lift": "deadlift", "scale": 0.20, "min_weight": 4.0, "max_weight": 80.0, "increment": 2.0},
    "косичка": {"main_lift": "bench_press", "scale": 0.50, "min_weight": 5.0, "max_weight": 50.0, "increment": 2.5},
    "французский жим лёжа": {"main_lift": "bench_press", "scale": 0.25, "min_weight": 10.0, "max_weight": 60.0, "increment": 2.5},
    "сгибания на бицепс ez грифа": {"main_lift": "bench_press", "scale": 0.25, "min_weight": 5.0, "max_weight": 50.0, "increment": 2.5},
    "подъем на бицепс с прямым грифом": {"main_lift": "bench_press", "scale": 0.3, "min_weight": 10.0, "max_weight": 50.0, "increment": 2.5},
    "молотки": {"main_lift": "bench_press", "scale": 0.20, "min_weight": 4.0, "max_weight": 30.0, "increment": 2.0},
    "передняя дельта": {"main_lift": "bench_press", "scale": 0.18, "min_weight": 4.0, "max_weight": 25.0, "increment": 2.0},
    "махи на среднюю дельту": {"main_lift": "bench_press", "scale": 0.15, "min_weight": 2.0, "max_weight": 25.0, "increment": 2.0},
    "отведения на дельты": {"main_lift": "bench_press", "scale": 0.20, "min_weight": 10.0, "max_weight": 35.0, "increment": 2.0},
    "подъем на носки в смите": {"main_lift": "squat", "scale": 0.3, "min_weight": 30.0, "max_weight": 100.0, "increment": 5.0},
    "сгибание на предплечье": {"main_lift": "bench_press", "scale": 0.6, "min_weight": 25.0, "max_weight": 60.0, "increment": 2.5},
    "разгибание на предплечье": {"main_lift": "bench_press", "scale": 0.6, "min_weight": 25.0, "max_weight": 60.0, "increment": 2.5},
    "разгибания ног в тренажере": {"main_lift": "squat", "scale": 0.60, "min_weight": 30.0, "max_weight": 100.0, "increment": 5.0},
    "сгибания ног в тренажере": {"main_lift": "squat", "scale": 0.60, "min_weight": 30.0, "max_weight": 90.0, "increment": 5.0},
    "жим гантелей лёжа 30°": {"main_lift": "bench_press", "scale": 0.30, "min_weight": 10.0, "max_weight": 50.0, "increment": 2.0}
}

# Функция для расчёта веса
def calculate_weight(max_lift: float, intensity: str, exercise: str) -> str:
    """Рассчитывает диапазон веса на основе максимума, интенсивности и упражнения."""
    try:
        mapping = EXERCISE_MAPPING.get(exercise.lower(), {
            "main_lift": "bench_press",
            "scale": 0.3,
            "min_weight": 5.0,
            "max_weight": 80.0,
            "increment": 2.5
        })
        scale = mapping["scale"]
        min_weight = mapping["min_weight"]
        max_weight = mapping["max_weight"]
        increment = mapping["increment"]

        base_weight = max_lift * scale
        intensity = intensity.lower()
        if intensity == "легкая":
            low = base_weight * 0.50
            high = base_weight * 0.60
        elif intensity == "средняя":
            low = base_weight * 0.60
            high = base_weight * 0.70
        elif intensity == "тяжелая":
            low = base_weight * 0.70
            high = base_weight * 0.80
        else:
            return "Не указан вес (неизвестная интенсивность)"

        # Ограничение весов и округление
        low = max(min_weight, min(max_weight, round(low / increment) * increment))
        high = max(min_weight, min(max_weight, round(high / increment) * increment))
        return f"{low:.1f}-{high:.1f} кг"
    except Exception as e:
        logger.error(f"Ошибка при расчёте веса для упражнения {exercise}: {e}")
        return "Ошибка расчёта веса"

# Функция для форматирования программы тренировок
async def format_workout_plan(week: int = None, user_id: int = None) -> str:
    """Форматирует план тренировок для указанной недели или всех недель."""
    if week is not None and not 1 <= week <= 8:
        return "Ошибка: Неделя должна быть от 1 до 8."

    user_data = load_user_data(user_id)
    logger.info(f"Извлечены данные для пользователя {user_id}: {user_data}")

    max_weights = {
        "bench_press": user_data.get("bench_press", 0.0),
        "squat": user_data.get("squat", 0.0),
        "deadlift": user_data.get("deadlift", 0.0)
    }
    logger.info(f"Максимальные веса для пользователя {user_id}: {max_weights}")

    result = "**Программа тренировок**\n\n"
    if week:
        result += f"**Неделя {week}**\n"
        week_df = df[df['неделя'] == week]
    else:
        week_df = df

    if week_df.empty:
        return f"Ошибка: Данные для недели {week} не найдены."

    days = ['понедельник', 'среда', 'пятница']
    for day in days:
        day_df = week_df[week_df['день'] == day]
        if not day_df.empty:
            result += f"\n*{day.capitalize()}*\n"
            for _, row in day_df.iterrows():
                exercise = row['упражнения']
                intensity = row['интенсивность']
                reps = row['подходы х повторения']

                # Определяем базовый вес для упражнения
                mapping = EXERCISE_MAPPING.get(exercise.lower(), {"main_lift": "bench_press", "scale": 0.3})
                main_lift = mapping["main_lift"]
                max_lift = max_weights.get(main_lift, 0.0)

                weight = calculate_weight(max_lift, intensity, exercise) if max_lift > 0 else "Введите максимальные веса (/reset)"
                result += f"- {exercise}: {intensity.capitalize()} ({reps}, {weight})\n"

    return result

# Валидация ввода веса
def validate_weight(text: str) -> tuple[bool, float, str]:
    """Проверяет, является ли введённый текст допустимым весом."""
    try:
        weight = float(text)
        if weight < 0:
            return False, 0.0, "Вес не может быть отрицательным."
        if weight > 1000:
            return False, 0.0, "Вес слишком большой. Введите реалистичное значение (до 1000 кг)."
        return True, weight, ""
    except ValueError:
        return False, 0.0, "Введите число (например, 100) или 'пропустить'."

# Обработчик команды /start
@router.message(CommandStart())
async def start_command(message: Message, state: FSMContext):
    """Запускает процесс ввода максимальных весов."""
    try:
        await state.clear()
        await message.answer("Привет! Я бот для тренировок. Давай начнём с твоих максимальных результатов.")
        await message.answer("Введи свой максимальный вес в жиме лёжа (в кг, например, 100) или напиши 'пропустить':")
        await state.set_state(MaxLiftForm.bench_press)
        logger.info(f"Пользователь {message.from_user.id} начал ввод максимальных весов")
    except Exception as e:
        logger.error(f"Ошибка в start_command для пользователя {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка. Попробуйте снова с /start.")

# Обработчик команды /cancel
@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    """Отменяет текущий процесс ввода весов."""
    try:
        current_state = await state.get_state()
        if current_state is None:
            await message.answer("Нет активного процесса ввода весов.")
            logger.info(f"Пользователь {message.from_user.id} попытался отменить, но не было активного состояния")
            return
        await state.clear()
        await message.answer(
            "Ввод весов отменён. Выбери неделю или используй команды:\n"
            "- /start — начать ввод весов\n"
            "- /workout — полный план тренировок\n"
            "- /week — выбрать неделю\n"
            "- /my_weights — проверить текущие веса\n"
            "- /reset — сбросить и ввести новые веса\n"
            "- /help — список всех команд",
            reply_markup=get_week_keyboard()
        )
        logger.info(f"Пользователь {message.from_user.id} отменил ввод весов")
    except Exception as e:
        logger.error(f"Ошибка в cancel_command для пользователя {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка при отмене. Попробуйте снова.")

# Обработчик ввода максимума в жиме лёжа
@router.message(MaxLiftForm.bench_press)
async def process_bench_press(message: Message, state: FSMContext):
    """Обрабатывает ввод максимального веса в жиме лёжа."""
    try:
        if message.text.lower() == 'пропустить':
            await state.update_data(bench_press=0.0, squat=0.0, deadlift=0.0)
            user_data = await state.get_data()
            save_user_data(message.from_user.id, user_data)
            await state.clear()
            await message.answer(
                "Вы пропустили ввод весов. План будет без расчёта весов.\n"
                "Выбери неделю или используй команды:\n"
                "- /workout — полный план тренировок\n"
                "- /week — выбрать неделю\n"
                "- /my_weights — проверить текущие веса\n"
                "- /reset — ввести максимальные веса\n"
                "- /help — список всех команд",
                reply_markup=get_week_keyboard()
            )
            logger.info(f"Пользователь {message.from_user.id} пропустил ввод весов")
            return

        is_valid, weight, error_msg = validate_weight(message.text)
        if not is_valid:
            await message.answer(f"Ошибка: {error_msg} Для отмены используй /cancel.")
            return

        await state.update_data(bench_press=weight)
        await message.answer("Отлично! Теперь введи свой максимальный вес в приседе (в кг) или 'пропустить':")
        await state.set_state(MaxLiftForm.squat)
        logger.info(f"Пользователь {message.from_user.id} ввёл жим лёжа: {weight} кг")
    except Exception as e:
        logger.error(f"Ошибка в process_bench_press для пользователя {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка. Попробуйте снова или используй /cancel.")

# Обработчик ввода максимума в приседе
@router.message(MaxLiftForm.squat)
async def process_squat(message: Message, state: FSMContext):
    """Обрабатывает ввод максимального веса в приседе."""
    try:
        if message.text.lower() == 'пропустить':
            await state.update_data(squat=0.0, deadlift=0.0)
            user_data = await state.get_data()
            save_user_data(message.from_user.id, user_data)
            await state.clear()
            await message.answer(
                "Вы пропустили ввод весов. План будет без расчёта весов.\n"
                "Выбери неделю или используй команды:\n"
                "- /workout — полный план тренировок\n"
                "- /week — выбрать неделю\n"
                "- /my_weights — проверить текущие веса\n"
                "- /reset — ввести максимальные веса\n"
                "- /help — список всех команд",
                reply_markup=get_week_keyboard()
            )
            logger.info(f"Пользователь {message.from_user.id} пропустил ввод весов")
            return

        is_valid, weight, error_msg = validate_weight(message.text)
        if not is_valid:
            await message.answer(f"Ошибка: {error_msg} Для отмены используй /cancel.")
            return

        await state.update_data(squat=weight)
        await message.answer("Супер! Введи свой максимальный вес в становой тяге (в кг) или 'пропустить':")
        await state.set_state(MaxLiftForm.deadlift)
        logger.info(f"Пользователь {message.from_user.id} ввёл присед: {weight} кг")
    except Exception as e:
        logger.error(f"Ошибка в process_squat для пользователя {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка. Попробуйте снова или используй /cancel.")

# Обработчик ввода максимума в становой тяге
@router.message(MaxLiftForm.deadlift)
async def process_deadlift(message: Message, state: FSMContext):
    """Обрабатывает ввод максимального веса в становой тяге."""
    try:
        if message.text.lower() == 'пропустить':
            await state.update_data(deadlift=0.0)
            user_data = await state.get_data()
            save_user_data(message.from_user.id, user_data)
            await state.clear()
            await message.answer(
                f"Ввод завершён. Текущие веса:\n"
                f"Жим лёжа: {user_data.get('bench_press', 0.0)} кг\n"
                f"Присед: {user_data.get('squat', 0.0)} кг\n"
                f"Становая тяга: {user_data.get('deadlift', 0.0)} кг\n"
                "Выбери неделю или используй команды:\n"
                "- /workout — полный план тренировок\n"
                "- /week — выбрать неделю\n"
                "- /my_weights — проверить текущие веса\n"
                "- /reset — ввести максимальные веса\n"
                "- /help — список всех команд",
                reply_markup=get_week_keyboard()
            )
            logger.info(f"Пользователь {message.from_user.id} пропустил ввод становой тяги. Текущие веса: {user_data}")
            return

        is_valid, weight, error_msg = validate_weight(message.text)
        if not is_valid:
            await message.answer(f"Ошибка: {error_msg} Для отмены используй /cancel.")
            return

        await state.update_data(deadlift=weight)
        user_data = await state.get_data()
        save_user_data(message.from_user.id, user_data)
        await state.clear()
        await message.answer(
            f"Отлично, данные сохранены!\n"
            f"Жим лёжа: {user_data['bench_press']} кг\n"
            f"Присед: {user_data['squat']} кг\n"
            f"Становая тяга: {user_data['deadlift']} кг\n"
            "Выбери неделю или используй команды:\n"
            "- /workout — полный план тренировок\n"
            "- /week — выбрать неделю\n"
            "- /my_weights — проверить текущие веса\n"
            "- /reset — ввести максимальные веса\n"
            "- /help — список всех команд",
            reply_markup=get_week_keyboard()
        )
        logger.info(f"Пользователь {message.from_user.id} завершил ввод весов: {user_data}")
    except Exception as e:
        logger.error(f"Ошибка в process_deadlift для пользователя {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка. Попробуйте снова или используй /cancel.")

# Обработчик команды /my_weights
@router.message(Command("my_weights"))
async def my_weights_command(message: Message, state: FSMContext):
    """Отображает текущие максимальные веса пользователя."""
    try:
        user_data = load_user_data(message.from_user.id)
        logger.info(f"Проверка весов для пользователя {message.from_user.id}: {user_data}")
        if not user_data or all(value == 0.0 for value in user_data.values()):
            await message.answer(
                "Вы ещё не ввели максимальные веса. Используй /start или /reset для ввода.",
                reply_markup=get_week_keyboard()
            )
            logger.info(f"Пользователь {message.from_user.id} запросил веса, но данные отсутствуют")
            return
        await message.answer(
            f"Текущие максимальные веса:\n"
            f"Жим лёжа: {user_data.get('bench_press', 0.0)} кг\n"
            f"Присед: {user_data.get('squat', 0.0)} кг\n"
            f"Становая тяга: {user_data.get('deadlift', 0.0)} кг\n"
            "Выбери неделю или используй /reset, чтобы обновить веса.",
            reply_markup=get_week_keyboard()
        )
        logger.info(f"Пользователь {message.from_user.id} запросил текущие веса: {user_data}")
    except Exception as e:
        logger.error(f"Ошибка в my_weights_command для пользователя {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка при получении весов. Попробуйте снова.")

# Обработчик команды /reset
@router.message(Command("reset"))
async def reset_command(message: Message, state: FSMContext):
    """Сбрасывает максимальные веса и начинает ввод заново."""
    try:
        await state.clear()
        clear_user_data(message.from_user.id)
        await message.answer("Максимальные веса сброшены. Введи свой максимальный вес в жиме лёжа (в кг) или 'пропустить':")
        await state.set_state(MaxLiftForm.bench_press)
        logger.info(f"Пользователь {message.from_user.id} сбросил максимальные веса")
    except Exception as e:
        logger.error(f"Ошибка в reset_command для пользователя {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка при сбросе весов. Попробуйте снова.")

# Обработчик команды /workout
@router.message(Command("workout"))
async def workout_command(message: Message, state: FSMContext):
    """Отправляет полный план тренировок."""
    try:
        workout_plan = await format_workout_plan(user_id=message.from_user.id)
        if len(workout_plan) > 4096:
            for i in range(0, len(workout_plan), 4096):
                await message.answer(workout_plan[i:i+4096], reply_markup=get_week_keyboard())
        else:
            await message.answer(workout_plan, reply_markup=get_week_keyboard())
        logger.info(f"Пользователь {message.from_user.id} запросил полный план тренировок")
    except Exception as e:
        logger.error(f"Ошибка в workout_command для пользователя {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка при получении плана тренировок. Попробуйте позже.")

# Обработчик команды /week
@router.message(Command("week"))
async def week_command(message: Message, state: FSMContext):
    """Отображает клавиатуру для выбора недели."""
    try:
        await message.answer(
            "Выбери неделю для тренировки:",
            reply_markup=get_week_keyboard()
        )
        logger.info(f"Пользователь {message.from_user.id} запросил выбор недели")
    except Exception as e:
        logger.error(f"Ошибка в week_command для пользователя {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка. Попробуйте снова.")

# Обработчик нажатий на кнопки недель
@router.callback_query(lambda c: c.data.startswith('week_'))
async def process_week_callback(callback: CallbackQuery):
    """Обрабатывает выбор недели через инлайн-кнопки."""
    try:
        week_number = int(callback.data.split('_')[1])
        workout_plan = await format_workout_plan(week=week_number, user_id=callback.from_user.id)
        await callback.message.answer(
            workout_plan,
            reply_markup=get_week_keyboard()
        )
        await callback.answer()
        logger.info(f"Пользователь {callback.from_user.id} выбрал неделю {week_number}")
    except ValueError:
        await callback.message.answer("Ошибка: Неверный формат номера недели.", reply_markup=get_week_keyboard())
        logger.warning(f"Пользователь {callback.from_user.id} вызвал ValueError в callback недели")
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в process_week_callback для пользователя {callback.from_user.id}: {e}")
        await callback.message.answer("Произошла ошибка. Попробуйте снова.", reply_markup=get_week_keyboard())
        await callback.answer()

# Обработчик команды /help
@router.message(Command("help"))
async def help_command(message: Message):
    """Отображает список доступных команд."""
    try:
        await message.answer(
            "Доступные команды:\n"
            "/start — Запустить бота и ввести максимальные веса\n"
            "/workout — Получить полный план тренировок\n"
            "/week — Выбрать неделю для тренировки (используй кнопки)\n"
            "/my_weights — Проверить текущие максимальные веса\n"
            "/reset — Сбросить максимальные веса и ввести новые\n"
            "/cancel — Отменить текущий ввод весов\n"
            "/help — Показать это сообщение",
            reply_markup=get_week_keyboard()
        )
        logger.info(f"Пользователь {message.from_user.id} запросил помощь")
    except Exception as e:
        logger.error(f"Ошибка в help_command для пользователя {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка при отображении помощи. Попробуйте снова.")

# Основная функция для запуска бота
async def main():
    """Запускает бота и инициализирует базу данных."""
    try:
        init_db()
        logger.info("Бот запущен...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
        raise
    finally:
        await dp.storage.close()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())