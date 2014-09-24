"""
Functions related to retrieving paths of tasks results
"""

import os
import logging
from glob import glob

from covscanhub.other.constants import *

from kobo.hub.models import Task


logger = logging.getLogger(__name__)


class TaskResultPaths(object):

    def __init__(self, task):
        """

        """

        self.task = task
        self.task_dir = Task.get_task_dir(task.id, create=True)

    def get_json_added(self):
        return os.path.join(self.task_dir, ERROR_DIFF_FILE)

    def get_json_fixed(self):
        return os.path.join(self.task_dir, FIXED_DIFF_FILE)

    def get_html_added(self):
        return os.path.join(self.task_dir, ERROR_HTML_FILE)

    def get_html_fixed(self):
        return os.path.join(self.task_dir, FIXED_HTML_FILE)

    def get_txt_added(self):
        return os.path.join(self.task_dir, ERROR_TXT_FILE)

    def get_txt_fixed(self):
        return os.path.join(self.task_dir, FIXED_TXT_FILE)

    def get_json_results(self):
        g = glob(os.path.join(self.task_dir, '*', SCAN_RESULTS_FILENAME))
        if len(g) == 1:
            return g[0]
        else:
            logger.warning("json results not found: '%s', task %s", g, self.task)
            raise RuntimeError('json results not found: "%s"' % g)

    def get_tarball_path(self):
        glob_paths = glob(os.path.join(self.task_dir, '*.tar.xz'))
        if len(glob_paths) == 1:
            return glob_paths[0]
        else:
            logger.error("Can't figure out results tarball %s, for task %s", glob_paths, self.task)
            raise RuntimeError("can't find results tarball: '%s'" % glob_paths)
