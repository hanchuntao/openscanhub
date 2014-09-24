# -*- coding: utf-8 -*-

"""
logic for spawning tasks

* common options are encapsulated in classes

"""
import os
import logging
import pipes
import shutil
from kobo.django.upload.models import FileUpload
from covscanhub.errata.check import check_analyzers, check_srpm
from covscanhub.errata.models import ScanningSession
from covscanhub.errata.service import return_or_raise
from covscanhub.errata.utils import is_rebase
from covscanhub.other.exceptions import PackageBlacklistedException, PackageNotEligibleException
from covscanhub.scan.service import get_latest_binding
from covscanhub.service.processing import task_has_results

from utils import get_or_fail
from check import check_nvr, check_obsolete_scan, check_build, check_package_is_blocked
from covscanhub.scan.models import Package, Tag, Scan, SCAN_TYPES, ScanBinding, ETMapping, REQUEST_STATES, MockConfig, \
    ClientAnalyzer

from kobo.hub.models import Task, TASK_STATES


logger = logging.getLogger(__name__)


class AbstractScheduler(object):
    """

    """
    def __init__(self, options, scanning_session, *args, **kwargs):
        """ """
        self.task_args = {}
        self.scan_args = {}

        # provided options
        self.options = options
        self.scanning_session = scanning_session

        # {'name': 'foo', 'version':...}
        self.target_nvre_dict = {}

        # required for base & target
        self.package_owner = None
        self.package = None
        self.scan = None
        self.nvr = None
        self.tag = None

        # transaction management
        self.is_stored = False

    def validate_options(self):
        self.package_owner = get_or_fail('package_owner', self.options)
        self.nvr = get_or_fail('target', self.options)
        self.target_nvre_dict = check_nvr(self.nvr)
        check_build(self.nvr)

    def prepare_args(self):
        """ prepare dicts -- arguments for task and scan """
        self.task_args['args'] = {}
        self.task_args['args']['build'] = self.nvr
        self.task_args['args']['scanning_session'] = self.scanning_session.id
        self.scan_args['nvr'] = self.nvr
        self.scan_args['username'] = self.package_owner

    def store(self):
        """
        create and update database models from provided data
        """
        if self.is_stored:
            logger.warning("Trying to call store() second time.")
            return
        logger.debug("Creating scan with args %s", self.scan_args)
        self.scan = Scan.create_scan(**self.scan_args)
        self.task_args['args']['scan_id'] = self.scan.id

    def spawn(self):
        """ """
        raise NotImplementedError()


class BaseScheduler(AbstractScheduler):
    """
    base scans
    """
    def __init__(self, *args, **kwargs):
        """
        prepare base scan

        options = {
            'target': <nvr>
            'package_owner': ''
            'mock_config': '',
        }
        """
        super(BaseScheduler, self).__init__(*args, **kwargs)
        self.mock_config = ''
        self.method = ''
        self.parent_scan = None
        self.validate_options()

    def validate_options(self):
        super(BaseScheduler, self).validate_options()
        self.mock_config = get_or_fail('mock_config', self.options)
        self.package = get_or_fail('package', self.options)
        self.parent_scan = get_or_fail('parent_scan', self.options)
        self.method = get_or_fail('method', self.options)
        self.tag = get_or_fail('tag', self.options)

    def prepare_args(self):
        """ add scan type specific arguments to args dicts """
        super(BaseScheduler, self).prepare_args()
        self.scan_args['scan_type'] = SCAN_TYPES['ERRATA_BASE']
        self.scan_args['package'] = self.package
        self.scan_args['tag'] = self.tag
        self.scan_args['enabled'] = False

        self.task_args['label'] = self.nvr
        self.task_args['method'] = self.method
        self.task_args['args']['mock_config'] = self.mock_config

    def store(self):
        """
        create and update database models from provided data
        """
        if self.is_stored:
            logger.warning("Trying to call store() second time.")
            return
        super(BaseScheduler, self).store()
        # update scan.models.Scan.base
        self.parent_scan.set_base(self.scan)
        self.is_stored = True

    def spawn(self):
        """
        """
        raise RuntimeError('Base scans are not meant to be scheduled directly, use TaskBase.spawn_subtask instead.')

    def get_spawn_subtask_args(self):
        """
            args for `spawn_subtask(method, args, label="")`
        """
        self.store()
        return self.task_args['method'], self.task_args['args'], self.task_args['label']


class AbstractTargetScheduler(AbstractScheduler):
    """
    abstract class for management of targets submitted by CI/release tool
    """

    def __init__(self, *args, **kwargs):
        """
        """
        super(AbstractTargetScheduler, self).__init__(*args, **kwargs)

        # required for target only
        self.base_nvr = None

        self.package_name = ""

        # transaction management
        self.is_spawned = False

        self.validate_options()

    def validate_options(self):
        """ Check if provided options are sane """
        super(AbstractTargetScheduler, self).validate_options()

        self.base_nvr = get_or_fail('base', self.options)
        get_or_fail('release', self.options)
        self.package_name = self.target_nvre_dict['name']

    def prepare_args(self):
        """ prepare dicts -- arguments for task and scan """
        super(AbstractTargetScheduler, self).prepare_args()
        self.task_args['args']['base_nvr'] = self.base_nvr
        self.task_args['owner_name'] = self.options['task_user']
        self.task_args['label'] = self.options['target']
        self.task_args['method'] = self.scanning_session.get_option('method')
        self.task_args['comment'] = self.scanning_session.get_option('comment_template') % {'target': self.options['target']}
        self.task_args['state'] = TASK_STATES['CREATED']
        self.task_args['priority'] = self.scanning_session.get_option('task_priority')

        self.scan_args['enabled'] = True

    def store(self):
        """
        create and update database models from provided data
        """
        if self.is_stored:
            logger.warning("Trying to call store() second time.")
            return
        self.package = Package.objects.get_or_create_by_name(self.package_name)

        self.tag = Tag.objects.for_release_str(self.options['release'])
        self.task_args['args']['mock_config'] = self.tag.mock.name
        self.scan_args['tag'] = self.tag
        self.scan_args['package'] = self.package

        check_package_is_blocked(self.package, self.tag.release)
        check_obsolete_scan(self.package, self.tag.release)

        self.scanning_session.check_capabilities(self.nvr, self.tag.mock.name,
                                                 self.package, self.tag.release)

        super(AbstractTargetScheduler, self).store()

        self.is_stored = True

    def spawn(self):
        """ Spawn tasks """
        if self.is_spawned:
            logger.warning("Trying to call spawn() second time.")
            return
        self.prepare_args()
        self.store()
        task_id = Task.create_task(**self.task_args)
        task = Task.objects.get(id=task_id)
        Task.get_task_dir(task_id, create=True)
        sb = ScanBinding.create_sb(task=task, scan=self.scan)
        task.free_task()

        child = ScanBinding.objects.latest_scan_of_package(self.package, self.tag.release)

        if child and child.scan:
            child_scan = child.scan
            child_scan.parent = self.scan
            child_scan.enabled = False
            child_scan.save()
        self.is_spawned = True
        return sb


class NewPkgScheduler(AbstractTargetScheduler):
    """

    """
    def prepare_args(self):
        """ add scan type specific arguments to args dicts """
        super(NewPkgScheduler, self).prepare_args()
        self.scan_args['scan_type'] = SCAN_TYPES['NEWPKG']


class RebaseScheduler(AbstractTargetScheduler):
    """

    """
    def prepare_args(self):
        """ add scan type specific arguments to args dicts """
        super(RebaseScheduler, self).prepare_args()
        self.scan_args['scan_type'] = SCAN_TYPES['REBASE']


class ClassicScheduler(AbstractTargetScheduler):
    """

    """
    def prepare_args(self):
        """ add scan type specific arguments to args dicts """
        super(ClassicScheduler, self).prepare_args()
        self.scan_args['scan_type'] = SCAN_TYPES['ERRATA']


class ClientDiffScanScheduler(object):
    """
    scheduler for tasks submitted from client -- users
    """
    def __init__(self, consume_options, forward_options, *args, **kwargs):
        """ """
        self.task_args = {}
        self.base_task_args = {}

        # provided options
        self.consume_options = consume_options
        self.forward_options = forward_options

        # required for base & target
        self.nvr = None
        self.base_nvr = None

        self.validate_options()

    def validate_options(self):
        self.user = get_or_fail('task_user', self.consume_options)

        # srpm
        self.target_srpm_name = self.consume_options.get('nvr_srpm', None)
        self.target_build_nvr = self.consume_options.get('nvr_brew_build', None)
        self.target_upload_id = self.consume_options.get('nvr_upload_id', None)
        self.base_srpm_name = self.consume_options.get('base_srpm', None)
        self.base_build_nvr = self.consume_options.get('base_brew_build', None)
        self.base_upload_id = self.consume_options.get('base_upload_id', None)
        target_check_srpm_response = check_srpm(self.target_srpm_name, self.target_upload_id, self.target_build_nvr, self.user)
        if target_check_srpm_response['type'] == 'build':
            self.target_build_kojibin = target_check_srpm_response['koji_bin']
        elif target_check_srpm_response['type'] == 'upload':
            self.target_srpm_path = target_check_srpm_response['srpm_path']
        base_check_srpm_response = check_srpm(self.base_srpm_name, self.base_upload_id, self.base_build_nvr, self.user)
        if base_check_srpm_response['type'] == 'build':
            self.base_build_kojibin = base_check_srpm_response['koji_bin']
        elif base_check_srpm_response['type'] == 'upload':
            self.base_srpm_path = base_check_srpm_response['srpm_path']

        # analyzers
        self.analyzers = get_or_fail('analyzers', self.consume_options)
        self.analyzer_models = check_analyzers(self.analyzers)

        # mock profile
        self.target_mock_config = get_or_fail('nvr_mock', self.consume_options)
        MockConfig.objects.verify_by_name(self.target_mock_config)
        try:
            self.base_mock_config = self.consume_options['base_mock']
        except KeyError:
            self.base_mock_config = self.target_mock_config
        else:
            MockConfig.objects.verify_by_name(self.base_mock_config)

        self.priority = self.consume_options.get('priority', 10)
        self.comment = self.consume_options.get('comment', '')

    def prepare_args(self):
        """ prepare dicts -- arguments for task and scan """
        self.task_args['owner_name'] = self.user
        self.task_args['label'] = self.target_build_nvr or self.target_srpm_name
        self.task_args['method'] = 'VersionDiffBuild'
        self.task_args['comment'] = self.comment
        self.task_args['priority'] = self.priority
        self.task_args['args'] = {}
        if self.target_build_nvr:
            self.task_args['args']['build'] = {
                'nvr': self.target_build_nvr,
                'koji_bin': self.target_build_kojibin,
            }
        else:
            self.task_args['args']['srpm_name'] = self.target_srpm_name
        analyzer_opts = ClientAnalyzer.objects.get_opts(self.analyzer_models)
        self.task_args['args']['analyzers'] = analyzer_opts['analyzers']
        self.task_args['args']['mock_config'] = self.target_mock_config
        self.task_args['args']['csmock_args'] = self.prepare_csmock_args(additional_csmock_args=analyzer_opts['args'])
        # base task args has to be last!
        self.task_args['args']['base_task_args'] = self.prepare_basetask_args()

    def prepare_csmock_args(self, additional_csmock_args=None):
        """ additional_csmock_args are additional arguments as string """
        cov_args = {
            'all': '--all',
            'security': '--security',
            'concurrency': '--concurrency',
            'aggressive': '--aggressiveness-level high',
        }
        csmock_args = {
            'keep_covdata': '--cov-keep-int-dir',
            'warning_level': '-w%s',
        }
        cov_opts = self.forward_options.get('args', [])
        csmock_opts = [additional_csmock_args]
        for opt in self.forward_options:
            if opt in cov_args:
                cov_opts.append(cov_args[opt])
        for opt in self.forward_options:
            if opt in csmock_args:
                csmock_opts.append(csmock_args[opt])
        opts = ""
        if cov_opts:
            opts = "--cov-analyze-opts %s" % (
                pipes.quote(" ".join(cov_opts)),
            )
        if csmock_opts:
            if opts:
                opts = "%s %s" % (opts, " ".join(csmock_opts))
            else:
                opts = " ".join(csmock_opts)
        logger.info("Task opts are '%s'", opts)
        return opts

    def prepare_basetask_args(self):
        label = self.base_build_nvr or self.base_srpm_name
        args = {
            'mock_config': self.base_mock_config,
            'analyzers': self.task_args['args']['analyzers'],
            'csmock_args': self.task_args['args']['csmock_args'],
        }
        if self.base_build_nvr:
            args['build'] = {
                'nvr': self.base_build_nvr,
                'koji_bin': self.base_build_kojibin,
            }
        else:
            args['srpm_name'] = self.base_srpm_name
        return self.task_args['method'], args, label

    def spawn(self):
        """ """
        task_id = Task.create_task(**self.task_args)
        task_dir = Task.get_task_dir(task_id, create=True)
        if self.target_upload_id:
            # move file to task dir, remove upload record and make the task
            # available
            shutil.move(self.target_srpm_path, os.path.join(task_dir, self.target_srpm_name))
            FileUpload.objects.get(id=self.target_upload_id).delete()
        return task_id


def create_diff_task2(consume_opts, forward_opts):
    cs = ClientDiffScanScheduler(consume_opts, forward_opts)
    cs.prepare_args()
    return cs.spawn()


def prepare_base_scan(options, scanning_session):
    """
    subtasks are meant to be created with kobo.worker.task.TaskBase.spawn_subtask
    """
    bs = BaseScheduler(options, scanning_session)
    bs.prepare_args()
    spawn_subtask_args = bs.get_spawn_subtask_args()
    return spawn_subtask_args


class BaseNotValidException(Exception):
    pass


def obtain_base2(base_nvr):
    """
    @param base_nvr - nvr of base to fetch

    returns none if no suitable scan is found
    """
    binding = get_latest_binding(base_nvr)
    logger.debug("Latest binding is '%s'", binding)
    if binding:
        if binding.scan.is_in_progress() and binding.result is None:
            logger.debug("Scan is in progress")
            return binding.scan
        elif binding.result is None:
            # safe handling: there should be result but it's not there actually -- reschedule
            logger.warning("Scan %s is not in progress and has no result.", binding)
            raise BaseNotValidException()
        elif not binding.is_actual():
            # is it scanned with up-to-date analysers?
            logger.debug("Configuration of analysers changed, rescan base")
            raise BaseNotValidException()
        elif not task_has_results(binding.task):
            raise BaseNotValidException()
    else:
        raise BaseNotValidException()
    return binding.scan


def create_errata_scan2(options, etm):
    scanning_session = ScanningSession.objects.get_by_name("ERRATA")
    if options['base'].lower() == 'new_package':
        sb = NewPkgScheduler(options, scanning_session).spawn()
    elif is_rebase(options['base'], options['target']):
        sb = RebaseScheduler(options, scanning_session).spawn()
    else:
        sb = ClassicScheduler(options, scanning_session).spawn()
    etm.set_latest_run(sb)
    sb.scan.set_state_queued()
    return etm


def handle_scan(kwargs):
    """
    Create ET diff scan, handle all possible failures, return dict with
    response, so it can be passed to ET
    """
    response = {}
    message = None

    etm = ETMapping()

    try:
        # ET internal id for the scan record in ET
        etm.et_scan_id = return_or_raise('id', kwargs)
        # ET internal id of the advisory that the build is part of
        etm.advisory_id = return_or_raise('errata_id', kwargs)
        etm.save()

        create_errata_scan2(kwargs, etm)
    except (PackageBlacklistedException, PackageNotEligibleException), ex:
        status = 'INELIGIBLE'
        message = unicode(ex)
    except RuntimeError, ex:
        status = 'ERROR'
        message = u'Unable to submit the scan, error: %s' % ex
    except Exception, ex:
        status = 'ERROR'
        message = unicode(ex)
    else:
        status = 'OK'

    # set status in response dict + in DB
    response['status'] = status
    etm.state = REQUEST_STATES[status]
    etm.save()

    # if there were some error, add it to response & DB
    if message:
        response['message'] = message
        etm.comment = message
        etm.save()

    # this should evaluated as True _always_
    if etm.id:
        response['id'] = etm.id

    return response