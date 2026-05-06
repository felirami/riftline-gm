from riftline_gm.dice import parse_and_roll


class RiggedRng:
    def __init__(self, values):
        self.values = list(values)

    def randint(self, a, b):
        value = self.values.pop(0)
        assert a <= value <= b
        return value


def test_roll_simple_expression():
    result = parse_and_roll("2d6+3", rng=RiggedRng([2, 5]))

    assert result.dice == [2, 5]
    assert result.modifier == 3
    assert result.total == 10


def test_roll_d10_critical_success_adds_extra_die():
    result = parse_and_roll("d10+4", rng=RiggedRng([10, 7]))

    assert result.dice == [10, 7]
    assert result.total == 21
    assert "Critical success" in result.critical_note


def test_roll_d10_critical_failure_subtracts_extra_die():
    result = parse_and_roll("1d10+5", rng=RiggedRng([1, 6]))

    assert result.dice == [1, -6]
    assert result.total == 0
    assert "Critical failure" in result.critical_note


def test_roll_rejects_bad_expression():
    try:
        parse_and_roll("roll the bones")
    except ValueError as exc:
        assert "Use dice" in str(exc)
    else:
        raise AssertionError("Expected ValueError")

