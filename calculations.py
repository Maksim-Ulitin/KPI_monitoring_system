import pandas as pd


def as_number(series):
    cleaned = (series.astype("string").str.strip().str.replace(r"[\s\u00a0]", "", regex=True)
               .str.replace(",", ".", regex=False))
    return pd.to_numeric(cleaned, errors="coerce")


def parse_dates(series):
    values = series.astype("string").str.strip()
    parts = values.str.extract(r"^(\d{1,2})/(\d{1,2})/\d{4}(?:\s.*)?$")
    first = pd.to_numeric(parts[0], errors="coerce")
    second = pd.to_numeric(parts[1], errors="coerce")
    month_first = bool((second > 12).any())
    day_first = bool((first > 12).any())
    if month_first and day_first:
        raise ValueError("В столбце смешаны форматы ДД/ММ/ГГГГ и ММ/ДД/ГГГГ. Приведите даты к ГГГГ-ММ-ДД.")
    dates = pd.to_datetime(values, errors="coerce", dayfirst=True, format="mixed")
    slash_rows = parts[0].notna()
    if month_first:
        dates.loc[slash_rows] = pd.to_datetime(
            values.loc[slash_rows], errors="coerce", dayfirst=False, format="mixed")
    return dates


def calculate_monthly(frame, cfg):
    return _calculate_periods(frame, cfg, "M", "Месяц")


def calculate_daily(frame, cfg):
    out, invalid = _calculate_periods(frame, cfg, "D", "Дата")
    return out[["Дата", "Факт"]], invalid


def _calculate_periods(frame, cfg, frequency, period_label):
    date_col = cfg["date_column"]
    if date_col not in frame.columns:
        raise ValueError(f"Не найден столбец даты: {date_col}")
    df = frame.copy()
    dates = parse_dates(df[date_col])
    invalid = int(dates.isna().sum())
    df = df.loc[dates.notna()].copy()
    if df.empty:
        raise ValueError("Нет строк с корректной датой.")
    df["_month"] = dates.loc[dates.notna()].dt.to_period(frequency).astype(str)

    op = cfg["operation"]
    value_col = cfg.get("value_column")
    if op in ("sum", "mean") or (op == "percent" and cfg.get("percent_basis") == "sum"):
        if not value_col or value_col not in df.columns:
            raise ValueError("Нужен существующий числовой столбец.")
        df["_number"] = as_number(df[value_col])
    else:
        df["_number"] = 1.0

    filter_col = cfg.get("filter_column")
    filter_value = cfg.get("filter_value")
    if filter_col:
        if filter_col not in df.columns:
            raise ValueError(f"Не найден столбец фильтра: {filter_col}")
        selected = df[filter_col].astype(str).str.strip() == str(filter_value).strip()
    else:
        selected = pd.Series(True, index=df.index)

    results = []
    for month, group in df.groupby("_month", sort=True):
        subset = group.loc[selected.loc[group.index]]
        if op == "sum":
            value = subset["_number"].sum(min_count=1)
        elif op == "mean":
            value = subset["_number"].mean()
        elif op == "count":
            value = float(len(subset))
        elif op == "percent":
            if not filter_col:
                raise ValueError("Для процента нужен фильтр числителя (например, тип оплаты = СБП).")
            basis = cfg.get("percent_basis", "count")
            if basis == "count":
                numerator, denominator = len(subset), len(group)
            elif basis == "sum":
                numerator = 0.0 if subset.empty else subset["_number"].sum(min_count=1)
                denominator = group["_number"].sum(min_count=1)
            else:
                raise ValueError("Неизвестная база процента.")
            value = numerator / denominator * 100 if pd.notna(denominator) and denominator != 0 else float("nan")
        else:
            raise ValueError("Неизвестный тип расчёта.")
        results.append({period_label: month, "Факт": float(value) if pd.notna(value) else float("nan")})

    out = pd.DataFrame(results)
    target = float(cfg["target"])
    out["План"] = target
    out["Отклонение"] = out["Факт"] - target
    return out, invalid
