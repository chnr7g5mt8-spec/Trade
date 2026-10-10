from app import diagnostics


def test_reports_success_and_failure_per_check(monkeypatch):
    def boom():
        raise RuntimeError("blocked")

    monkeypatch.setattr(diagnostics, "CHECKS", {"good": lambda: "fine", "bad": boom})
    monkeypatch.setattr(diagnostics, "_cached", None)
    report = diagnostics.run()
    assert report["checks"]["good"]["ok"] is True
    assert report["checks"]["good"]["detail"] == "fine"
    assert report["checks"]["bad"] == {"ok": False, "detail": "RuntimeError: blocked",
                                       "seconds": report["checks"]["bad"]["seconds"]}


def test_results_are_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(diagnostics, "CHECKS", {"x": lambda: calls.append(1) or "ok"})
    monkeypatch.setattr(diagnostics, "_cached", None)
    diagnostics.run()
    diagnostics.run()
    assert len(calls) == 1
