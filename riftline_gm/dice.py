from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Protocol


class RandomLike(Protocol):
    def randint(self, a: int, b: int) -> int: ...


ROLL_RE = re.compile(r"^\s*(?:(?P<count>\d*)d(?P<sides>\d+))\s*(?P<mod>[+-]\s*\d+)?\s*$", re.I)


@dataclass(frozen=True)
class RollResult:
    expression: str
    dice: list[int]
    modifier: int
    total: int
    critical_note: str | None = None

    def format(self) -> str:
        dice_text = " + ".join(str(value) for value in self.dice)
        mod_text = ""
        if self.modifier > 0:
            mod_text = f" + {self.modifier}"
        elif self.modifier < 0:
            mod_text = f" - {abs(self.modifier)}"

        note = f"\n{self.critical_note}" if self.critical_note else ""
        return f"`{self.expression}` -> {dice_text}{mod_text} = **{self.total}**{note}"


def parse_and_roll(expression: str, *, rng: RandomLike | None = None) -> RollResult:
    rng = rng or random.SystemRandom()
    match = ROLL_RE.match(expression)
    if not match:
        raise ValueError("Use dice like d10, 1d10+5, 2d6, or 3d6-1.")

    count_raw = match.group("count")
    count = int(count_raw) if count_raw else 1
    sides = int(match.group("sides"))
    modifier_raw = match.group("mod")
    modifier = int(modifier_raw.replace(" ", "")) if modifier_raw else 0

    if count < 1 or count > 20:
        raise ValueError("Dice count must be between 1 and 20.")
    if sides < 2 or sides > 1000:
        raise ValueError("Dice sides must be between 2 and 1000.")

    dice = [rng.randint(1, sides) for _ in range(count)]
    total = sum(dice) + modifier
    note = None

    if count == 1 and sides == 10:
        if dice[0] == 10:
            extra = rng.randint(1, 10)
            dice.append(extra)
            total += extra
            note = "Critical success trigger: add the extra d10."
        elif dice[0] == 1:
            extra = rng.randint(1, 10)
            dice.append(-extra)
            total -= extra
            note = "Critical failure trigger: subtract the extra d10."

    return RollResult(expression=expression.strip(), dice=dice, modifier=modifier, total=total, critical_note=note)

