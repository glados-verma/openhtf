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

from examples import checkpoints
from openhtf.util import example_test


class TestCheckpoints(example_test.ExampleTestBase):

  def test_main_execution(self):
    with tempfile.TemporaryDirectory() as temp_dir:
      # Call the refactored function, passing temp_dir as the output directory.
      checkpoints.create_and_run_test(temp_dir)

      expected_json_path = os.path.join(temp_dir, 'checkpoints.json')
      self.assertTrue(os.path.exists(expected_json_path),
                      f"Expected output file {expected_json_path} not found in {temp_dir}. Files: {os.listdir(temp_dir)}")

      with open(expected_json_path) as f:
        output_data = json.load(f)

    self.assertEqual(output_data['dut_id'], 'MyDutId')
    self.assertEqual(output_data['outcome'], 'FAIL')

    # Verify failing_phase
    failing_phase_data = self.get_phase_by_name(output_data, 'failing_phase')
    self.assertIsNotNone(failing_phase_data, "Phase 'failing_phase' not found.")
    self.assertEqual(failing_phase_data['outcome'], 'FAIL')
    self.assertEqual(failing_phase_data['measurements']['fixed_time']['outcome'], 'FAIL')

    # Verify long_running_phase was not executed
    executed_phase_names = [phase['name'] for phase in output_data['phases']]
    self.assertNotIn('long_running_phase', executed_phase_names,
                     "Phase 'long_running_phase' should not have been executed.")


if __name__ == "__main__":
  unittest.main()
