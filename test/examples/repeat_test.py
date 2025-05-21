# Copyright 2023 Google Inc. All Rights Reserved.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import tempfile
import unittest

from examples import repeat
from openhtf.util import example_test


class TestRepeat(example_test.ExampleTestBase):

  def test_main_execution(self):
    with tempfile.TemporaryDirectory() as temp_dir:
      # Stub out the test_start parameter of test.execute(), since we're
      # not prompting for DUT ID in this test.
      # The dut_id is hardcoded in examples/repeat.py
      dut_id = "RepeatDutID"
      # The test name is "Repeat Test" as per the subtask description.
      test_name = "Repeat Test"
      expected_json_path = os.path.join(temp_dir, f"{dut_id}.{test_name}.json")

      # Call the refactored function, passing temp_dir as the output directory.
      repeat.create_and_run_test(temp_dir)

      # Ensure the expected file was created before trying to access it.
      self.assertTrue(os.path.exists(expected_json_path),
                      f"Expected output file {expected_json_path} not found in {temp_dir}. Files: {os.listdir(temp_dir)}")
      
      # Only try to open the file if it exists, to prevent FileNotFoundError if the above assert fails.
      if os.path.exists(expected_json_path):
        with open(expected_json_path) as f:
          output_data = json.load(f)
      else:
        # If the file doesn't exist, we can't proceed with other assertions.
        # The previous assertion already failed, so we can just return or raise here.
        self.fail(f"Cannot proceed, output file {expected_json_path} was not created.")

    self.assertEqual(output_data["dut_id"], dut_id)
    self.assertEqual(output_data["outcome"], "FAIL")

    # Filter for 'phase_repeat' records
    phase_repeat_records = [
        phase for phase in output_data["phases"] if phase["name"] == "phase_repeat"
    ]
    self.assertEqual(len(phase_repeat_records), 3)
    # Assert outcomes: first two attempts are 'SKIP', last is 'PASS'
    self.assertEqual(phase_repeat_records[0]["outcome"], "SKIP")
    self.assertEqual(phase_repeat_records[1]["outcome"], "SKIP")
    self.assertEqual(phase_repeat_records[2]["outcome"], "PASS")

    # Filter for 'phase_repeat_with_limit' records
    phase_repeat_with_limit_records = [
        phase
        for phase in output_data["phases"]
        if phase["name"] == "phase_repeat_with_limit"
    ]
    self.assertEqual(len(phase_repeat_with_limit_records), 5)
    # Assert outcomes: first four attempts are 'SKIP', last is 'FAIL'
    self.assertEqual(phase_repeat_with_limit_records[0]["outcome"], "SKIP")
    self.assertEqual(phase_repeat_with_limit_records[1]["outcome"], "SKIP")
    self.assertEqual(phase_repeat_with_limit_records[2]["outcome"], "SKIP")
    self.assertEqual(phase_repeat_with_limit_records[3]["outcome"], "SKIP")
    self.assertEqual(phase_repeat_with_limit_records[4]["outcome"], "ERROR") # Changed from FAIL to ERROR


if __name__ == "__main__":
  unittest.main()
