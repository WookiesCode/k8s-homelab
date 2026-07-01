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