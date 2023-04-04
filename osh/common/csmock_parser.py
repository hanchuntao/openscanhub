"""

csmock python api

{
    "scan":
    {
        "analyzer-version-clang": "3.4",
        "analyzer-version-cppcheck": "1.66",
        "analyzer-version-gcc": "4.9.1",
        "exit-code": 0,
        "host": "quahog",
        "mock-config": "fedora-21-x86_64",
        "store-results-to": "/tmp/asd",
        "time-created": "2014-09-01 18:30:19",
        "time-finished": "2014-09-01 18:38:15",
        "tool": "csmock",
        "tool-args": "'/bin/csmock' '-t' 'cppcheck,gcc,clang' '--no-scan' '-r' 'fedora-21-x86_64' '-o' 'asd' '--force'",
        "tool-version": "csmock-1.3.2.20140829.165742.ge16c941-1.fc21"
    },
    "defects": ""
}
"""

import glob
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request

from kobo.shortcuts import run

RESULT_FILE_JSON = 'scan-results.js'
RESULT_FILE_ERR = 'scan-results.err'
RESULT_FILE_HTML = 'scan-results.html'


logger = logging.getLogger(__name__)


class ResultsExtractor:
    """

    """

    def __init__(self, path, output_dir=None, unpack_in_temp=True):
        """
        path is either path to tarball or to a dir with results
        """
        self.path = path
        if output_dir:
            self.output_dir = output_dir
        elif unpack_in_temp:
            self.output_dir = tempfile.mkdtemp(prefix='csmock-')
        else:
            self.output_dir = os.path.dirname(os.path.expanduser(path))
        self._json_path = None

    @property
    def json_path(self):
        if self._json_path is None:
            self.process()
        if not os.path.exists(self._json_path):
            raise RuntimeError('json results do not exist: %s' % self._json_path)
        return self._json_path

    def extract_tarball(self, exclude_patterns=None):
        """

        """
        exclude_patterns = exclude_patterns or []
        exclude_patterns.append("*debug")  # do not unpack debug dir
        # python 2 does not support lzma
        command = [
            'tar', '-xf', self.path,
            '-C', self.output_dir,
            '--wildcards',
            '--wildcards-match-slash',
        ]
        if exclude_patterns:
            # do NOT quote pattern! it won't work
            command += ['--exclude=%s' % p for p in exclude_patterns]
        logger.debug('Running command %s' % command)
        subprocess.check_call(command)

    def get_json_result_path(self):
        return self.json_path

    def process(self):
        """ untar results if needed """
        if os.path.isdir(self.path):
            self._json_path = os.path.join(self.path, RESULT_FILE_JSON)
        else:
            self.extract_tarball()
            try:
                self._json_path = glob.glob(os.path.join(self.output_dir, '*', RESULT_FILE_JSON))[0]
            except IndexError:
                logger.error("no results (%s) in dir %s", RESULT_FILE_JSON, self.output_dir)
                self._json_path = ''


class CsmockAPI:
    """

    """

    def __init__(self, json_results_path):
        """
        path -- path to results in JSON format
        """
        self.json_results_path = json_results_path
        self._json_result = None

    @property
    def json_result(self):
        if self._json_result is None:
            with open(self.json_results_path) as fp:
                self._json_result = json.load(fp)
        return self._json_result

    def get_defects(self):
        """
        return list of defects: csmock's output is used directly
        """
        return self.json_result['defects']

    def get_scan_metadata(self):
        try:
            return self.json_result['scan']
        except Exception: # noqa
            return {}

    def json(self):
        """
        return result report from csmock as json
        """
        return self.json_result

    def get_analyzers(self):
        """
        return analyzers used for scan, format:

        [{
            'name': 'analyzer1',
            'version': '1.2.3'
        },... ]
        """
        scan = self.get_scan_metadata()
        analyzers = []
        for key, value in scan.items():
            if key.startswith('analyzer-version-'):
                analyzer = {}
                # analyzer-version-[gcc]
                analyzer['name'] = key[17:]
                analyzer['version'] = value
                analyzers.append(analyzer)
        return analyzers


class CsmockRunner:
    """
    context manager class which executes csmock in current process
    """

    def __init__(self, tmpdir=None, create_tmpdir=False):
        if create_tmpdir:
            self.tmpdir = tempfile.mkdtemp()
            self.our_temp_dir = True
        else:
            self.tmpdir = tmpdir
            self.our_temp_dir = False

    def __enter__(self):
        self.tmpdir = tempfile.mkdtemp()
        self.our_temp_dir = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.our_temp_dir:
            try:
                shutil.rmtree(self.tmpdir)
            except OSError:
                # dangling temp dir
                # could be erased with rm -rf self.tmpdir
                pass

    def download_csmock_model(self, model_url, model_name):
        if self.tmpdir:
            model_path = os.path.join(self.tmpdir, model_name)
        else:
            model_path = os.path.join(os.getcwd(), model_name)

        urllib.request.urlretrieve(model_url, model_path)
        return model_path

    def do(self, command, output_path=None, su_user=None, **kwargs):
        """ we are expecting that csmock will produce and output """
        if not command:
            logger.error("no cs* command specified!")
            raise RuntimeError("no cs* command specified!")

        if output_path:
            command += ' -o ' + output_path

        if self.tmpdir:
            if not os.path.isdir(self.tmpdir):
                logger.error('temp dir does not exists!')
                raise RuntimeError('temp dir does not exists!')
            command = f'cd {shlex.quote(self.tmpdir)} && ' + command

        if su_user:
            if self.our_temp_dir:
                inner_cmd = ['chown', f'{su_user}:{su_user}', self.tmpdir]
                try:
                    subprocess.check_call(inner_cmd)
                except subprocess.CalledProcessError:
                    subprocess.check_call(['su', '-', '-c', "%s" % shlex.quote(' '.join(inner_cmd))])
                inner_cmd2 = ['chmod', 'go+rx', self.tmpdir]
                try:
                    subprocess.check_call(inner_cmd2)
                except subprocess.CalledProcessError:
                    subprocess.check_call(['su', '-', su_user, '-c', "%s" % shlex.quote(' '.join(inner_cmd2))])
            command = f'su - {shlex.quote(su_user)} --session-command {shlex.quote(command)}'

        retcode, _ = run(command, stdout=True, can_fail=True, return_stdout=False, buffer_size=2, show_cmd=True, universal_newlines=True, errors="backslashreplace")
        if output_path:
            return output_path, retcode

        if self.tmpdir:
            path = self.tmpdir
        else:
            # search current directory for the results if not tmpdir is set
            path = '.'
        glob_pattern = os.path.join(path, '*.tar.xz')
        glob_results = glob.glob(glob_pattern)

        if 0 == len(glob_results):
            # no .tar.xz found
            logger.info("No tarballs in '%s'", glob_pattern)
            return None, retcode

        # usually we have just one .tar.xz but, if we analyze an usptream
        # tarball which itself has .tar.xz suffix, we need to pick a file
        # ending -results.tar.xz, which appears second in the glob results
        return glob_results[-1], retcode

    def analyze(self, analyzers, srpm_path, profile=None, su_user=None, additional_arguments=None,
                result_filename=None, **kwargs):
        if result_filename is None:
            result_filename = os.path.basename(srpm_path)[:-8]
        if self.tmpdir:
            output_path = os.path.join(self.tmpdir, result_filename + '.tar.xz')
        else:
            output_path = os.path.join(os.getcwd(), result_filename + '.tar.xz')

        if output_path == srpm_path:
            # use a different output path to avoid overwriting the input tarball
            output_path = re.sub('\\.tar\\.xz$', '-results.tar.xz', output_path)

        if profile == "cspodman":
            cmd = "cspodman"
            # XXX: this destroys all containers we have access to, related or not
            cmd += " --force-global-cleanup-on-exit"
        else:
            cmd = "csmock"
            if analyzers:
                cmd += ' -t %s' % (shlex.quote(analyzers))
            if profile:
                cmd += ' -r %s' % shlex.quote(profile)

        if output_path:
            cmd += ' -o %s' % (shlex.quote(output_path))

        if additional_arguments:
            # split/quote/rejoin to avoid shell injection
            try:
                split_args = shlex.split(additional_arguments)

                # starting with Python 3.8, one can use + shlex.join(split_args)
                cmd += ' ' + ' '.join(shlex.quote(arg) for arg in split_args)
            except ValueError as e:
                logger.error("failed to parse csmock arguments: %s" % e)
                return None, 2

        cmd += ' ' + srpm_path
        return self.do(cmd, su_user=su_user, **kwargs)

    def srpm_download_analyze(self, analyzers, srpm_name, srpm_url, profile=None,
                              su_user=None, additional_arguments=None, **kwargs):
        """ download srpm from remote location and analyze it"""
        logger.debug("additional args = %s, kwargs = %s", additional_arguments, kwargs)
        if self.tmpdir:
            srpm_path = os.path.join(self.tmpdir, srpm_name)
        else:
            srpm_path = os.path.join(os.getcwd(), srpm_name)
        urllib.request.urlretrieve(srpm_url, srpm_path)
        return self.analyze(analyzers, srpm_path, profile, su_user, additional_arguments, **kwargs)

    def koji_analyze(self, analyzers, nvr, profile=None, su_user=None,
                     additional_arguments=None, koji_bin="koji", **kwargs):
        if profile == "cspodman":
            return self.analyze(analyzers, nvr, profile, su_user, additional_arguments, result_filename=nvr, **kwargs)

        download_cmd = [koji_bin, "download-build", "--quiet", "--arch=src", nvr]
        try:
            if self.tmpdir:
                subprocess.check_call(download_cmd, cwd=self.tmpdir)
                srpm_path = os.path.join(self.tmpdir, '%s.src.rpm' % nvr)
            else:
                subprocess.check_call(download_cmd)
                srpm_path = os.path.join(os.getcwd(), '%s.src.rpm' % nvr)

        except (OSError, subprocess.CalledProcessError) as ex:
            print(f"command '{download_cmd}' failed to execute: {ex}",
                  file=sys.stderr)
            return (None, 2)

        if not os.path.exists(srpm_path):
            print("downloaded SRPM not found: %s" % srpm_path, file=sys.stderr)
            # `brew win-build` creates build ID without .el8 but SRPM with .el8
            srpm_files = glob.glob(os.path.join(self.tmpdir, '*.src.rpm'))
            if len(srpm_files) == 1:
                srpm_path = srpm_files[0]

        if not os.path.exists(srpm_path):
            print("downloaded SRPM not found: %s" % srpm_path, file=sys.stderr)
            return (None, 2)

        # check that we downloaded an RPM because koji/brew silently download
        # an HTML 404 page instead in case the build has been already deleted
        check_cmd = ['file', '--mime-type', srpm_path]
        p = subprocess.Popen(check_cmd, stdout=subprocess.PIPE)
        mime_type, _ = p.communicate()
        if not re.match(b'^.*application/x-rpm$', mime_type):
            print("unexpected MIME type: %s" % mime_type, file=sys.stderr)
            return (None, 2)

        return self.analyze(analyzers, srpm_path, profile, su_user, additional_arguments, result_filename=nvr, **kwargs)

    def no_scan(self, analyzers, profile=None, su_user=None, additional_arguments=None,
                **kwargs):
        """
        execute csmock command for listing analyzers and versions
        returns path to dir with results
        """
        if self.tmpdir:
            output_path = os.path.join(self.tmpdir, 'output.tar.xz')
        else:
            output_path = os.path.join(os.getcwd(), 'csmock-output')

        if profile == "cspodman":
            cmd = "cspodman"
        else:
            cmd = "csmock"
            cmd += ' -t ' + shlex.quote(analyzers)
            if profile:
                cmd += ' -r %s' % shlex.quote(profile)

        cmd += ' --no-scan'
        if additional_arguments:
            cmd += ' ' + additional_arguments
        return self.do(cmd, output_path=output_path, su_user=su_user, **kwargs)


def unpack_and_return_api(tb_path, in_dir=""):
    """ convenience shortcut """
    in_dir = in_dir or os.path.dirname(tb_path)
    rex = ResultsExtractor(tb_path, output_dir=in_dir, unpack_in_temp=False)
    try:
        return CsmockAPI(rex.json_path)
    except RuntimeError as ex:
        logger.error('Error while creating csmock api: %s', ex)
        return None
