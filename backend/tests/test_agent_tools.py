from agent_tools import (
    calculate_budget_status,
    categorize_spending,
    compare_periods,
    detect_anomalies,
    forecast_next_month,
    get_budgets,
    get_transactions,
)
from models import Budget


# --- categorize_spending ----------------------------------------------------

def test_categorize_spending_sums_by_category_and_ignores_money_in(db, make_user, add_txn):
    user = make_user()
    add_txn(user.id, "2026-09-01", 10.00, "FOOD_AND_DRINK")
    add_txn(user.id, "2026-09-02", 15.50, "FOOD_AND_DRINK")
    add_txn(user.id, "2026-09-03", 40.00, "TRANSPORTATION")
    add_txn(user.id, "2026-09-04", -500.00, "INCOME")  # Plaid: negative = money in, not spending

    result = categorize_spending(db, user.id)

    assert result["by_category"] == {"TRANSPORTATION": 40.00, "FOOD_AND_DRINK": 25.50}
    assert result["total"] == 65.50


def test_categorize_spending_date_range_is_inclusive(db, make_user, add_txn):
    user = make_user()
    add_txn(user.id, "2026-08-31", 100.00)
    add_txn(user.id, "2026-09-01", 10.00)
    add_txn(user.id, "2026-09-30", 20.00)
    add_txn(user.id, "2026-10-01", 400.00)

    result = categorize_spending(db, user.id, start_date="2026-09-01", end_date="2026-09-30")

    assert result["total"] == 30.00


def test_categorize_spending_groups_missing_category(db, make_user, add_txn):
    user = make_user()
    add_txn(user.id, "2026-09-01", 12.00, category=None)

    assert categorize_spending(db, user.id)["by_category"] == {"Uncategorized": 12.00}


# --- get_transactions -------------------------------------------------------

def test_get_transactions_filters_by_category_newest_first(db, make_user, add_txn):
    user = make_user()
    add_txn(user.id, "2026-09-01", 5.00, "FOOD_AND_DRINK", name="old")
    add_txn(user.id, "2026-09-09", 7.00, "FOOD_AND_DRINK", name="new")
    add_txn(user.id, "2026-09-05", 9.00, "TRANSPORTATION", name="bus")

    result = get_transactions(db, user.id, category="FOOD_AND_DRINK")

    assert result["count"] == 2
    assert [t["name"] for t in result["transactions"]] == ["new", "old"]


# --- detect_anomalies -------------------------------------------------------

def test_detect_anomalies_flags_an_outlier(db, make_user, add_txn):
    user = make_user()
    for day in range(1, 11):
        add_txn(user.id, f"2026-09-{day:02d}", 10.00, "FOOD_AND_DRINK", name="coffee")
    add_txn(user.id, "2026-09-15", 500.00, "FOOD_AND_DRINK", name="mystery charge")

    result = detect_anomalies(db, user.id)

    assert result["count"] == 1
    assert result["anomalies"][0]["name"] == "mystery charge"


def test_detect_anomalies_needs_enough_data_in_a_category(db, make_user, add_txn):
    user = make_user()
    add_txn(user.id, "2026-09-01", 10.00, "TRAVEL")
    add_txn(user.id, "2026-09-02", 900.00, "TRAVEL")  # only 2 data points - can't call it unusual

    assert detect_anomalies(db, user.id)["count"] == 0


def test_detect_anomalies_ignores_money_in(db, make_user, add_txn):
    user = make_user()
    for day in range(1, 11):
        add_txn(user.id, f"2026-09-{day:02d}", -10.00, "INCOME")
    add_txn(user.id, "2026-09-15", -5000.00, "INCOME")  # a big paycheck is not an anomaly

    assert detect_anomalies(db, user.id)["count"] == 0


# --- budgets ----------------------------------------------------------------

def test_budget_status_uses_stored_budget(db, make_user, add_txn):
    user = make_user()
    db.add(Budget(user_id=user.id, category="FOOD_AND_DRINK", monthly_amount=100.0))
    db.commit()
    add_txn(user.id, "2026-09-02", 60.00, "FOOD_AND_DRINK")

    result = calculate_budget_status(db, user.id, "FOOD_AND_DRINK", start_date="2026-09-01", end_date="2026-09-30")

    assert result["budget_source"] == "stored"
    assert result["spent"] == 60.00
    assert result["remaining"] == 40.00
    assert result["percent_used"] == 60.0
    assert result["over_budget"] is False


def test_budget_status_flags_overspend(db, make_user, add_txn):
    user = make_user()
    add_txn(user.id, "2026-09-02", 120.00, "FOOD_AND_DRINK")

    result = calculate_budget_status(db, user.id, "FOOD_AND_DRINK", budget_amount=100.0)

    assert result["over_budget"] is True
    assert result["remaining"] == -20.00
    assert result["budget_source"] == "given_in_message"


def test_budget_status_explicit_amount_beats_stored(db, make_user, add_txn):
    user = make_user()
    db.add(Budget(user_id=user.id, category="FOOD_AND_DRINK", monthly_amount=100.0))
    db.commit()
    add_txn(user.id, "2026-09-02", 60.00, "FOOD_AND_DRINK")

    result = calculate_budget_status(db, user.id, "FOOD_AND_DRINK", budget_amount=50.0)

    assert result["budget"] == 50.0
    assert result["over_budget"] is True


def test_budget_status_with_no_budget_anywhere_returns_an_error(db, make_user):
    user = make_user()

    result = calculate_budget_status(db, user.id, "FOOD_AND_DRINK")

    assert "error" in result


# --- compare_periods / forecast ---------------------------------------------

def test_compare_periods(db, make_user, add_txn):
    user = make_user()
    add_txn(user.id, "2026-09-10", 100.00)
    add_txn(user.id, "2026-08-10", 50.00)

    result = compare_periods(db, user.id, "2026-09-01", "2026-09-30", "2026-08-01", "2026-08-31")

    assert result["period_a"]["total"] == 100.00
    assert result["period_b"]["total"] == 50.00
    assert result["change"] == 50.00
    assert result["percent_change"] == 100.0


def test_compare_periods_with_empty_baseline_has_no_percent(db, make_user, add_txn):
    user = make_user()
    add_txn(user.id, "2026-09-10", 100.00)

    result = compare_periods(db, user.id, "2026-09-01", "2026-09-30", "2026-08-01", "2026-08-31")

    assert result["percent_change"] is None


def test_forecast_is_the_average_of_monthly_totals(db, make_user, add_txn):
    user = make_user()
    add_txn(user.id, "2026-08-10", 100.00)
    add_txn(user.id, "2026-09-10", 200.00)

    result = forecast_next_month(db, user.id)

    assert result["forecast_next_month"] == 150.00
    assert result["months_of_data"] == ["2026-08", "2026-09"]


def test_forecast_with_no_data(db, make_user):
    user = make_user()

    assert forecast_next_month(db, user.id)["forecast"] is None


# --- isolation: one user's data never leaks into another's tool results -----

def test_every_tool_is_scoped_to_its_user(db, make_user, add_txn):
    alice = make_user("alice@gmail.com")
    bob = make_user("bob@gmail.com")
    for day in range(1, 11):
        add_txn(alice.id, f"2026-09-{day:02d}", 10.00, "ALICE_ONLY")
    add_txn(alice.id, "2026-09-15", 500.00, "ALICE_ONLY")
    db.add(Budget(user_id=alice.id, category="ALICE_ONLY", monthly_amount=100.0))
    db.commit()

    assert get_transactions(db, bob.id)["count"] == 0
    assert categorize_spending(db, bob.id)["total"] == 0
    assert detect_anomalies(db, bob.id)["count"] == 0
    assert get_budgets(db, bob.id)["count"] == 0
    assert forecast_next_month(db, bob.id)["forecast"] is None
    assert compare_periods(db, bob.id, "2026-09-01", "2026-09-30", "2026-08-01", "2026-08-31")["period_a"]["total"] == 0
    # Bob can't use Alice's stored budget either
    assert "error" in calculate_budget_status(db, bob.id, "ALICE_ONLY")

    # ...and Alice still sees her own data
    assert get_transactions(db, alice.id)["count"] == 11
    assert get_budgets(db, alice.id)["count"] == 1
