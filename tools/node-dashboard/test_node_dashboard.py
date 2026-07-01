#!/usr/bin/env python3

import unittest
from datetime import timedelta
from node_dashboard import parse_cpu_millicores, parse_memory_mi, format_age


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