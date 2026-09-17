import unittest

import fetch_parameter_descriptions as f


class TestExtractDescriptions(unittest.TestCase):
    def test_extracts_description_and_params(self):
        payload = {
            "response": {
                "code": 200,
                "page": {
                    "contents": {
                        "description": "Описание метода.",
                        "params_common_description": "Общий текст.",
                        "params": [{"name": "a", "description": "Параметр А"}, {"name": "b"}],
                    }
                },
            }
        }
        entry = f.extract_descriptions(payload)
        self.assertEqual(entry["description"], "Описание метода.")
        self.assertEqual(entry["params_common_description"], "Общий текст.")
        self.assertEqual(entry["params"], {"a": "Параметр А", "b": ""})

    def test_empty_payload(self):
        entry = f.extract_descriptions({})
        self.assertEqual(entry, {"description": "", "params_common_description": "", "params": {}})


if __name__ == "__main__":
    unittest.main()
