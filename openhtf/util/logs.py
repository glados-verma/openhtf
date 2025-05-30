# Copyright 2014 Google Inc. All Rights Reserved.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Logging mechanisms for use in OpenHTF.

Below is an illustration of the tree of OpenHTF loggers:

+---------+
| openhtf |
+---------+
  |
  |  +--------------------------------+
  |--| Framework logs:                |
  |  | - openhtf.core.test_executor   |
  |  | - openhtf.util.threads         |
  |  | - etc. etc.                    |
  |  +--------------------------------+
  |
  |  +----------------------------------+
  +--| Test record logs:                |
     | - openhtf.test_record.<test_uid> |
     +----------------------------------+
       |
       |  +-----------------------------------------------------+
       +--| Test subsystem logs:                                |
          | - openhtf.test_record.<test_uid>.phase.<phase_name> |
          | - openhtf.test_record.<test_uid>.plug.<plug_name>   |
          +-----------------------------------------------------+

All of our logging handlers are attached to the top-level `openhtf` logger. The
other loggers in the tree have their logs propagate up to the top level.

The Test record and subsytem logs do not register with the centralized logging
hierarchy because those loggers cannot be cleaned up; instead, they use a Logger
subclass defined below that overrides the getChild function that directly
instanciates children rather than using the hierarchy.

------------------------------ Test record output ------------------------------

The test record loggers are loggers specific to a running test, with names
prefixed by `openhtf.test_record.<test_uid>`. These logs are saved only to the
record of the test with a matching test_uid. We call the other loggers in the
tree the "framework loggers". Their logs are saved to the records of all
currently running tests.

Test record logs are typically generated by test authors. Often this is done
with the logger attached to the TestApi object passed into test phases, e.g.:

  def MyLoggingPhase(test):
    test.logger.info('My log line.')

To facilitate emitting test record logs outside of test phases (without forcing
the author to pass the logger around), we provide the get_record_logger_for()
function which takes a Test UID and returns a logger, e.g.:

  from openhtf.util import logs

  class MyHelperClass(object):
    def __init__(self)
      self.test_uid = ''

    def MyRandomMethod(self):
      logs.get_record_logger_for(self.test_uid).info(
          'Log this to currently running test.')

  def MyPhase(test, helper):
    helper.MyRandomMethod()

  if __name__ == '__main__':
    helper = MyHelperClass()
    my_test = openhtf.Test(MyPhase.with_args(helper=helper))
    helper.test_uid = my_test.uid
    my_test.execute()

------------------------------ Command-line output -----------------------------

By default, logs are not sent to stdout. This is done to allow test authors to
provide a more streamlined and predictable console interface for test operators.
See the util.console_output module for tools for printing to the CLI.

During development you will probably want to run OpenHTF at a higher verbosity
level in order to view logs and full tracebacks of errors. The verbosity flag
can be used as follows:
  - Default: Logs are not printed.
  - `-v`: Logs are printed at the INFO level and up.
  - `-vv`: Logs are printed at the DEBUG level and up.

Additionally, the --quiet flag and CLI_QUIET variable from the console_output
module will override the verbosity setting and suppress all CLI output.
"""

import collections
import datetime
import logging
import os
import re
import sys
import textwrap

from openhtf.util import argv
from openhtf.util import console_output
from openhtf.util import functions

# The number of v's provided as command line arguments to control verbosity.
# Will be overridden if the ARG_PARSER below parses the -v argument.
CLI_LOGGING_VERBOSITY = 0

ARG_PARSER = argv.module_parser()
ARG_PARSER.add_argument(
    '-v',
    action=argv.StoreRepsInModule,
    target='%s.CLI_LOGGING_VERBOSITY' % __name__,
    help=textwrap.dedent("""\
        CLI logging verbosity. Can be repeated to increase verbosity (i.e. -v,
        -vv, -vvv)."""))

LOGGER_PREFIX = 'openhtf'
RECORD_LOGGER_PREFIX = '.'.join((LOGGER_PREFIX, 'test_record'))
RECORD_LOGGER_RE = re.compile(r'%s\.(?P<test_uid>[^.]*)\.?' %
                              RECORD_LOGGER_PREFIX)
SUBSYSTEM_LOGGER_RE = re.compile(
    r'%s\.[^.]*\.(?P<subsys>plug|phase)\.(?P<id>[^.]*)' % RECORD_LOGGER_PREFIX)

_LOG_ONCE_SEEN = set()


class LogRecord(
    collections.namedtuple('LogRecord', [
        'level',
        'logger_name',
        'source',
        'lineno',
        'timestamp_millis',
        'message',
    ])):
  pass


class HtfTestLogger(logging.Logger):
  """Custom Logger subclass that does not use the logging hierarchy.

  This subclass avoids the logging hierarchy in order to not accumulate loggers
  over the course of the test execution. The Python logging hierarchy is meant
  for module-level loggers; it does not support removing a logger from the
  hierarchy.

  Since this does not use the logging hierarchy, subloggers must be constructed
  using the parent's getChild method.
  """

  def getChild(self, suffix):
    child = HtfTestLogger('.'.join((self.name, suffix)))
    child.parent = self
    return child


def get_record_logger_for(test_uid):
  """Return the child logger associated with the specified test UID."""
  htf_logger = logging.getLogger(RECORD_LOGGER_PREFIX)
  record_logger = HtfTestLogger('.'.join(((RECORD_LOGGER_PREFIX, test_uid))))
  record_logger.parent = htf_logger
  return record_logger


def initialize_record_handler(test_uid, test_record, notify_update):
  """Initialize the record handler for a test.

  For each running test, we attach a record handler to the top-level OpenHTF
  logger. The handler will append OpenHTF logs to the test record, while
  filtering out logs that are specific to any other test run.

  Args:
    test_uid: UID for the test run.
    test_record: The test record for the current test run.
    notify_update: Function that gets called when the test record is updated.
  """
  htf_logger = logging.getLogger(LOGGER_PREFIX)
  htf_logger.addHandler(RecordHandler(test_uid, test_record, notify_update))


def remove_record_handler(test_uid):
  handlers = logging.getLogger(LOGGER_PREFIX).handlers
  for handler in handlers:
    if isinstance(handler, RecordHandler) and handler.test_uid is test_uid:
      handlers.remove(handler)
      break


def log_once(log_func, msg, *args, **kwargs):
  """"Logs a message only once."""
  if msg not in _LOG_ONCE_SEEN:
    log_func(msg, *args, **kwargs)
    # Key on the message, ignoring args. This should fit most use cases.
    _LOG_ONCE_SEEN.add(msg)


class MacAddressLogFilter(logging.Filter):
  """A filter which redacts MAC addresses."""

  MAC_REPLACE_RE = re.compile(
      r"""
        ((?:[\dA-F]{2}:){3})       # 3-part prefix, f8:8f:ca means google
        (?:[\dA-F]{2}(:|\b)){3}    # the remaining octets
        """, re.IGNORECASE | re.VERBOSE)
  MAC_REPLACEMENT = r'\1<REDACTED>'

  def filter(self, record):
    if self.MAC_REPLACE_RE.search(record.getMessage()):
      # Update all the things to have no mac address in them
      if isinstance(record.msg, str):
        record.msg = self.MAC_REPLACE_RE.sub(self.MAC_REPLACEMENT, record.msg)
        record.args = tuple([
            self.MAC_REPLACE_RE.sub(self.MAC_REPLACEMENT, str(arg))
            if isinstance(arg, str) else arg for arg in record.args
        ])
      else:
        record.msg = self.MAC_REPLACE_RE.sub(self.MAC_REPLACEMENT,
                                             record.getMessage())
    return True


# We use one shared instance of this, it has no internal state.
MAC_FILTER = MacAddressLogFilter()


class TestUidFilter(logging.Filter):
  """Exclude logs emitted by the record loggers of other tests."""

  def __init__(self, test_uid):
    super(TestUidFilter, self).__init__()
    self.test_uid = test_uid

  def filter(self, record):
    match = RECORD_LOGGER_RE.match(record.name)

    # Keep framework logs.
    if not match:
      return True

    # Exclude logs emitted by the record loggers of other tests.
    return match.group('test_uid') == self.test_uid


class RecordHandler(logging.Handler):
  """A handler to save logs to an HTF TestRecord."""

  def __init__(self, test_uid, test_record, notify_update):
    super(RecordHandler, self).__init__()
    self.test_uid = test_uid
    self._test_record = test_record
    self._notify_update = notify_update
    self.addFilter(MAC_FILTER)
    self.addFilter(TestUidFilter(test_uid))

  def emit(self, record):
    """Save a logging.LogRecord to our test record.

    Logs carry useful metadata such as the logger name and level information.
    We capture this in a structured format in the test record to enable
    filtering by client applications.

    Args:
      record: A logging.LogRecord to record.
    """
    try:
      message = self.format(record)
      log_record = LogRecord(
          record.levelno,
          record.name,
          os.path.basename(record.pathname),
          record.lineno,
          int(record.created * 1000),
          message,
      )
      self._test_record.add_log_record(log_record)
      self._notify_update()
    except Exception:  # pylint: disable=broad-except
      self.handleError(record)


class CliFormatter(logging.Formatter):
  """Formats log messages for printing to the CLI."""

  def format(self, record):
    """Format the record as tersely as possible but preserve info."""
    super(CliFormatter, self).format(record)
    localized_time = datetime.datetime.fromtimestamp(record.created)
    terse_time = localized_time.strftime(u'%H:%M:%S')
    terse_level = record.levelname[0]
    terse_name = record.name.split('.')[-1]
    match = RECORD_LOGGER_RE.match(record.name)
    if match:
      # Figure out which OpenHTF subsystem the record came from.
      subsys_match = SUBSYSTEM_LOGGER_RE.match(record.name)
      if subsys_match:
        terse_name = '<{subsys}: {id}>'.format(
            subsys=subsys_match.group('subsys'), id=subsys_match.group('id'))
      else:
        # Fall back to using the last five characters of the test UUID.
        terse_name = '<test %s>' % match.group('test_uid')[-5:]
    return '{lvl} {time} {logger} - {msg}'.format(
        lvl=terse_level, time=terse_time, logger=terse_name, msg=record.message)


@functions.call_once
def configure_logging():
  """One-time initialization of loggers. See module docstring for more info."""

  # Define the top-level logger.
  htf_logger = logging.getLogger(LOGGER_PREFIX)
  htf_logger.propagate = False
  htf_logger.setLevel(logging.DEBUG)

  # By default, don't print any logs to the CLI.
  if CLI_LOGGING_VERBOSITY == 0:
    htf_logger.addHandler(logging.NullHandler())
    return

  if CLI_LOGGING_VERBOSITY == 1:
    logging_level = logging.INFO
  else:
    logging_level = logging.DEBUG

  # Configure a handler to print to the CLI.
  cli_handler = logging.StreamHandler(stream=sys.stdout)
  cli_handler.setFormatter(CliFormatter())
  cli_handler.setLevel(logging_level)
  cli_handler.addFilter(MAC_FILTER)
  htf_logger.addHandler(cli_handler)

  # Suppress CLI logging if the --quiet flag is used, or while CLI_QUIET is set
  # in the console_output module.
  cli_handler.addFilter(console_output.CliQuietFilter())
