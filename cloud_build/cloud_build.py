#!/usr/bin/python3

from typing import Dict, List, Set, Tuple, Union, Optional
from pathlib import Path

import contextlib
import datetime
import fcntl
import logging
import os
import re
import shutil
import string
import subprocess
import time

import yaml

import cloud_build.image_tests
import cloud_build.rename

PROG = 'cloud-build'

# types
PathLike = Union[Path, str]


class Error(Exception):
    pass


class BuildError(Error):
    def __init__(self, target: str, arch: str):
        self.target = target
        self.arch = arch

    def __str__(self) -> str:
        return f'Fail building of {self.target} {self.arch}'


class MultipleBuildErrors(Error):
    def __init__(self, build_errors: List[BuildError]):
        self.build_errors = build_errors

    def __str__(self) -> str:
        s = 'Fail building of the following targets:\n'
        s += '\n'.join(f'  {be.target} {be.arch}' for be in self.build_errors)
        return s


class CB:
    """class for building cloud images"""

    def __init__(
            self,
            config: str,
            *,
            data_dir: Optional[PathLike] = None,
            tasks: Optional[dict[str, List[str]]] = None,
            built_images_dir: Optional[PathLike] = None,
            config_override: Optional[Dict] = None,
    ) -> None:
        self.initialized = False
        self._save_cwd = os.getcwd()
        self.parse_config(config, config_override)
        if tasks is None:
            self.tasks = {}
        else:
            self.tasks = tasks

        if not data_dir:
            data_dir = (Path(self.expand_path(os.getenv('XDG_DATA_HOME',
                                                        '~/.local/share')))
                        / f'{PROG}')
        else:
            data_dir = Path(data_dir).absolute()
        self.data_dir = data_dir

        self.checksum_command = 'sha256sum'

        if built_images_dir:
            self._images_dir = Path(built_images_dir).absolute()
            self.no_build = True
        else:
            self._images_dir = data_dir / 'images'
            self.no_build = False
        self.work_dir = data_dir / 'work'
        self.out_dir = data_dir / 'out'

        self.service_default_state = 'enabled'
        self.created_scripts: List[Path] = []
        self._build_errors: List[BuildError] = []

        self.ensure_dirs()
        logging.basicConfig(
            filename=f'{data_dir}/{PROG}.log',
            format='%(levelname)s:%(asctime)s - %(message)s',
        )
        self.log = logging.getLogger(PROG)
        self.log.setLevel(self.log_level)
        self.ensure_run_once()
        self.info(f'Start {PROG}')
        self.initialized = True

    def __del__(self) -> None:
        if not self.initialized:
            if getattr(self, 'lock_file', False):
                self.lock_file.close()
            return

        def unlink(path) -> None:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

        for name in self.created_scripts:
            unlink(name)
        unlink(self.work_dir / f'mkimage-profiles/conf.d/{PROG}.mk')

        os.chdir(self._save_cwd)
        try:
            self.info(f'Finish {PROG}')
        except FileNotFoundError:
            pass
        self.lock_file.close()

    @property
    def _remote_formaters(self) -> Set[str]:
        return {
            key
            for tup in string.Formatter().parse(self._remote)
            if (key := tup[1]) is not None
        }

    @property
    def is_remote_arch(self) -> bool:
        return 'arch' in self._remote_formaters

    @property
    def is_remote_branch(self) -> bool:
        return 'branch' in self._remote_formaters

    def images_dirs_remotes_list(self) -> List[Tuple[Path, str]]:
        images_dirs_list = []
        images_dir = self._images_dir
        if self.is_remote_branch:
            for branch in self.branches:
                if self.is_remote_arch:
                    for arch in self.arches_by_branch(branch):
                        remote = self._remote.format(branch=branch, arch=arch)
                        pair = (images_dir / branch / arch, remote)
                        images_dirs_list.append(pair)
                else:
                    remote = self._remote.format(branch=branch)
                    images_dirs_list.append((images_dir / branch, remote))
        else:
            if self.is_remote_arch:
                for arch in self.all_arches:
                    remote = self._remote.format(arch=arch)
                    images_dirs_list.append((images_dir / arch, remote))
            else:
                images_dirs_list.append((images_dir, self._remote))

        return images_dirs_list

    def images_dirs_list(self) -> List[Path]:
        return [pair[0] for pair in self.images_dirs_remotes_list()]

    def images_dir(self, branch: str, arch: str) -> Path:
        images_dir = self._images_dir
        if self.is_remote_branch:
            images_dir = images_dir / branch
        if self.is_remote_arch:
            images_dir = images_dir / arch
        return images_dir

    def expand_path(self, path: PathLike):
        result = os.path.expanduser(os.path.expandvars(path))
        if isinstance(path, Path):
            return Path(result)
        else:
            return result

    def ensure_run_once(self) -> None:
        self.lock_file = open(self.data_dir / f'{PROG}.lock', 'w')

        try:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:  # already locked
            dd = self.data_dir
            msg = f'Program {PROG} already running in `{dd}` directory'
            self.error(msg)

    @contextlib.contextmanager
    def pushd(self, new_dir):
        previous_dir = os.getcwd()
        self.debug(f'Pushd to {new_dir}')
        os.chdir(new_dir)
        yield
        self.debug(f'Popd from {new_dir}')
        os.chdir(previous_dir)

    def parse_config(
        self,
        config: str,
        override: Optional[Dict] = None
    ) -> None:
        if override is None:
            override = {}

        try:
            with open(config) as f:
                cfg = yaml.safe_load(f)
        except OSError as e:
            msg = f'Could not read config file `{e.filename}`: {e.strerror}'
            raise Error(msg)

        def lazy_get_raises(key):
            if key in override:
                return override[key]
            else:
                return cfg[key]

        self.mkimage_profiles_git = self.expand_path(
            cfg.get('mkimage_profiles_git', '')
        )

        self.log_level = getattr(logging, cfg.get('log_level', 'INFO').upper())

        self._repository_url = cfg.get('repository_url',
                                       'copy:///space/ALT/{branch}')

        self._image_repo = cfg.get('image_repo')

        self.try_build_all = cfg.get('try_build_all', False)

        self.no_delete = cfg.get('no_delete', True)

        self.bad_arches = cfg.get('bad_arches', [])

        self.external_files = cfg.get('external_files')
        if self.external_files:
            self.external_files = self.expand_path(Path(self.external_files))

        rebuild_after = override.get(
            'rebuild_after',
            cfg.get('rebuild_after', {'days': 1}),
        )
        try:
            self.rebuild_after = datetime.timedelta(**rebuild_after)
        except TypeError as e:
            m = re.match(r"'([^']+)'", str(e))
            if m:
                arg = m.groups()[0]
                raise Error(f'Invalid key `{arg}` passed to rebuild_after')
            else:
                raise

        self._packages = cfg.get('packages', {})
        self._services = cfg.get('services', {})
        self._scripts = cfg.get('scripts', {})

        self._after_sync_commands = cfg.get('after_sync_commands', [])

        self.key = override.get('key', cfg.get('key'))
        if isinstance(self.key, int):
            self.key = '{:X}'.format(self.key)

        try:
            self._remote = self.expand_path(lazy_get_raises('remote'))
            self._images = lazy_get_raises('images')
            self._branches = lazy_get_raises('branches')
            for _, branch in self._branches.items():
                branch['arches'] = {k: {} if v is None else v
                                    for k, v in branch['arches'].items()}
        except KeyError as e:
            msg = f'Required parameter {e} does not set in config'
            raise Error(msg)

    def info(self, msg: str) -> None:
        self.log.info(msg)

    def debug(self, msg: str) -> None:
        self.log.debug(msg)

    def error(self, arg: Union[str, Error]) -> None:
        if isinstance(arg, Error):
            err = arg
        else:
            err = Error(arg)
        self.log.error(err)
        raise err

    def remote(self, branch: str, arch: str) -> str:
        # import pdb; pdb.set_trace()
        return self._remote.format(branch=branch, arch=arch)

    def repository_url(self, branch: str, arch: str) -> str:
        url = self._branches[branch]['arches'][arch].get('repository_url')
        if url is None:
            url = self._branches[branch].get('repository_url',
                                             self._repository_url)
        return url.format(branch=branch, arch=arch)

    def image_repo(self, branch: str, arch: str) -> str:
        url = self._branches[branch]['arches'][arch].get('image_repo')
        if url is None:
            url = self._branches[branch].get('image_repo',
                                             self._image_repo)

        if url is not None:
            url = url.format(branch=branch, arch=arch)

        return url

    def call(
        self,
        cmd: List[str],
        *,
        stdout_to_file: str = '',
        fail_on_error: bool = True,
    ) -> None:
        def maybe_fail(string: str, rc: int) -> None:
            if fail_on_error:
                if rc != 0:
                    msg = 'Command `{}` failed with {} return code'.format(
                        string,
                        rc,
                    )
                    self.error(msg)

        # just_print = True
        just_print = False
        string = ' '.join(cmd)
        self.debug(f'Call `{string}`')
        if just_print:
            print(string)
        else:
            if stdout_to_file:
                # TODO rewrite using subprocess.run
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
                rc = p.wait()
                maybe_fail(string, rc)
                # TODO rewrite by passing f as stdout value
                with open(stdout_to_file, 'w') as f:
                    if p.stdout:
                        f.write(p.stdout.read().decode())
                    if p.stdout is not None:
                        p.stdout.close()
            else:
                # TODO rewrite using subprocess.run
                rc = subprocess.call(cmd)
                maybe_fail(string, rc)

    def ensure_dirs(self) -> None:
        for attr in dir(self):
            if attr.endswith('_dir'):
                value = getattr(self, attr)
                if isinstance(value, str) or isinstance(value, os.PathLike):
                    os.makedirs(value, exist_ok=True)

        for images_dir in self.images_dirs_list():
            os.makedirs(images_dir, exist_ok=True)

    def generate_apt_files(self) -> None:
        apt_dir = self.work_dir / 'apt'
        os.makedirs(apt_dir, exist_ok=True)
        for branch in self.branches:
            for arch in self.arches_by_branch(branch):
                repo = self.repository_url(branch, arch)
                with open(f'{apt_dir}/apt.conf.{branch}.{arch}', 'w') as f:
                    apt_conf = f'''
Dir::Etc::main "/dev/null";
Dir::Etc::parts "/var/empty";
Dir::Etc::SourceList "{apt_dir}/sources.list.{branch}.{arch}";
Dir::Etc::SourceParts "/var/empty";
Dir::Etc::preferences "/dev/null";
Dir::Etc::preferencesparts "/var/empty";
'''.lstrip()
                    f.write(apt_conf)

                with open(f'{apt_dir}/sources.list.{branch}.{arch}', 'w') as f:
                    sources_list = f'rpm {repo} {arch} classic\n'
                    if arch not in self.bad_arches:
                        sources_list += f'rpm {repo} noarch classic\n'
                    for task in self.tasks.get(branch.lower(), []):
                        tr = 'http://git.altlinux.org'
                        sources_list += f'rpm {tr} repo/{task}/{arch} task\n'
                    f.write(sources_list)

    def escape_branch(self, branch: str) -> str:
        return re.sub(r'\.', '_', branch)

    def ensure_mkimage_profiles(self) -> None:
        """Checks that mkimage-profiles exists or clones it"""

        def add_recipe(variable: str, value: str) -> str:
            return f'\n\t@$(call add,{variable},{value})'

        url = self.mkimage_profiles_git
        if url == '':
            url = (
                'git://'
                + 'git.altlinux.org/'
                + 'people/antohami/packages/mkimage-profiles.git'
            )
        os.chdir(self.work_dir)
        if os.path.isdir('mkimage-profiles'):
            with self.pushd('mkimage-profiles'):
                self.info('Updating mkimage-profiles')
                self.call(['git', 'pull', '--ff-only'], fail_on_error=True)
        else:
            self.info('Downloading mkimage-profiles')
            self.call(['git', 'clone', url, 'mkimage-profiles'])

        # create file with proper brandings
        with self.pushd('mkimage-profiles'):
            with open(f'conf.d/{PROG}.mk', 'w') as f:
                for image in self.images:
                    target = self.target_by_image(image)
                    for branch in self.branches:
                        ebranch = self.escape_branch(branch)

                        prerequisites = [target]
                        prerequisites.extend(
                            self.prerequisites_by_branch(branch)
                        )
                        prerequisites.extend(
                            self.prerequisites_by_image(image)
                        )
                        prerequisites_s = ' '.join(prerequisites)

                        recipes = []
                        branding = self.branding(image, branch)
                        if branding:
                            branding = f'\n\t@$(call set,BRANDING,{branding})'
                            recipes.append(branding)

                        for package in self.packages(image, branch):
                            recipes.append(
                                add_recipe(
                                    'BASE_PACKAGES',
                                    package))

                        for service in self.enabled_services(image, branch):
                            recipes.append(
                                add_recipe(
                                    'DEFAULT_SERVICES_ENABLE',
                                    service))
                        for service in self.disabled_services(image, branch):
                            recipes.append(
                                add_recipe(
                                    'DEFAULT_SERVICES_DISABLE',
                                    service))

                        recipes_s = ''.join(recipes)

                        rule = f'''
{target}_{ebranch}: {prerequisites_s}; @:{recipes_s}
'''.strip()
                        print(rule, file=f)

        self.generate_apt_files()

    @property
    def branches(self) -> List[str]:
        return list(self._branches.keys())

    def arches_by_branch(self, branch: str) -> List[str]:
        return list(self._branches[branch]['arches'].keys())

    @property
    def all_arches(self) -> List[str]:
        arches: Set[str] = set()
        for branch in self.branches:
            arches |= set(self.arches_by_branch(branch))
        return list(arches)

    def prerequisites_by_branch(self, branch: str) -> List[str]:
        return self._branches[branch].get('prerequisites', [])

    @property
    def images(self) -> List[str]:
        return list(self._images.keys())

    def kinds_by_image(self, image: str) -> List[str]:
        return self._images[image]['kinds']

    def convert_size(self, size: str) -> Optional[str]:
        result = None
        multiplier = {
            '': 1,
            'k': 2 ** 10,
            'm': 2 ** 20,
            'g': 2 ** 30,
        }
        match = re.match(
            r'^(?P<num> \d+(:?.\d+)? ) (?P<suff> [kmg] )?$',
            size,
            re.IGNORECASE | re.VERBOSE,
        )
        if not match:
            self.error('Bad size format')
        else:
            num = float(match.group('num'))
            suff = match.group('suff')
            if suff is None:
                suff = ''
            mul = multiplier[str.lower(suff)]
            result = str(round(num * mul))

        return result

    def size_by_image(self, image: str) -> Optional[str]:
        size = self._images[image].get('size')
        if size is not None:
            size = self.convert_size(str(size))
        return size

    def target_by_image(self, image: str) -> str:
        return self._images[image]['target']

    def prerequisites_by_image(self, image: str) -> List[str]:
        return self._images[image].get('prerequisites', [])

    def tests_by_image(self, image: str) -> List[Dict]:
        return self._images[image].get('tests', [])

    def scripts_by_image(self, image: str) -> Dict[str, str]:
        scripts = {}
        for name, value in self._scripts.items():
            number = value.get('number')
            if (
                value.get('global', False)
                and name not in self._images[image].get('no_scripts', [])
                or name in self._images[image].get('scripts', [])
            ):
                if number is not None:
                    if isinstance(number, int):
                        number = f'{number:02}'
                    name = f'{number}-{name}'
                scripts[name] = value['contents']
        return scripts

    def skip_arch(self, image: str, arch: str) -> bool:
        return arch in self._images[image].get('exclude_arches', [])

    def skip_branch(self, image: str, branch: str) -> bool:
        return branch in self._images[image].get('exclude_branches', [])

    def get_items(
        self,
        data: Dict,
        image: str,
        branch: str,
        state_re: str = None,
        default_state: str = None,
    ) -> List[str]:
        items = []

        if state_re is None:
            state_re = ''
        if default_state is None:
            default_state = state_re

        for item, constraints in data.items():
            if constraints is None:
                constraints = {}

            if (
                image in constraints.get('exclude_images', [])
                or branch in constraints.get('exclude_branches', [])
            ):
                continue

            # Empty means no constraint: e.g. all images
            images = constraints.get('images', [image])
            branches = constraints.get('branch', [branch])

            state = constraints.get('state', default_state)

            if (
                image in images
                and branch in branches
                and re.match(state_re, state)
            ):
                items.append(item)

        return items

    def branding(self, image: str, branch: str) -> str:
        if (image_branding := self._images[image].get('branding')) is not None:
            return image_branding

        return self._branches[branch].get('branding', '')

    def packages(self, image: str, branch: str) -> List[str]:
        image_packages = self._images[image].get('packages', [])
        return image_packages + self.get_items(self._packages, image, branch)

    def enabled_services(self, image: str, branch: str) -> List[str]:
        image_services = self._images[image].get('services_enabled', [])
        return image_services + self.get_items(
            self._services,
            image,
            branch,
            'enabled?',
            self.service_default_state,
        )

    def disabled_services(self, image: str, branch: str) -> List[str]:
        image_services = self._images[image].get('services_disabled', [])
        return image_services + self.get_items(
            self._services,
            image,
            branch,
            'disabled?',
            self.service_default_state,
        )

    def build_failed(self, target, arch):
        if self.try_build_all:
            self._build_errors.append(BuildError(target, arch))
        else:
            self.error(BuildError(target, arch))

    def should_rebuild(self, tarball):
        if not os.path.exists(tarball):
            rebuild = True
        else:
            lived = time.time() - os.path.getmtime(tarball)
            delta = datetime.timedelta(seconds=lived)
            rebuild = delta > self.rebuild_after
            if rebuild:
                os.unlink(tarball)
        return rebuild

    def build_tarball(
        self,
        target: str,
        branch: str,
        arch: str,
        kind: str,
        size: str = None,
    ) -> Optional[Path]:
        target = f'{target}_{self.escape_branch(branch)}'
        image = re.sub(r'.*/', '', target)
        full_target = f'{target}.{kind}'
        tarball_name = f'{image}-{arch}.{kind}'
        tarball_path = self.out_dir / tarball_name
        result: Optional[Path] = tarball_path
        apt_dir = self.work_dir / 'apt'
        with self.pushd(self.work_dir / 'mkimage-profiles'):
            if not self.should_rebuild(tarball_path):
                self.info(f'Skip building of {full_target} {arch}')
            else:
                image_repo = self.image_repo(branch, arch)
                cmd = [
                    'make',
                    f'APTCONF={apt_dir}/apt.conf.{branch}.{arch}',
                    f'ARCH={arch}',
                    f'BRANCH={branch}',
                    f'IMAGE_OUTDIR={self.out_dir}',
                    f'IMAGE_OUTFILE={tarball_name}',
                ]
                if image_repo is not None:
                    cmd.append(f'REPO={image_repo}')
                if size is not None:
                    cmd.append(f'VM_SIZE={size}')
                cmd.append(full_target)
                self.info(f'Begin building of {full_target} {arch}')
                self.call(cmd, fail_on_error=False)

                if os.path.exists(tarball_path):
                    self.info(f'End building of {full_target} {arch}')
                else:
                    result = None
                    self.build_failed(full_target, arch)

        return result

    def image_path(
        self,
        image: str,
        branch: str,
        arch: str,
        kind: str
    ) -> Path:
        name = f'alt-{branch.lower()}-{image}-{arch}.{kind}'
        rename_dict = self._images[image].get('rename', {})
        if rename_dict:
            name = cloud_build.rename.rename(rename_dict, name)
        path = self.images_dir(branch, arch) / name
        return path

    def copy_image(self, src: Path, dst: Path, *, rewrite=False) -> None:
        if rewrite and dst.exists():
            os.unlink(dst)
        os.link(src, dst)

    def clear_images_dir(self):
        for images_dir in self.images_dirs_list():
            for path in images_dir.iterdir():
                if path.is_file():
                    os.unlink(path)
                else:
                    shutil.rmtree(path)

    def remove_old_tarballs(self):
        with self.pushd(self.out_dir):
            for tb in os.listdir():
                lived = time.time() - os.path.getmtime(tb)
                delta = datetime.timedelta(seconds=lived)
                if delta > self.rebuild_after:
                    os.unlink(tb)

    def ensure_scripts(self, image):
        for name in self.created_scripts:
            os.unlink(name)

        self.created_scripts = []

        target_type = re.sub(r'(?:(\w+)/)?.*', r'\1',
                             self.target_by_image(image))
        if not target_type:
            target_type = 'distro'
        scripts_path = (
            self.work_dir
            / 'mkimage-profiles'
            / 'features.in'
            / f'build-{target_type}'
            / 'image-scripts.d'
        )
        for name, content in self.scripts_by_image(image).items():
            script = scripts_path / name
            self.created_scripts.append(script)
            script.write_text(content)
            os.chmod(script, 0o755)

    def ensure_build_success(self) -> None:
        if self._build_errors:
            self.error(MultipleBuildErrors(self._build_errors))

    def create_images(self, no_tests: bool = False) -> None:
        if self.no_build:
            msg = 'Trying to build images when build stage should be skipped'
            self.error(msg)
        self.clear_images_dir()
        self.ensure_mkimage_profiles()

        for branch in self.branches:
            for image in self.images:
                if self.skip_branch(image, branch):
                    continue
                self.ensure_scripts(image)
                target = self.target_by_image(image)
                for arch in self.arches_by_branch(branch):
                    if self.skip_arch(image, arch):
                        continue

                    for kind in self.kinds_by_image(image):
                        size = self.size_by_image(image)
                        tarball = self.build_tarball(
                            target, branch, arch, kind, size
                        )
                        if tarball is None:
                            continue

                        image_path = self.image_path(image, branch, arch, kind)
                        self.copy_image(tarball, image_path)
                        if not no_tests:
                            for test in self.tests_by_image(image):
                                self.info(f'Test {image} {branch} {arch}')
                                if not cloud_build.image_tests.test(
                                    image=image_path,
                                    branch=branch,
                                    arch=arch,
                                    **test,
                                ):
                                    self.error(f'Test for {image} failed')

        self.ensure_build_success()
        self.remove_old_tarballs()

    def copy_external_files(self):
        if not self.external_files:
            return

        for branch in os.listdir(self.external_files):
            if branch not in self.branches:
                self.error(f'Unknown branch {branch} in external_files')
            arches = self.arches_by_branch(branch)
            for arch in os.listdir(self.external_files / branch):
                if arch not in arches:
                    self.error(f'Unknown arch {arch} in external_files')
                with self.pushd(self.external_files / branch / arch):
                    for image in os.listdir():
                        msg = f'Copy external file {image} in {branch}/{arch}'
                        self.info(msg)
                        self.copy_image(
                            image,
                            self.images_dir(branch, arch) / image,
                            rewrite=True,
                        )

    def sign(self):
        if self.key is None:
            self.error('Pass key to config file for sign')

        sum_file = self.checksum_command.upper()
        for images_dir in self.images_dirs_list():
            with self.pushd(images_dir):
                files = [f
                         for f in os.listdir()
                         if not f.startswith(sum_file)]
                string = ','.join(files)

                cmd = [self.checksum_command] + files
                self.info(f'Calculate checksum of {string}')
                self.call(cmd, stdout_to_file=sum_file)
                shutil.copyfile(sum_file, 'SHA256SUMS')

                self.info(f'Sign checksum of {string}')
                self.call(['gpg2', '--yes', '-basu', self.key, sum_file])
                shutil.copyfile(sum_file + '.asc', 'SHA256SUMS.gpg')

    def after_sync_commands(self):
        remote = self._remote
        colon = remote.find(':')
        if colon != -1:
            host = remote[:colon]

            def cmd(command):
                return ['ssh', host, command]
        else:
            host = remote

            def cmd(command):
                return [command]

        for command in self._after_sync_commands:
            self.call(cmd(command))

    def sync(self, create_remote_dirs: bool = False) -> None:
        for images_dir, remote in self.images_dirs_remotes_list():
            if create_remote_dirs:
                os.makedirs(remote, exist_ok=True)
            cmd = [
                'rsync',
                f'{images_dir}/',
                '-rv',
                remote,
            ]
            if not self.no_delete:
                cmd.append('--delete')
            self.call(cmd)

        self.after_sync_commands()
