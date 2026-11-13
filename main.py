"""Streamlit UI: KPI draft -> CSV -> calculation settings -> monitoring."""
import streamlit as st
import pandas as pd
import altair as alt
from csv_import import parse_csv, file_hash
from database import (init_db, list_datasets, add_dataset, read_dataset,
                      list_kpis, add_kpi, update_target, delete_kpi, delete_dataset)
from calculations import calculate_monthly, calculate_daily

st.set_page_config(page_title="KPI Мониторинг", page_icon="📊", layout="wide")
init_db()
st.title("Мониторинг KPI")
st.caption("Создание KPI · импорт CSV · настройка расчёта · мониторинг")

create_tab, monitor_tab = st.tabs(
    ["1. Создание KPI и импорт данных", "2. Мониторинг"],
    key="section", bind="query-params",
)

with create_tab:
    st.subheader("1. Создание KPI")
    with st.form("kpi_details"):
        name = st.text_input("Название KPI", placeholder="Доля оплат через СБП")
        description = st.text_input("Описание (необязательно)")
        create_draft = st.form_submit_button("Создать KPI и перейти к импорту", type="primary")
    if create_draft:
        if not name.strip():
            st.error("Введите название показателя.")
        else:
            st.session_state["kpi_draft"] = {"name": name.strip(), "description": description.strip()}
    draft = st.session_state.get("kpi_draft")
    if draft:
        st.success(f'Черновик KPI «{draft["name"]}» создан. Импортируйте данные и настройте расчёт.')
        st.subheader("2. Импорт исходных данных")
        st.write("CSV должен содержать заголовки и столбец с датой. Поддерживаются разделители ',' и ';'.")
        file = st.file_uploader("Выберите CSV", type="csv")
        if file is not None:
            content = file.getvalue()
            try:
                frame = parse_csv(content)
                st.success(f"Прочитано строк: {len(frame)}; столбцов: {len(frame.columns)}")
                st.dataframe(frame.head(3), use_container_width=True, hide_index=True)
                if st.button("Сохранить набор данных", type="primary"):
                    dataset_id, created = add_dataset(file.name, file_hash(content), frame)
                    if created:
                        st.success(f"Набор данных №{dataset_id} сохранён в SQLite.")
                    else:
                        st.info("Такой файл уже был загружен: дубликат не создан.")
            except ValueError as exc:
                st.error(str(exc))
        st.subheader("3. Настройка расчёта")
        datasets = list_datasets()
        if not datasets:
            st.info("Загрузите и сохраните CSV выше, чтобы настроить расчёт KPI.")
        else:
            datasets_map = {f'{d["filename"]} · №{d["id"]}': d["id"] for d in datasets}
            with st.container():
                source_name = st.selectbox("Набор данных", list(datasets_map))
                source_id = datasets_map[source_name]
                frame = read_dataset(source_id)
                cols = list(frame.columns)
                date_col = st.selectbox("Столбец даты", cols)
                method_labels = {"Сумма": "sum", "Количество строк": "count", "Среднее": "mean",
                                 "Процент / доля": "percent"}
                method_label = st.selectbox("Тип расчёта", list(method_labels))
                operation = method_labels[method_label]
                basis = None
                if operation == "percent":
                    basis_label = st.radio("Процент считать по", ["Количеству записей", "Сумме значений"], horizontal=True)
                    basis = "count" if basis_label == "Количеству записей" else "sum"
                needs_number = operation in ("sum", "mean") or (operation == "percent" and basis == "sum")
                value_col = st.selectbox("Числовой столбец", cols) if needs_number else None
                apply_filter = st.checkbox("Использовать фильтр", value=(operation == "percent"),
                                           disabled=(operation == "percent"))
                filter_col, filter_val = None, None
                if apply_filter or operation == "percent":
                    filter_col = st.selectbox("Столбец фильтра", cols)
                    choices = sorted(frame[filter_col].dropna().astype(str).str.strip().unique().tolist())
                    filter_val = st.selectbox("Значение фильтра", choices)
                unit_default = "%" if operation == "percent" else ("шт." if operation == "count" else "")
                unit = st.text_input("Единица измерения", value=unit_default, placeholder="₽, %, шт., мин.")
                target = st.number_input("План за месяц", value=35.0 if operation == "percent" else 100.0, step=1.0)
                submitted = st.button("Сохранить KPI", type="primary")
            if submitted:
                config = {"name": draft["name"], "description": draft["description"], "unit": unit.strip(),
                          "dataset_id": source_id, "date_column": date_col, "operation": operation,
                          "value_column": value_col, "filter_column": filter_col, "filter_value": filter_val,
                          "percent_basis": basis, "target": target}
                if not config["name"]:
                    st.error("Введите название показателя.")
                else:
                    try:
                        results, bad_dates = calculate_monthly(frame, config)
                        add_kpi(config)
                        st.success(f"KPI создан. Рассчитано периодов: {len(results)}.")
                        if bad_dates:
                            st.warning(f"Строк без корректной даты: {bad_dates}. Они не учитываются.")
                    except ValueError as exc:
                        st.error(f"Не удалось рассчитать KPI: {exc}")

    with st.expander("Управление наборами данных"):
        sources = list_datasets()
        if not sources:
            st.info("Нет сохранённых наборов данных.")
        else:
            st.dataframe(pd.DataFrame(sources)[["id", "filename", "row_count", "imported_at"]],
                         use_container_width=True, hide_index=True)
            dataset_to_delete = st.selectbox(
                "Набор для удаления", [d["id"] for d in sources],
                format_func=lambda source_id: next(
                    f'{d["filename"]} · №{d["id"]}' for d in sources if d["id"] == source_id),
            )
            linked = [k["name"] for k in list_kpis() if k["dataset_id"] == dataset_to_delete]
            if linked:
                st.info("Набор используется в KPI: " + ", ".join(linked)
                        + ". Сначала удалите эти показатели на вкладке «Мониторинг».")
            confirmed = st.checkbox("Подтверждаю удаление набора и всех его строк",
                                    key=f"confirm_dataset_{dataset_to_delete}")
            if st.button("Удалить набор данных", disabled=bool(linked) or not confirmed):
                try:
                    delete_dataset(dataset_to_delete)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()

with monitor_tab:
    st.subheader("Результаты мониторинга")
    kpis = list_kpis()
    if not kpis:
        st.info("Создайте показатель на вкладке «Создание KPI и импорт данных».")
    else:
        selected_label = st.selectbox("Показатель", [f'{k["name"]} · №{k["id"]}' for k in kpis])
        selected_id = int(selected_label.rsplit("№", 1)[1])
        kpi = next(k for k in kpis if k["id"] == selected_id)
        st.caption(f'Источник: {kpi["dataset_name"]} · расчёт: {kpi["operation"]} · единица: {kpi["unit"] or "не задана"}')
        if kpi["description"]:
            st.write(kpi["description"])
        with st.expander("Изменить план или удалить показатель"):
            revised_target = st.number_input("План", value=float(kpi["target"]), key=f'target_{selected_id}')
            c1, c2 = st.columns(2)
            if c1.button("Сохранить план", key=f'save_{selected_id}'):
                update_target(selected_id, revised_target)
                st.rerun()
            confirm_delete = c2.checkbox("Подтвердить удаление KPI", key=f'confirm_{selected_id}')
            if c2.button("Удалить KPI", disabled=not confirm_delete, key=f'delete_{selected_id}'):
                delete_kpi(selected_id)
                st.rerun()
        try:
            result, bad_dates = calculate_monthly(read_dataset(kpi["dataset_id"]), kpi)
            if bad_dates:
                st.warning(f"При расчёте пропущено {bad_dates} строк с некорректной датой.")
            last = result.iloc[-1]
            c1, c2, c3 = st.columns(3)
            c1.metric("Факт за последний месяц", f'{last["Факт"]:.2f} {kpi["unit"]}' if pd.notna(last["Факт"]) else "Нет данных")
            c2.metric("План за месяц", f'{last["План"]:.2f} {kpi["unit"]}')
            c3.metric("Факт − план", f'{last["Отклонение"]:+.2f} {kpi["unit"]}' if pd.notna(last["Отклонение"]) else "Нет данных")
            daily, _ = calculate_daily(read_dataset(kpi["dataset_id"]), kpi)
            daily["Дата"] = pd.to_datetime(daily["Дата"])
            latest_month = daily["Дата"].max().to_period("M")
            selected_period = st.date_input(
                "Период просмотра",
                value=(latest_month.start_time.date(), latest_month.end_time.date()),
                key=f"view_period_{selected_id}",
                format="DD.MM.YYYY",
            )
            if len(selected_period) != 2:
                st.info("Выберите начало и конец периода.")
            else:
                start_date, end_date = selected_period
                days = pd.date_range(start_date, end_date, freq="D")
                displayed = daily.set_index("Дата").reindex(days).rename_axis("Дата").reset_index()
                st.caption(f"Динамика с {start_date:%d.%m.%Y} по {end_date:%d.%m.%Y}")
                # Ordinal dates keep every calendar day visible, including days without data.
                displayed["День"] = displayed["Дата"].dt.strftime("%d.%m.%Y")
                chart = alt.Chart(displayed).mark_line(point=True).encode(
                    x=alt.X("День:O", sort=None, title="День",
                            axis=alt.Axis(labelAngle=-90, labelOverlap=False)),
                    y=alt.Y("Факт:Q", title=kpi["unit"] or "Факт", scale=alt.Scale(zero=False)),
                    tooltip=[alt.Tooltip("День:O", title="Дата"),
                             alt.Tooltip("Факт:Q", format=".2f")],
                )
                st.altair_chart(chart, use_container_width=True)
                if displayed["Факт"].isna().all():
                    st.info("За выбранный период нет рассчитанных значений.")
                st.caption("Дни без исходных данных показаны без значения. План задан за месяц и не распределяется по дням.")
                st.dataframe(displayed[["День", "Факт"]].rename(columns={"День": "Дата"}).style.format(
                    {"Факт": "{:.2f}"}, na_rep="—"), use_container_width=True, hide_index=True)
                export = displayed[["Дата", "Факт"]]
                st.download_button(
                    "Скачать рассчитанные значения (CSV)",
                    export.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"kpi_{selected_id}_{start_date}_{end_date}.csv", mime="text/csv",
                )
            st.caption("Сравнение носит числовой характер: система не определяет, является ли отклонение хорошим или плохим.")
        except ValueError as exc:
            st.error(str(exc))
