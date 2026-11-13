from io import BytesIO
import hashlib
import pandas as pd

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 25_000


def parse_csv(content):
    if not content:
        raise ValueError("Файл пуст.")
    if len(content) > MAX_BYTES:
        raise ValueError("Максимальный размер CSV — 5 МБ.")
    last_error = None
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            frame = pd.read_csv(BytesIO(content), sep=None, engine="python", encoding=encoding,
                                dtype=str, keep_default_na=False)
            break
        except UnicodeDecodeError as exc:
            last_error = exc
        except (pd.errors.ParserError, ValueError) as exc:
            raise ValueError(f"Не удалось разобрать CSV: {exc}") from exc
    else:
        raise ValueError("Не удалось прочитать кодировку файла.") from last_error
    if frame.empty or not len(frame.columns):
        raise ValueError("CSV должен содержать заголовки и хотя бы одну строку данных.")
    if len(frame) > MAX_ROWS:
        raise ValueError("Допустимо не более 25 000 строк в одном файле.")
    frame.columns = [str(c).strip() for c in frame.columns]
    if any(not c or c.startswith("Unnamed:") for c in frame.columns):
        raise ValueError("Все столбцы должны иметь названия.")
    if len(set(frame.columns)) != len(frame.columns):
        raise ValueError("Названия столбцов должны быть уникальными.")
    return frame


def file_hash(content):
    return hashlib.sha256(content).hexdigest()
