import re
from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar

from pyairbnb.calendar_models import (
    CalendarConditionRange,
    CalendarConditions,
    CalendarContractError,
    CalendarContractIssue,
    CalendarDay,
    CalendarDayPrice,
    CalendarMonth,
)

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_T = TypeVar("_T")


class _CalendarParser:
    def __init__(self) -> None:
        self.issues: list[CalendarContractIssue] = []

    def parse(self, value: object) -> list[CalendarMonth]:
        months = self._list(value, "$", self._month)
        if self.issues:
            raise CalendarContractError(tuple(self.issues))
        return months

    def _issue(
        self,
        path: str,
        kind: str,
        expected: str | None,
        value: object,
        message: str,
        *,
        missing: bool = False,
        actual: str | None = None,
    ) -> None:
        if actual is None and not missing:
            actual = type(value).__name__
        self.issues.append(CalendarContractIssue(path, kind, expected, actual, message))

    def _object(
        self, value: object, path: str, expected_keys: set[str]
    ) -> dict[str, object] | None:
        if type(value) is not dict:
            self._issue(path, "invalid_container", "dict", value, "expected an object")
            return None

        result = value
        for key in sorted(expected_keys - result.keys()):
            self._issue(
                f"{path}.{key}",
                "missing_field",
                "present",
                None,
                "missing required field",
                missing=True,
            )
        for key in sorted(result.keys() - expected_keys):
            self._issue(
                f"{path}.{key}",
                "extra_field",
                None,
                result[key],
                "unexpected field",
            )
        return result

    def _list(
        self,
        value: object,
        path: str,
        parser: Callable[[object, str], _T | None],
    ) -> list[_T]:
        if type(value) is not list:
            self._issue(path, "invalid_container", "list", value, "expected a list")
            return []
        parsed: list[_T] = []
        for index, item in enumerate(value):
            converted = parser(item, f"{path}[{index}]")
            if converted is not None:
                parsed.append(converted)
        return parsed

    def _string(self, value: object, path: str) -> str | None:
        if type(value) is not str:
            self._issue(path, "invalid_type", "str", value, "expected a string")
            return None
        return value

    def _nullable_string(self, value: object, path: str) -> str | None:
        if value is None:
            return None
        return self._string(value, path)

    def _boolean(self, value: object, path: str) -> bool | None:
        if type(value) is not bool:
            self._issue(path, "invalid_type", "bool", value, "expected a boolean")
            return None
        return value

    def _nullable_boolean(self, value: object, path: str) -> bool | None:
        if value is None:
            return None
        return self._boolean(value, path)

    def _integer(
        self, value: object, path: str, *, minimum: int = 0, maximum: int | None = None
    ) -> int | None:
        if type(value) is not int:
            self._issue(path, "invalid_type", "int", value, "expected an integer")
            return None
        if value < minimum or (maximum is not None and value > maximum):
            expected = f"int from {minimum}"
            if maximum is not None:
                expected += f" to {maximum}"
            self._issue(
                path,
                "invalid_value",
                expected,
                value,
                f"expected {expected}",
                actual=repr(value),
            )
            return None
        return value

    def _date(self, value: object, path: str) -> str | None:
        parsed = self._string(value, path)
        if parsed is None:
            return None
        if not _DATE_PATTERN.fullmatch(parsed):
            self._issue(
                path,
                "invalid_value",
                "date in YYYY-MM-DD format",
                value,
                "expected a date in YYYY-MM-DD format",
                actual=repr(value),
            )
            return None
        try:
            date.fromisoformat(parsed)
        except ValueError:
            self._issue(
                path,
                "invalid_value",
                "valid calendar date",
                value,
                "expected a valid calendar date",
                actual=repr(value),
            )
            return None
        return parsed

    def _typename(self, value: object, path: str, expected: str) -> str | None:
        parsed = self._string(value, path)
        if parsed is not None and parsed != expected:
            self._issue(
                path,
                "invalid_value",
                expected,
                value,
                f"expected {expected}",
                actual=repr(value),
            )
            return None
        return parsed

    def _month(self, value: object, path: str) -> CalendarMonth | None:
        keys = {"__typename", "listingId", "month", "year", "days", "conditionRanges"}
        item = self._object(value, path, keys)
        if item is None:
            return None

        typename = self._field(
            item,
            "__typename",
            path,
            lambda value, path: self._typename(value, path, "MerlinCalendarMonth"),
        )
        listing_id = self._field(item, "listingId", path, self._string)
        month = self._field(
            item,
            "month",
            path,
            lambda value, path: self._integer(value, path, minimum=1, maximum=12),
        )
        year = self._field(item, "year", path, self._integer)
        days = self._field(
            item,
            "days",
            path,
            lambda value, path: tuple(self._list(value, path, self._day)),
        )
        ranges = self._field(
            item,
            "conditionRanges",
            path,
            lambda value, path: tuple(self._list(value, path, self._condition_range)),
        )
        if any(
            value is _MISSING
            for value in (typename, listing_id, month, year, days, ranges)
        ):
            return None
        return CalendarMonth(typename, listing_id, month, year, days, ranges)

    def _day(self, value: object, path: str) -> CalendarDay | None:
        keys = {
            "__typename",
            "calendarDate",
            "available",
            "availableForCheckin",
            "availableForCheckout",
            "bookable",
            "minNights",
            "maxNights",
            "price",
        }
        item = self._object(value, path, keys)
        if item is None:
            return None

        typename = self._field(
            item,
            "__typename",
            path,
            lambda value, path: self._typename(value, path, "MerlinCalendarDay"),
        )
        calendar_date = self._field(item, "calendarDate", path, self._date)
        available = self._field(item, "available", path, self._boolean)
        checkin = self._field(item, "availableForCheckin", path, self._boolean)
        checkout = self._field(item, "availableForCheckout", path, self._boolean)
        bookable = self._field(
            item, "bookable", path, self._nullable_boolean, nullable=True
        )
        min_nights = self._field(item, "minNights", path, self._integer)
        max_nights = self._field(item, "maxNights", path, self._integer)
        price = self._field(item, "price", path, self._price)
        values = (
            typename,
            calendar_date,
            available,
            checkin,
            checkout,
            bookable,
            min_nights,
            max_nights,
            price,
        )
        if any(value is _MISSING for value in values):
            return None
        return CalendarDay(*values)

    def _price(self, value: object, path: str) -> CalendarDayPrice | None:
        keys = {"__typename", "localPriceFormatted"}
        item = self._object(value, path, keys)
        if item is None:
            return None
        typename = self._field(
            item,
            "__typename",
            path,
            lambda value, path: self._typename(value, path, "MerlinCalendarDayPrice"),
        )
        local_price = self._field(
            item, "localPriceFormatted", path, self._nullable_string, nullable=True
        )
        if typename is _MISSING or local_price is _MISSING:
            return None
        return CalendarDayPrice(typename, local_price)

    def _condition_range(
        self, value: object, path: str
    ) -> CalendarConditionRange | None:
        keys = {"__typename", "startDate", "endDate", "conditions"}
        item = self._object(value, path, keys)
        if item is None:
            return None
        typename = self._field(
            item,
            "__typename",
            path,
            lambda value, path: self._typename(
                value, path, "MerlinCalendarConditionRange"
            ),
        )
        start_date = self._field(item, "startDate", path, self._date)
        end_date = self._field(item, "endDate", path, self._date)
        conditions = self._field(item, "conditions", path, self._conditions)
        if (
            start_date is not _MISSING
            and end_date is not _MISSING
            and start_date > end_date
        ):
            self._issue(
                f"{path}.endDate",
                "invalid_value",
                "date on or after startDate",
                end_date,
                "endDate cannot be before startDate",
                actual=repr(end_date),
            )
            end_date = _MISSING
        if any(
            value is _MISSING for value in (typename, start_date, end_date, conditions)
        ):
            return None
        return CalendarConditionRange(typename, start_date, end_date, conditions)

    def _conditions(self, value: object, path: str) -> CalendarConditions | None:
        keys = {
            "__typename",
            "closedToArrival",
            "closedToDeparture",
            "endDayOfWeek",
            "minNights",
            "maxNights",
        }
        item = self._object(value, path, keys)
        if item is None:
            return None
        typename = self._field(
            item,
            "__typename",
            path,
            lambda value, path: self._typename(value, path, "MerlinCalendarConditions"),
        )
        arrival = self._field(item, "closedToArrival", path, self._boolean)
        departure = self._field(item, "closedToDeparture", path, self._boolean)
        end_day = self._field(item, "endDayOfWeek", path, self._none, nullable=True)
        min_nights = self._field(item, "minNights", path, self._integer)
        max_nights = self._field(item, "maxNights", path, self._integer)
        values = (typename, arrival, departure, end_day, min_nights, max_nights)
        if any(value is _MISSING for value in values):
            return None
        return CalendarConditions(*values)

    def _none(self, value: object, path: str) -> None:
        if value is not None:
            self._issue(
                path,
                "invalid_value",
                "null",
                value,
                "expected null",
                actual=repr(value),
            )

    def _field(
        self,
        item: dict[str, object],
        key: str,
        path: str,
        parser: Callable[[object, str], Any],
        *,
        nullable: bool = False,
    ) -> Any:
        if key not in item:
            return _MISSING
        before = len(self.issues)
        result = parser(item[key], f"{path}.{key}")
        if len(self.issues) != before:
            return _MISSING
        if result is None and not nullable:
            return _MISSING
        return result


_MISSING = object()


def parse_calendar(value: object) -> list[CalendarMonth]:
    """Validate and convert an extracted Airbnb calendar payload."""
    return _CalendarParser().parse(value)
