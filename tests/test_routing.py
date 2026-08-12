import unittest

from graph import route_task


class TaskRoutingTests(unittest.TestCase):
    def assert_route(self, task, expected):
        self.assertEqual(route_task({"task": task}), expected)

    def test_chinese_et1100_documentation_request_routes_to_build_docs(self):
        tasks = (
            "請根據 ET1100 Spec 建立 EtherCAT EEPROM 文件",
            "整理 ET1100 EEPROM 規格成 Markdown",
            "建立 EEPROM docs/read 文件",
        )

        for task in tasks:
            with self.subTest(task=task):
                self.assert_route(task, "build_docs")

    def test_english_markdown_documentation_request_routes_to_build_docs(self):
        self.assert_route(
            "Generate an ET1100 EEPROM documentation draft in Markdown",
            "build_docs",
        )

    def test_slave_discovery_result_check_routes_to_result_check(self):
        self.assert_route(
            "Check whether this Slave Discovery result is correct\n"
            "Slave count: 2\n"
            "Position: 1, Initial ADP: 0x0000, "
            "Configured Address: 0x0001, Vendor ID: 0x000001DD, "
            "Product Code: 0x1041000F",
            "result_check",
        )

    def test_normal_analysis_question_routes_to_analysis(self):
        self.assert_route(
            "What does the EtherCAT Working Counter do?",
            "analysis",
        )


if __name__ == "__main__":
    unittest.main()
