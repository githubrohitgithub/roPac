"""Tests for structured log analysis."""

from log_analysis import analyze_log_text, build_log_analysis_context, is_log_path


SAMPLE_LOG = """
[08:34:40 +0100] [Debug] [MainViewModel] New Session Started
[08:34:53 +0100] [Debug] [FreedomPayPaymentHandler] {"productName":"Porridge","quantity":1,"totalAmount":2.25}
[08:35:24 +0100] [Debug] [FreedomPayPaymentHandler] Got success for :ABC123
Decision: ACCEPT.
[08:35:27 +0100] [Debug] [OrderScreenViewModel] Place Order Success <><><> [PA37252Z260508083525829]
[08:49:23 +0100] [Debug] [OrdersSyncWorker] Orders in DB: total=119, offline (pending)=0
[08:52:16 +0100] [Debug] [OrderScreenViewModel] Place Order Success <><><> [PA37254Z260508085214851, PA37255Z260508085214923]
[08:52:01 +0100] [Debug] [FreedomPayPaymentHandler] {"productName":"Latte","quantity":1}
Decision: ACCEPT.
[09:00:00 +0100] [Error] [FreedomPayInitialization] FreedomPay connection failed: device offline
[09:01:00 +0100] [Error] [RestaurantMenuInitialization] Fetched menu successfully for TEST:restaurant
"""


def test_is_log_path():
    assert is_log_path("app.log")
    assert is_log_path("afcc_12_00.log")
    assert not is_log_path("resume.pdf")


def test_analyze_orders_and_payments():
    result = analyze_log_text(SAMPLE_LOG, filename="test.log")
    assert result.total_orders_placed == 3
    assert "PA37252Z260508083525829" in result.order_ids
    assert result.payments_accepted >= 2
    assert result.kiosk_sessions == 1
    assert result.db_total_latest == 119
    assert any("Porridge" in p for p in result.products)
    assert any("connection failed" in i for i in result.issues)
    assert not any("Fetched menu successfully" in i for i in result.issues)


def test_build_log_analysis_context_from_text(tmp_path):
    log_file = tmp_path / "session.log"
    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    report = build_log_analysis_context([str(log_file)], query="total number of orders")
    assert "LOG ANALYSIS" in report
    assert "Total orders placed (unique IDs): 3" in report
    assert "Place Order Success" in report or "PA37252" in report
