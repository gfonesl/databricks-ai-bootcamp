from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from lakebase import TripwiseRepository, lakebase_connection


@contextmanager
def _connection_with(cursor):
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    yield connection


def test_save_weather_replaces_existing_snapshots(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.return_value = {"exists": 1}
    monkeypatch.setattr("lakebase.lakebase_connection", lambda: _connection_with(cursor))
    repository = TripwiseRepository()
    forecasts = [
        {
            "date": "2026-08-14",
            "condition": "Clear",
            "weather_code": 0,
            "temperature_min": 15,
            "temperature_max": 25,
            "precipitation_probability_max": 5,
            "wind_speed_max": 10,
            "uv_index_max": 5,
            "risk_level": "low",
        }
    ]

    with patch("lakebase.execute_values") as execute_values:
        assert repository.save_weather(7, forecasts) == 1

    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert any("FOR UPDATE" in statement for statement in statements)
    assert any("DELETE FROM tripwise.weather_snapshots" in statement for statement in statements)
    execute_values.assert_called_once()


def test_build_packing_list_replaces_generated_items(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        {"exists": 1},
        {
            "precipitation_probability_max": 50,
            "temperature_min": 20,
            "temperature_max": 25,
            "wind_speed_max": 10,
        },
    ]
    monkeypatch.setattr("lakebase.lakebase_connection", lambda: _connection_with(cursor))

    with patch("lakebase.execute_values") as execute_values:
        items = TripwiseRepository().build_packing_list(3)

    assert [item["item"] for item in items] == ["Umbrella or rain shell"]
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert any("DELETE FROM tripwise.packing_items" in statement for statement in statements)
    execute_values.assert_called_once()


def test_build_packing_list_requires_weather(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        {"exists": 1},
        {
            "precipitation_probability_max": None,
            "temperature_min": None,
            "temperature_max": None,
            "wind_speed_max": None,
        },
    ]
    monkeypatch.setattr("lakebase.lakebase_connection", lambda: _connection_with(cursor))

    with pytest.raises(ValueError, match="Sync current weather"):
        TripwiseRepository().build_packing_list(3)


def test_build_packing_list_removes_obsolete_weather_items(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        {"exists": 1},
        {
            "precipitation_probability_max": 5,
            "temperature_min": 20,
            "temperature_max": 25,
            "wind_speed_max": 10,
        },
    ]
    monkeypatch.setattr("lakebase.lakebase_connection", lambda: _connection_with(cursor))

    with patch("lakebase.execute_values") as execute_values:
        items = TripwiseRepository().build_packing_list(3)

    assert [item["item"] for item in items] == ["Comfortable walking shoes"]
    assert any(
        "DELETE FROM tripwise.packing_items" in call.args[0]
        for call in cursor.execute.call_args_list
    )
    inserted_rows = execute_values.call_args.args[2]
    assert inserted_rows == [
        (3, "Comfortable walking shoes", "No material weather risk is currently forecast.")
    ]


def test_connection_rolls_back_non_database_errors(monkeypatch):
    connection = MagicMock()
    monkeypatch.setattr("lakebase._credential", lambda: "temporary-token")
    monkeypatch.setattr(
        "lakebase._settings",
        lambda: {"host": "db", "dbname": "tripwise", "user": "app"},
    )
    monkeypatch.setattr("lakebase.psycopg2.connect", lambda **_kwargs: connection)

    with pytest.raises(RuntimeError, match="failed after delete"):
        with lakebase_connection():
            raise RuntimeError("failed after delete")

    connection.rollback.assert_called_once_with()
    connection.commit.assert_not_called()
    connection.close.assert_called_once_with()
