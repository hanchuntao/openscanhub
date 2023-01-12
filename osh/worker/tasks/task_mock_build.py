# -*- coding: utf-8 -*-

from __future__ import print_function

import os
import sys

import six.moves.urllib.parse
from kobo.worker import TaskBase

from covscancommon.csmock_parser import CsmockRunner


class MockBuild(TaskBase):
    enabled = True

    arches = ["noarch"]     # list of supported architectures
    channels = ["default"]  # list of channels
    exclusive = False       # leave False here unless you really know what you're doing
    foreground = False      # if True the task is not forked and runs in the worker process (no matter you run worker without -f)
    priority = 10
    weight = 1.0

    def run(self):
        mock_config = self.args.pop("mock_config")
        build = self.args.pop("build", {})
        srpm_name = self.args.pop("srpm_name", None)
        csmock_args = self.args.pop("csmock_args", None)
        analyzers = self.args.pop('analyzers')
        su_user = self.args.pop('su_user', None)
        custom_model_name = self.args.pop("custom_model_name", None)
        task_url = self.hub.client.task_url(self.task_id)
        result_filename = self.args.pop("result_filename", None)

        with CsmockRunner() as runner:
            if custom_model_name:
                model_url = six.moves.urllib.parse.urljoin(task_url, 'log/%s?format=raw' % custom_model_name)
                model_path = runner.download_csmock_model(model_url, custom_model_name)
                csmock_args += " --cov-custom-model %s" % model_path

            if build:
                results, retcode = runner.koji_analyze(
                    analyzers,
                    build['nvr'],
                    profile=mock_config,
                    additional_arguments=csmock_args,
                    koji_bin=build['koji_bin'],
                    su_user=su_user)
            elif srpm_name:
                url = six.moves.urllib.parse.urljoin(task_url, 'log/%s?format=raw' % srpm_name)
                results, retcode = runner.srpm_download_analyze(
                    analyzers,
                    srpm_name,
                    url,
                    profile=mock_config,
                    additional_arguments=csmock_args,
                    result_filename=result_filename,
                    su_user=su_user)
            else:
                print("No srpm specified", file=sys.stderr)
                self.fail()
            if results is None:
                print("No results available", file=sys.stderr)
                self.fail()
            base_results = os.path.basename(results)
            with open(results, "rb") as f:
                self.hub.upload_task_log(f, self.task_id, base_results)
        # first finish task, then fail if needed, so tarball gets unpacked
        self.hub.worker.finish_task(self.task_id)
        if retcode > 0:
            print("Scanning have not completed successfully (%d)" % retcode, file=sys.stderr)
            self.fail()

    @classmethod
    def notification(cls, hub, conf, task_info):
        hub.worker.email_task_notification(task_info["id"])