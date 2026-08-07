from dataclasses import dataclass


@dataclass(frozen=True)
class CalendarDayPrice:
    typename: str
    local_price_formatted: str | None


@dataclass(frozen=True)
class CalendarDay:
    typename: str
    calendar_date: str
    available: bool
    available_for_checkin: bool
    available_for_checkout: bool
    bookable: bool | None
    min_nights: int
    max_nights: int
    price: CalendarDayPrice


@dataclass(frozen=True)
class CalendarConditions:
    typename: str
    closed_to_arrival: bool
    closed_to_departure: bool
    end_day_of_week: None
    min_nights: int
    max_nights: int


@dataclass(frozen=True)
class CalendarConditionRange:
    typename: str
    start_date: str
    end_date: str
    conditions: CalendarConditions


@dataclass(frozen=True)
class CalendarMonth:
    typename: str
    listing_id: str
    month: int
    year: int
    days: tuple[CalendarDay, ...]
    condition_ranges: tuple[CalendarConditionRange, ...]


@dataclass(frozen=True)
class CalendarContractIssue:
    path: str
    kind: str
    expected: str | None
    actual: str | None
    message: str


def _format_contract_mismatch(issues: tuple[CalendarContractIssue, ...]) -> str:
    lines = [f"Calendar contract mismatch: {len(issues)} issues"]
    lines.extend(f"- {issue.path}: {issue.message}" for issue in issues)
    return "\n".join(lines)


class CalendarContractError(ValueError):
    def __init__(self, issues: tuple[CalendarContractIssue, ...]):
        self.issues = tuple(issues)
        super().__init__(_format_contract_mismatch(self.issues))


class CalendarExtractionError(ValueError):
    def __init__(self, path: str):
        self.path = path
        super().__init__(f"Calendar could not be extracted at {path}")


class CalendarContractWarning(UserWarning):
    def __init__(self, issues: tuple[CalendarContractIssue, ...]):
        self.issues = tuple(issues)
        super().__init__(_format_contract_mismatch(self.issues))
