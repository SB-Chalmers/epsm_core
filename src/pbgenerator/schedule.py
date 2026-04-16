from __future__ import annotations

from honeybee_energy.schedule.day import ScheduleDay
from honeybee_energy.schedule.rule import ScheduleRule
from honeybee_energy.schedule.ruleset import ScheduleRuleset
from honeybee_energy.lib.scheduletypelimits import schedule_type_limit_by_identifier
from ladybug.dt import Time


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Generic builders
# ---------------------------------------------------------------------------

def make_fractional_schedule(
    identifier: str,
    weekday_times: list[tuple[int, int]],
    weekday_values: list[float],
    weekend_times: list[tuple[int, int]],
    weekend_values: list[float],
) -> ScheduleRuleset:
    frac = schedule_type_limit_by_identifier("Fractional")
    wd_day = ScheduleDay(
        f"{identifier}_wd", weekday_values,
        [Time(h, m) for h, m in weekday_times],
    )
    we_day = ScheduleDay(
        f"{identifier}_we", weekend_values,
        [Time(h, m) for h, m in weekend_times],
    )
    weekend_rule = ScheduleRule(we_day, apply_sunday=True, apply_saturday=True)
    return ScheduleRuleset(identifier, wd_day,
                           schedule_rules=[weekend_rule],
                           schedule_type_limit=frac)


def make_constant_temp_schedule(identifier: str, temp: float) -> ScheduleRuleset:
    limit = schedule_type_limit_by_identifier("Temperature")
    return ScheduleRuleset(identifier, ScheduleDay(f"{identifier}_day", [temp]),
                           schedule_type_limit=limit)


def make_constant_fractional(identifier: str, value: float) -> ScheduleRuleset:
    frac = schedule_type_limit_by_identifier("Fractional")
    return ScheduleRuleset(identifier,
                           ScheduleDay(f"{identifier}_day", [_clamp(value, 0.0, 1.0)]),
                           schedule_type_limit=frac)


# ---------------------------------------------------------------------------
# Pre-defined schedule factories  (Sveby Brukarindata Bostadshus 2.0, 2024)
# ---------------------------------------------------------------------------

# Sveby: 14 h presence/day, 17:00-07:00, all days alike
OCC_SCHED = lambda: make_fractional_schedule(
    "OCC_SCH",
    [(0,0),(7,0),(17,0)], [1.0, 0.0, 1.0],
    [(0,0),(7,0),(17,0)], [1.0, 0.0, 1.0],
)
# Sveby: hushållsel internal heat is constant avg; no separate lighting schedule
LIGHT_SCHED = lambda: make_constant_fractional("LIGHT_SCH", 1.0)
EQUIP_SCHED = lambda: make_constant_fractional("EQUIP_SCH", 1.0)

# Sveby: 80 W/person (50 sensible + 30 latent)
ACTIVITY_SCHED = lambda: ScheduleRuleset("ACTIVITY_SCH", ScheduleDay("ACTIVITY_day", [80]))

# DHW schedule (kept for optional use; Sveby uses constant rate = always on)
DHW_SCHED = lambda: make_constant_fractional("DHW_SCH", 1.0)
