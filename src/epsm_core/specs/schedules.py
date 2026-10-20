# File: specs/schedules.py
# Purpose: Explicit local-standard-time operational calendars.
# SPDX-License-Identifier: MIT
# Date created: 2026-10-03
# References: EnergyPlus 24.2 Input Output Reference, Schedule:Compact;
# https://bigladdersoftware.com/epx/docs/24-2/input-output-reference/group-schedules.html
"""Daily, weekly and dated schedules without implicit holidays or daylight saving.

Values describe hour-start intervals in the EPW's local standard time. Date
periods override weekly profiles; annual vectors are exclusive, year-pinned
inputs. No national holiday or school term is inferred from a building label.
"""

from __future__ import annotations

from calendar import isleap
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, timedelta
from typing import Annotated

from pydantic import Field, model_validator

from .base import Spec

DayValues = Annotated[tuple[float, ...], Field(min_length=24, max_length=24)]

_hourly_schedules: ContextVar[dict | None] = ContextVar("epsm_hourly_schedules", default=None)


@contextmanager
def hourly_schedule_scope() -> Iterator[None]:
    """Reuse immutable hourly tuples during one preparation and calculation call.

    Equal schedule contents and years share expansion, including across model
    validation and delivered-energy accounting. Nested scopes share their outer
    call's values; leaving the outer scope releases them, also after a failure.
    Outside a scope, ``ScheduleSpec.hourly`` retains its ordinary behavior. This
    performs no I/O and does not retain schedules between independent calls.

    Yields
    ------
    None
        A local scope; ``ScheduleSpec.hourly`` continues to return immutable tuples.
    """
    if _hourly_schedules.get() is not None:
        yield
        return
    token = _hourly_schedules.set({})
    try:
        yield
    finally:
        _hourly_schedules.reset(token)


class SchedulePeriod(Spec):
    """Inclusive dated replacement for a daily profile, with source provenance.

    Periods cannot overlap. Cross-year periods and periods not in the simulated
    year are rejected rather than silently omitted. Use separate periods per year.
    """

    start_date: date
    end_date: date
    values: DayValues
    source: Annotated[str, Field(min_length=1, pattern=r"\S")]

    @model_validator(mode="after")
    def ordered(self):
        """Require an ordered, single-year interval."""
        if self.start_date > self.end_date or self.start_date.year != self.end_date.year:
            raise ValueError("Schedule period must be ordered and lie within one year")
        return self


class ScheduleSpec(Spec):
    """Backward-compatible daily values with optional explicit calendar controls.

    ``weekday_values`` has seven profiles, Monday first. ``periods`` take
    precedence over those profiles. An ``annual_values`` vector requires its
    Gregorian ``calendar_year`` and exactly 8760/8784 values. Its year is checked
    against the building climate before compilation. Values retain the units of
    their consuming field; UseSpec/AirflowSpec validate fractional limits.
    """

    source: str | None = None
    values: DayValues
    weekday_values: Annotated[tuple[DayValues, ...], Field(min_length=7, max_length=7)] | None = (
        None
    )
    periods: tuple[SchedulePeriod, ...] = ()
    annual_values: tuple[float, ...] | None = None
    calendar_year: Annotated[int, Field(ge=1900, le=2200)] | None = None

    @model_validator(mode="after")
    def calendar(self):
        """Reject ambiguous vectors, duplicate periods and detached year labels."""
        if self.annual_values is not None:
            if self.calendar_year is None or self.weekday_values or self.periods:
                raise ValueError(
                    "Annual schedule requires a year and cannot also use calendar rules"
                )
            if len(self.annual_values) != (8784 if isleap(self.calendar_year) else 8760):
                raise ValueError("Annual schedule length must match its Gregorian year")
        elif self.calendar_year is not None:
            raise ValueError("calendar_year is reserved for explicit annual values")
        ordered = sorted(self.periods, key=lambda p: p.start_date)
        if any(a.end_date >= b.start_date for a, b in zip(ordered, ordered[1:])):
            raise ValueError("Schedule periods cannot overlap")
        return self

    @classmethod
    def constant(cls, value: float):
        """Return the historical repeated 24-hour constant profile."""
        return cls(values=(value,) * 24)

    @classmethod
    def annual(cls, values, *, calendar_year: int, source: str | None = None):
        """Pin an explicit hourly vector to a Gregorian local-standard-time year."""
        values = tuple(values)
        if not values:
            raise ValueError("Annual schedule cannot be empty")
        return cls(
            values=(values[0],) * 24,
            annual_values=values,
            calendar_year=calendar_year,
            source=source,
        )

    @property
    def all_values(self):
        """Expose every declared value, including overrides, for bounds validation."""
        if self.annual_values is not None:
            return self.annual_values
        return (
            self.values
            + tuple(v for day in self.weekday_values or () for v in day)
            + tuple(v for p in self.periods for v in p.values)
        )

    @property
    def declared_years(self):
        """Return years which the schedule explicitly references."""
        return {p.start_date.year for p in self.periods} | (
            {self.calendar_year} if self.calendar_year is not None else set()
        )

    def hourly(self, year: int) -> tuple[float, ...]:
        """Expand all calendar rules, rejecting any date/year mismatch.

        Every hour is represented once, including 29 February. No DST, warm-up
        or design-day hours are inserted. This is the axis used by climate/results.
        """
        if self.annual_values is not None:
            # Already immutable and expanded; retain year checks without
            # serializing an entire annual vector merely to cache its identity.
            return self._expand_hourly(year)
        retained = _hourly_schedules.get()
        if retained is None:
            return self._expand_hourly(year)
        # Do not let an equal-valued float reuse an integer year's expansion:
        # uncached daily calendar construction rejects that input type.
        key = (self.model_dump_json(), type(year), year)
        if key not in retained:
            retained[key] = self._expand_hourly(year)
        return retained[key]

    def _expand_hourly(self, year: int) -> tuple[float, ...]:
        """Validate the selected year and expand this schedule's calendar rules."""
        if not 1900 <= year <= 2200:
            raise ValueError("Schedule year must lie in [1900,2200]")
        if self.declared_years and self.declared_years != {year}:
            raise ValueError("Schedule calendar differs from simulation year")
        if self.annual_values is not None:
            return self.annual_values
        values = []
        current = date(year, 1, 1)
        while current.year == year:
            day = self.weekday_values[current.weekday()] if self.weekday_values else self.values
            for period in self.periods:
                if period.start_date <= current <= period.end_date:
                    day = period.values
                    break
            values.extend(day)
            current += timedelta(days=1)
        return tuple(values)

    def compact_data(self, year: int) -> list[dict]:
        """Emit Schedule:Compact blocks after resolving the actual calendar.

        Consecutive identical days share a block. AllDays ensures EnergyPlus
        holiday/day-type flags cannot override the explicitly resolved dates.
        The historical daily profile emits the identical one-block representation.
        """
        hourly = self.hourly(year)
        days = [hourly[i : i + 24] for i in range(0, len(hourly), 24)]
        data = []
        for i, day in enumerate(days):
            if i + 1 < len(days) and day == days[i + 1]:
                continue
            end = date(year, 1, 1) + timedelta(days=i)
            data.extend(
                [{"field": f"Through: {end.month:02}/{end.day:02}"}, {"field": "For: AllDays"}]
            )
            for hour, value in enumerate(day, 1):
                data.extend([{"field": f"Until: {hour:02}:00"}, {"field": value}])
        return data
