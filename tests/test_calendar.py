import copy
import unittest
import warnings
from dataclasses import FrozenInstanceError
from unittest.mock import Mock, patch

import pyairbnb
from pyairbnb import calendarinfo
from pyairbnb.calendar_parser import parse_calendar


def calendar_fixture():
    return [
        {
            "__typename": "MerlinCalendarMonth",
            "listingId": "123",
            "month": 8,
            "year": 2026,
            "days": [
                {
                    "__typename": "MerlinCalendarDay",
                    "calendarDate": "2026-08-01",
                    "available": True,
                    "availableForCheckin": True,
                    "availableForCheckout": False,
                    "bookable": None,
                    "minNights": 1,
                    "maxNights": 365,
                    "price": {
                        "__typename": "MerlinCalendarDayPrice",
                        "localPriceFormatted": None,
                    },
                }
            ],
            "conditionRanges": [
                {
                    "__typename": "MerlinCalendarConditionRange",
                    "startDate": "2026-08-01",
                    "endDate": "2026-08-01",
                    "conditions": {
                        "__typename": "MerlinCalendarConditions",
                        "closedToArrival": False,
                        "closedToDeparture": False,
                        "endDayOfWeek": None,
                        "minNights": 1,
                        "maxNights": 365,
                    },
                }
            ],
        }
    ]


class CalendarParserTests(unittest.TestCase):
    def test_converts_every_level_to_frozen_dataclasses(self):
        result = parse_calendar(calendar_fixture())

        self.assertIsInstance(result[0], pyairbnb.CalendarMonth)
        self.assertIsInstance(result[0].days, tuple)
        self.assertIsInstance(result[0].days[0], pyairbnb.CalendarDay)
        self.assertIsInstance(result[0].days[0].price, pyairbnb.CalendarDayPrice)
        self.assertIsInstance(result[0].condition_ranges, tuple)
        self.assertIsInstance(
            result[0].condition_ranges[0], pyairbnb.CalendarConditionRange
        )
        self.assertIsInstance(
            result[0].condition_ranges[0].conditions,
            pyairbnb.CalendarConditions,
        )
        with self.assertRaises(FrozenInstanceError):
            result[0].month = 9

    def test_accumulates_missing_extra_type_and_value_issues(self):
        payload = calendar_fixture()
        day = payload[0]["days"][0]
        del day["bookable"]
        day["newAirbnbField"] = "new"
        day["available"] = 1
        day["calendarDate"] = "2026-02-30"

        with self.assertRaises(pyairbnb.CalendarContractError) as caught:
            parse_calendar(payload)

        issues = caught.exception.issues
        self.assertEqual(
            {issue.kind for issue in issues},
            {"missing_field", "extra_field", "invalid_type", "invalid_value"},
        )
        self.assertEqual(
            {issue.path for issue in issues},
            {
                "$[0].days[0].bookable",
                "$[0].days[0].newAirbnbField",
                "$[0].days[0].available",
                "$[0].days[0].calendarDate",
            },
        )

    def test_rejects_bool_as_integer_and_integer_as_bool(self):
        payload = calendar_fixture()
        payload[0]["month"] = True
        payload[0]["days"][0]["available"] = 1

        with self.assertRaises(pyairbnb.CalendarContractError) as caught:
            parse_calendar(payload)

        self.assertEqual(
            [issue.kind for issue in caught.exception.issues],
            ["invalid_type", "invalid_type"],
        )

    def test_rejects_unknown_typename_non_null_end_day_and_reversed_range(self):
        payload = calendar_fixture()
        condition_range = payload[0]["conditionRanges"][0]
        condition_range["__typename"] = "UnknownRange"
        condition_range["startDate"] = "2026-08-02"
        condition_range["conditions"]["endDayOfWeek"] = "MONDAY"

        with self.assertRaises(pyairbnb.CalendarContractError) as caught:
            parse_calendar(payload)

        self.assertEqual(len(caught.exception.issues), 3)
        self.assertTrue(
            all(issue.kind == "invalid_value" for issue in caught.exception.issues)
        )

    def test_rejects_invalid_containers_at_root_and_nested_levels(self):
        with self.assertRaises(pyairbnb.CalendarContractError) as root_error:
            parse_calendar({})
        self.assertEqual(root_error.exception.issues[0].kind, "invalid_container")

        payload = calendar_fixture()
        payload[0]["days"] = {}
        with self.assertRaises(pyairbnb.CalendarContractError) as nested_error:
            parse_calendar(payload)
        self.assertEqual(nested_error.exception.issues[0].path, "$[0].days")


class GetCalendarTests(unittest.TestCase):
    def setUp(self):
        self.payload = calendar_fixture()

    @patch("pyairbnb.start.calendar.get")
    def test_raw_mode_returns_the_original_payload_without_validation(self, get):
        self.payload[0]["unknown"] = {"preserved": True}
        get.return_value = self.payload

        result = pyairbnb.get_calendar(
            api_key="key", room_id="123", return_dataclass=False
        )

        self.assertIs(result, self.payload)
        get.assert_called_once()
        self.assertFalse(get.call_args.kwargs["require_calendar_path"])

    @patch("pyairbnb.start.calendar.get")
    def test_default_returns_dataclasses_for_a_valid_contract(self, get):
        get.return_value = self.payload

        result = pyairbnb.get_calendar(api_key="key", room_id="123")

        self.assertIsInstance(result[0], pyairbnb.CalendarMonth)
        self.assertTrue(get.call_args.kwargs["require_calendar_path"])

    @patch("pyairbnb.start.calendar.get")
    def test_default_warns_once_and_returns_the_whole_raw_list(self, get):
        payload = copy.deepcopy(self.payload)
        del payload[0]["days"][0]["bookable"]
        payload[0]["days"][0]["newField"] = 1
        get.return_value = payload

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = pyairbnb.get_calendar(api_key="key", room_id="123")

        self.assertIs(result, payload)
        self.assertEqual(len(caught), 1)
        self.assertIsInstance(caught[0].message, pyairbnb.CalendarContractWarning)
        self.assertEqual(len(caught[0].message.issues), 2)

    @patch("pyairbnb.start.calendar.get")
    def test_strict_mode_raises_structured_contract_error(self, get):
        payload = copy.deepcopy(self.payload)
        payload[0]["month"] = 13
        get.return_value = payload

        with self.assertRaises(pyairbnb.CalendarContractError) as caught:
            pyairbnb.get_calendar(
                api_key="key", room_id="123", on_dataclass_error="raise"
            )

        self.assertEqual(caught.exception.issues[0].path, "$[0].month")

    @patch("pyairbnb.start.api.get")
    @patch("pyairbnb.start.calendar.get")
    def test_invalid_options_fail_before_io(self, calendar_get, api_get):
        for invalid in (1, 0, "yes", None):
            with self.subTest(return_dataclass=invalid), self.assertRaises(TypeError):
                pyairbnb.get_calendar(return_dataclass=invalid)

        with self.assertRaises(ValueError):
            pyairbnb.get_calendar(on_dataclass_error="ignore")

        calendar_get.assert_not_called()
        api_get.assert_not_called()

    @patch("pyairbnb.start.calendar.get", return_value=[])
    def test_explicit_empty_list_is_valid_in_both_modes(self, get):
        self.assertEqual(pyairbnb.get_calendar(api_key="key"), [])
        self.assertEqual(
            pyairbnb.get_calendar(api_key="key", return_dataclass=False), []
        )


class CalendarExtractionTests(unittest.TestCase):
    def test_missing_path_is_an_error_only_for_dataclass_mode(self):
        with self.assertRaises(pyairbnb.CalendarExtractionError) as caught:
            calendarinfo._extract_calendar({}, require_path=True)
        self.assertEqual(
            caught.exception.path,
            "$.data.merlin.pdpAvailabilityCalendar.calendarMonths",
        )
        self.assertEqual(calendarinfo._extract_calendar({}, require_path=False), [])

    def test_explicit_empty_list_is_preserved(self):
        response = {
            "data": {"merlin": {"pdpAvailabilityCalendar": {"calendarMonths": []}}}
        }
        calendar = response["data"]["merlin"]["pdpAvailabilityCalendar"][
            "calendarMonths"
        ]
        self.assertIs(
            calendarinfo._extract_calendar(response, require_path=True), calendar
        )


class GetDetailsCompatibilityTests(unittest.TestCase):
    @patch("pyairbnb.start.host_details.get", return_value={})
    @patch("pyairbnb.start.get_calendar", return_value=[])
    @patch("pyairbnb.start.reviews.get", return_value=[])
    @patch("pyairbnb.start.details.get")
    def test_get_details_requests_raw_calendar(
        self, details_get, reviews_get, get_calendar, host_details_get
    ):
        details_get.return_value = (
            {"host": {"id": "host"}},
            {"product_id": "123", "api_key": "key", "impression_id": "id"},
            Mock(),
        )

        result = pyairbnb.get_details(room_id=123)

        self.assertEqual(result["calendar"], [])
        self.assertFalse(get_calendar.call_args.kwargs["return_dataclass"])


if __name__ == "__main__":
    unittest.main()
