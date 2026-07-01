#!/usr/bin/env python3

import unittest
from datetime import timedelta
from node_dashboard import parse_cpu_millicores, parse_memory_mi, format_age, build_event_reason_lookup


class TestParseCpuMillicores(unittest.TestCase):
    def test_millicore_string(self):
        self.assertEqual(parse_cpu_millicores("168m"), 168)

    def test_whole_core_string(self):
        self.assertEqual(parse_cpu_millicores("1"), 1000)

    def test_zero_millicores(self):
        self.assertEqual(parse_cpu_millicores("0m"), 0)


if __name__ == "__main__":
    unittest.main()

class TestParseMemoryMi(unittest.TestCase):
    def test_mebibytes(self):
        self.assertEqual(parse_memory_mi("2745Mi"), 2745)

    def test_gibibytes(self):
        self.assertEqual(parse_memory_mi("2Gi"), 2048)

    def test_kibibytes(self):
        self.assertEqual(parse_memory_mi("2048Ki"), 2)

    def test_unrecognized_unit(self):
        self.assertEqual(parse_memory_mi("500Xi"), 0)

class TestFormatAge(unittest.TestCase):
    def test_hours_minutes_seconds(self):
        age = timedelta(hours=2, minutes=15, seconds=3)
        self.assertEqual(format_age(age), "2h 15m 3s ago")

    def test_minutes_seconds_only(self):
        age = timedelta(minutes=15, seconds=3)
        self.assertEqual(format_age(age), "15m 3s ago")

    def test_seconds_only(self):
        age = timedelta(seconds=45)
        self.assertEqual(format_age(age), "45s ago")

    def test_zero_duration(self):
        age = timedelta(seconds=0)
        self.assertEqual(format_age(age), "0s ago")

class TestBuildEventReasonLookup(unittest.TestCase):
    def make_event(self, event_type, reason, pod_name, namespace, timestamp):
        """Helper to build a fake event dict matching kubectl's shape."""
        return {
            "type": event_type,
            "reason": reason,
            "count": 1,
            "lastTimestamp": timestamp,
            "involvedObject": {
                "name": pod_name,
                "namespace": namespace,
            },
        }

    def test_single_warning_event(self):
        events = [
            self.make_event("Warning", "BackOff", "my-pod", "default", "2026-06-30T10:00:00Z"),
        ]
        lookup = build_event_reason_lookup(events)
        self.assertEqual(lookup["default/my-pod"]["reason"], "BackOff")

    def test_normal_events_are_skipped(self):
        events = [
            self.make_event("Normal", "Started", "my-pod", "default", "2026-06-30T10:00:00Z"),
        ]
        lookup = build_event_reason_lookup(events)
        self.assertEqual(lookup, {})

    def test_missing_timestamp_is_skipped(self):
        event = self.make_event("Warning", "BackOff", "my-pod", "default", None)
        lookup = build_event_reason_lookup([event])
        self.assertEqual(lookup, {})

    def test_keeps_most_recent_event(self):
        events = [
            self.make_event("Warning", "BackOff", "my-pod", "default", "2026-06-30T08:00:00Z"),
            self.make_event("Warning", "FailedMount", "my-pod", "default", "2026-06-30T10:00:00Z"),
        ]
        lookup = build_event_reason_lookup(events)
        self.assertEqual(lookup["default/my-pod"]["reason"], "FailedMount")