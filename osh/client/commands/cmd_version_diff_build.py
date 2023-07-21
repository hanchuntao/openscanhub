# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright contributors to the OpenScanHub project.

from kobo.shortcuts import random_string

from osh.client.commands.cmd_build import Base_Build
from osh.client.conf import get_conf

from .shortcuts import (check_analyzers, upload_file, verify_koji_build,
                        verify_mock, verify_scan_profile_exists)


class Version_Diff_Build(Base_Build):
    """analyze 2 SRPMs (base and target) and diff results"""
    enabled = True
    admin = False  # admin type account required

    def options(self):
        super().options()

        self.parser.add_option(
            "--base-config",
            help="specify mock config name for base package"
        )

        self.parser.add_option(
            "--base-nvr",
            help="use a Koji build for base (specified by NVR) instead of a local file"
        )

        self.parser.add_option(
            "--base-srpm",
            help="path to SRPM used as base"
        )

        self.parser.add_option(
            "--srpm",
            help="path to SRPM used as target"
        )

        # Deprecated aliases:
        self.parser.add_option("--base-brew-build", dest="base_nvr",
                               help="DEPRECATED alias for --base-nvr")

    def prepare_task_options(self, args, kwargs):  # noqa: C901
        local_conf = get_conf(self.conf)

        # options
        options = {}

        config = kwargs.pop("config", None)
        base_config = kwargs.pop("base_config", None)
        email_to = kwargs.pop("email_to", [])
        comment = kwargs.pop("comment")
        priority = kwargs.pop("priority")
        base_nvr = kwargs.pop("base_nvr", None)
        nvr = kwargs.pop("nvr", None)
        base_srpm = kwargs.pop("base_srpm", None)
        srpm = kwargs.pop("srpm", None)
        warn_level = kwargs.pop('warn_level', '0')
        analyzers = kwargs.pop('analyzers', '')
        profile = kwargs.pop('profile', None)
        csmock_args = kwargs.pop('csmock_args', None)
        cov_custom_model = kwargs.pop('cov_custom_model', None)

        if comment:
            options['comment'] = comment

        # both bases are specified
        if base_nvr and base_srpm:
            self.parser.error("Choose exactly one option (--base-nvr, --base-srpm), not both of them.")

        # both nvr/targets are specified
        if nvr and srpm:
            self.parser.error("Choose exactly one option (--nvr, --srpm), not both of them.")

        # no package option specified
        if (not base_nvr and not nvr and not srpm and not base_srpm):
            self.parser.error("Please specify both builds or SRPMs.")

        # no base specified
        if not base_nvr and not base_srpm:
            self.parser.error("You haven't specified base.")

        # no nvr/target specified
        if not nvr and not srpm:
            self.parser.error("You haven't specified target.")

        if srpm and not srpm.endswith(".src.rpm"):
            self.parser.error("provided target file doesn't appear to be \
a SRPM")

        # non-negative priority
        if priority is not None and priority < 0:
            self.parser.error("Priority must be a non-negative number!")

        koji_profiles = self.conf.get('KOJI_PROFILES', 'brew,koji')
        if nvr:
            result = verify_koji_build(nvr, koji_profiles)
            if result is not None:
                self.parser.error(result)

        if base_nvr:
            result = verify_koji_build(base_nvr, koji_profiles)
            if result is not None:
                self.parser.error(result)

        if not base_config:
            if config:
                base_config = config
            else:
                base_config = local_conf.get_default_mockconfig()
            if not base_config:
                self.parser.error("You haven't specified mock config, there \
is not even one in your user configuration file \
(~/.config/osh/client.conf) nor in system configuration file \
(/etc/osh/client.conf)")
            print("Mock config for base not specified, using default one: %s" %
                  base_config)

        if not config:
            if base_config:
                config = base_config
            else:
                config = local_conf.get_default_mockconfig()
            if not config:
                self.parser.error("You haven't specified mock config, there \
is not even one in your user configuration file \
(~/.config/osh/client.conf) nor in system configuration file \
(/etc/osh/client.conf)")
            print("Mock config for target not specified, using default: %s" %
                  config)

        result = verify_mock(base_config, self.hub)
        if result is not None:
            self.parser.error(result)

        options['base_mock_config'] = base_config

        result = verify_mock(config, self.hub)
        if result is not None:
            self.parser.error(result)

        options['mock_config'] = config

        # end of CLI options handling

        if email_to:
            options["email_to"] = email_to
        if priority is not None:
            options["priority"] = priority

        if warn_level:
            options['warning_level'] = warn_level
        if analyzers:
            try:
                check_analyzers(self.hub, analyzers)
            except RuntimeError as ex:
                self.parser.error(str(ex))
            options['analyzers'] = analyzers
        if profile:
            result = verify_scan_profile_exists(self.hub, profile)
            if result is not None:
                self.parser.error(result)
            options['profile'] = profile

        if nvr:
            options["brew_build"] = nvr
        else:
            target_dir = random_string(32)
            upload_id, err_code, err_msg = upload_file(self.hub, srpm,
                                                       target_dir, self.parser)
            options["upload_id"] = upload_id

        if base_nvr:
            options["base_brew_build"] = base_nvr
        else:
            target_dir = random_string(32)
            upload_id, err_code, err_msg = upload_file(self.hub, base_srpm,
                                                       target_dir, self.parser)
            options["base_upload_id"] = upload_id

        if csmock_args:
            options['csmock_args'] = csmock_args
        if cov_custom_model:
            target_dir = random_string(32)
            upload_model_id, err_code, err_msg = upload_file(self.hub,
                                                             cov_custom_model,
                                                             target_dir,
                                                             self.parser)
            options["upload_model_id"] = upload_model_id

        return options

    def submit_task(self, options):
        return self.hub.scan.create_user_diff_task(options, {})
