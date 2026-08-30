from data_logger import bump_restart_count


def test_bump_restart_count_starts_at_one(tmp_path):
    path = tmp_path / "restart_count.json"
    assert bump_restart_count(path) == 1


def test_bump_restart_count_increments_across_calls(tmp_path):
    path = tmp_path / "restart_count.json"
    bump_restart_count(path)
    bump_restart_count(path)
    assert bump_restart_count(path) == 3


def test_bump_restart_count_recovers_from_corrupt_file(tmp_path):
    path = tmp_path / "restart_count.json"
    path.write_text("not a number")
    assert bump_restart_count(path) == 1
