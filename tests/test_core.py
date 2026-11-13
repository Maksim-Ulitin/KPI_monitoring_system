import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pytest
from csv_import import parse_csv, file_hash
from calculations import calculate_monthly


def test_csv_semicolon_and_comma():
    a = parse_csv('date;method;amount\n2026-01-01;SBP;100\n'.encode())
    b = parse_csv('date,method,amount\n2026-01-01,SBP,100\n'.encode())
    assert list(a.columns) == list(b.columns) == ['date', 'method', 'amount']
    assert file_hash(b'abc') == file_hash(b'abc')


def test_percent_sum_and_count_not_average_of_percentages():
    frame = pd.DataFrame({'date': ['2026-01-01'] * 3 + ['2026-02-01'] * 2,
                          'method': ['SBP', 'CARD', 'CARD', 'SBP', 'CARD'],
                          'amount': ['100', '100', '800', '40', '60']})
    common = dict(date_column='date', operation='percent', filter_column='method',
                  filter_value='SBP', value_column='amount', target=35)
    sums, invalid = calculate_monthly(frame, dict(common, percent_basis='sum'))
    counts, _ = calculate_monthly(frame, dict(common, percent_basis='count'))
    assert invalid == 0
    assert list(sums['Факт']) == pytest.approx([10, 40])
    assert list(counts['Факт']) == pytest.approx([100/3, 50])
    assert list(sums['Отклонение']) == pytest.approx([-25, 5])


def test_sum_average_count_and_filter():
    frame = pd.DataFrame({'date': ['2026-01-01']*3,
                          'kind': ['A', 'A', 'B'], 'num': ['1,5', '2,5', '10']})
    base = dict(date_column='date', value_column='num', target=4,
                filter_column='kind', filter_value='A')
    assert calculate_monthly(frame, dict(base, operation='sum'))[0]['Факт'][0] == pytest.approx(4)
    assert calculate_monthly(frame, dict(base, operation='mean'))[0]['Факт'][0] == pytest.approx(2)
    assert calculate_monthly(frame, dict(base, operation='count'))[0]['Факт'][0] == pytest.approx(2)


def test_zero_denominator_missing_value_and_invalid_date():
    frame = pd.DataFrame({'date': ['2026-01-01', '2026-01-02', 'bad'],
                          'kind': ['A', 'B', 'A'], 'amount': ['0', '0', '10']})
    cfg = dict(date_column='date', operation='percent', percent_basis='sum',
               value_column='amount', filter_column='kind', filter_value='A', target=35)
    out, invalid = calculate_monthly(frame, cfg)
    assert invalid == 1
    assert pd.isna(out.iloc[0]['Факт'])


def test_missing_filter_for_percent():
    frame = pd.DataFrame({'date': ['2026-01-01']})
    with pytest.raises(ValueError):
        calculate_monthly(frame, dict(date_column='date', operation='percent',
                                      filter_column=None, target=35))


def test_daily_percent_uses_each_days_source_rows():
    from calculations import calculate_daily
    frame = pd.DataFrame({
        'date': ['2026-01-01', '2026-01-01', '2026-01-03', '2026-02-01', 'bad'],
        'kind': ['A', 'B', 'A', 'B', 'A'],
        'amount': ['10', '30', '20', '50', '100'],
    })
    cfg = dict(date_column='date', operation='percent', percent_basis='sum',
               value_column='amount', filter_column='kind', filter_value='A', target=35)
    daily, invalid = calculate_daily(frame, cfg)
    assert invalid == 1
    assert list(daily.columns) == ['Дата', 'Факт']
    assert list(daily['Дата']) == ['2026-01-01', '2026-01-03', '2026-02-01']
    assert list(daily['Факт']) == pytest.approx([25, 100, 0])


def test_delete_dataset_removes_rows_and_protects_linked_kpis(tmp_path, monkeypatch):
    import database as db
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'test.sqlite3')
    db.init_db()
    frame = pd.DataFrame({'date': ['2026-01-01']})
    source_id, _ = db.add_dataset('test.csv', 'test-hash', frame)
    db.add_kpi(dict(name='Test', description='', unit='', dataset_id=source_id,
                    date_column='date', operation='count', target=1))
    with pytest.raises(ValueError, match='используется'):
        db.delete_dataset(source_id)
    assert len(db.read_dataset(source_id)) == 1
    db.delete_kpi(db.list_kpis()[0]['id'])
    db.delete_dataset(source_id)
    assert db.list_datasets() == []
    assert db.read_dataset(source_id).empty


def test_slash_dates_infer_month_first_for_whole_column():
    from calculations import calculate_daily
    frame = pd.DataFrame({'date': [f'1/{day}/2026' for day in range(1, 32)]})
    cfg = dict(date_column='date', operation='count', target=31)
    daily, invalid = calculate_daily(frame, cfg)
    monthly, _ = calculate_monthly(frame, cfg)
    assert invalid == 0
    assert daily['Дата'].tolist() == [f'2026-01-{day:02}' for day in range(1, 32)]
    assert monthly['Месяц'].tolist() == ['2026-01']
    assert monthly['Факт'].tolist() == [31]


def test_date_parser_preserves_russian_and_iso_dates():
    from calculations import parse_dates
    dates = parse_dates(pd.Series(['02.01.2026', '2026-01-03', '14/01/2026', '02/01/2026']))
    assert dates.dt.strftime('%Y-%m-%d').tolist() == [
        '2026-01-02', '2026-01-03', '2026-01-14', '2026-01-02']
