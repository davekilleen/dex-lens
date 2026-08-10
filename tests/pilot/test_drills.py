from capability_exchange.pilot.drills import REQUIRED_RUNBOOK_IDS, DrillExecutor


def test_all_five_runbooks_have_passing_tabletops() -> None:
    executor = DrillExecutor()
    results = executor.execute_all()
    assert tuple(result.runbook_id for result in results) == REQUIRED_RUNBOOK_IDS
    assert executor.complete()
    withdrawal = next(result for result in results if result.runbook_id == "withdrawal")
    assert withdrawal.deletion_verified
    adverse = next(result for result in results if result.runbook_id == "incident")
    assert adverse.stop_triggered
    assert "Recovery failed" in adverse.scenario
