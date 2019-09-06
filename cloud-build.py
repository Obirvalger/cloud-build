#!/usr/bin/python3

from typing import Dict, List

from pathlib import Path
import argparse
import contextlib
import datetime
import fcntl
import glob
import logging
import os
import re
import subprocess
import sys

import yaml

from cloud_build.test_images import test_image

PROG = 'cloud-build'


class CB:
    """class for building cloud images"""

    def __init__(self, config: str, system_datadir: str) -> None:
        self.parse_config(config)

        data_dir = (Path(os.getenv('XDG_DATA_HOME',
                                   '~/.local/share')).expanduser()
                    / f'{PROG}')
        self.data_dir = data_dir

        self.ensure_run_once()

        self.checksum_command = 'sha256sum'

        self.images_dir = data_dir / 'images'
        self.work_dir = data_dir / 'work'
        self.out_dir = data_dir / 'out'
        self.system_datadir = system_datadir

        self.date = datetime.date.today().strftime('%Y%m%d')
        self.service_default_state = 'enabled'
        self.created_scripts: List[Path] = []

        self.ensure_dirs()
        logging.basicConfig(
            filename=f'{data_dir}/{PROG}.log',
            format='%(levelname)s:%(asctime)s - %(message)s',
        )
        self.log = logging.getLogger(PROG)
        self.log.setLevel(self.log_level)
        self.info(f'Start {PROG}')

    def __del__(self) -> None:
        def unlink(path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

        for name in self.created_scripts:
            unlink(name)
        unlink(self.work_dir / f'mkimage-profiles/conf.d/{PROG}.mk')

        self.info(f'Finish {PROG}')

    def ensure_run_once(self):
        self.lock_file = open(self.data_dir / f'{PROG}.lock', 'w')

        try:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:  # already locked
            print(f'{PROG} already running', file=sys.stderr)
            exit(3)

    @contextlib.contextmanager
    def pushd(self, new_dir):
        previous_dir = os.getcwd()
        self.debug(f'Pushd to {new_dir}')
        os.chdir(new_dir)
        yield
        self.debug(f'Popd from {new_dir}')
        os.chdir(previous_dir)

    def parse_config(self, config: str) -> None:
        with open(config) as f:
            cfg = yaml.safe_load(f)

        self.mkimage_profiles_git = os.path.expanduser(
            cfg.get('mkimage_profiles_git', '')
        )

        self.log_level = getattr(logging, cfg.get('log_level', 'INFO').upper())

        self._repository_url = cfg.get('repository_url',
                                       'file:///space/ALT/{branch}')

        self.bad_arches = cfg.get('bad_arches', [])

        self._packages = cfg.get('packages', {})
        self._services = cfg.get('services', {})
        self._scripts = cfg.get('scripts', {})

        try:
            self._remote = os.path.expanduser(cfg['remote'])
            self.key = cfg['key']
            if isinstance(self.key, int):
                self.key = '{:X}'.format(self.key)
            self._images = cfg['images']
            self._branches = cfg['branches']
            for _, branch in self._branches.items():
                branch['arches'] = {k: {} if v is None else v
                                    for k, v in branch['arches'].items()}
        except KeyError as e:
            msg = f'Required parameter {e} does not set in config'
            print(msg, file=sys.stderr)
            raise Exception(msg)

    def info(self, msg: str) -> None:
        self.log.info(msg)

    def debug(self, msg: str) -> None:
        self.log.debug(msg)

    def error(self, msg: str) -> None:
        self.log.error(msg)
        raise Exception(msg)

    def remote(self, branch: str) -> str:
        return self._remote.format(branch=branch)

    def repository_url(self, branch: str, arch: str) -> str:
        url = self._branches[branch]['arches'][arch].get('repository_url')
        if url is None:
            url = self._branches[branch].get('repository_url',
                                             self._repository_url)
        return url.format(branch=branch, arch=arch)

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
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
                rc = p.wait()
                maybe_fail(string, rc)
                with open(stdout_to_file, 'w') as f:
                    f.write(p.stdout.read().decode())
            else:
                rc = subprocess.call(cmd)
                maybe_fail(string, rc)

    def ensure_dirs(self) -> None:
        for attr in dir(self):
            if attr.endswith('_dir'):
                value = getattr(self, attr)
                if isinstance(value, str):
                    os.makedirs(value, exist_ok=True)
        for branch in self.branches:
            os.makedirs(self.images_dir / branch, exist_ok=True)

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
'''
                    f.write(apt_conf)

                with open(f'{apt_dir}/sources.list.{branch}.{arch}', 'w') as f:
                    sources_list = f'rpm {repo} {arch} classic\n'
                    if arch not in self.bad_arches:
                        sources_list += f'rpm {repo} noarch classic\n'
                    f.write(sources_list)

    def escape_branch(self, branch: str) -> str:
        return re.sub(r'\.', '_', branch)

    def ensure_mkimage_profiles(self, update: bool = False) -> None:
        """Checks that mkimage-profiles exists or clones it"""

        def add_recipe(variable: str, value: str) -> str:
            return f'\n\t@$(call add,{variable},{value})'

        url = self.mkimage_profiles_git
        if url == '':
            url = (
                'git://'
                + 'git.altlinux.org/'
                + 'people/mike/packages/mkimage-profiles.git'
            )
        os.chdir(self.work_dir)
        if os.path.isdir('mkimage-profiles'):
            if update:
                with self.pushd('mkimage-profiles'):
                    self.info('Updating mkimage-profiles')
                    self.call(['git', 'pull'], fail_on_error=False)
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

                        branding = self.branding_by_branch(branch)
                        if branding:
                            branding = f'\n\t@$(call set,BRANDING,{branding})'
                        recipes = [branding]

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

    def branding_by_branch(self, branch: str) -> str:
        return self._branches[branch].get('branding', '')

    def prerequisites_by_branch(self, branch: str) -> List[str]:
        return self._branches[branch].get('prerequisites', [])

    @property
    def images(self) -> List[str]:
        return list(self._images.keys())

    def kinds_by_image(self, image: str) -> List[str]:
        return self._images[image]['kinds']

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

    def packages(self, image: str, branch: str) -> List[str]:
        return self.get_items(self._packages, image, branch)

    def enabled_services(self, image: str, branch: str) -> List[str]:
        return self.get_items(
            self._services,
            image,
            branch,
            'enabled?',
            self.service_default_state,
        )

    def disabled_services(self, image: str, branch: str) -> List[str]:
        return self.get_items(
            self._services,
            image,
            branch,
            'disabled?',
            self.service_default_state,
        )

    def build_tarball(
        self,
        target: str,
        branch: str,
        arch: str,
        kind: str
    ) -> Path:
        self.ensure_mkimage_profiles()

        target = f'{target}_{self.escape_branch(branch)}'
        image = re.sub(r'.*/', '', target)
        full_target = f'{target}.{kind}'
        tarball = self.out_dir / f'{image}-{self.date}-{arch}.{kind}'
        apt_dir = self.work_dir / 'apt'
        with self.pushd(self.work_dir / 'mkimage-profiles'):
            if tarball.exists():
                self.info(f'Skip building of {full_target} {arch}')
            else:
                cmd = [
                    'make',
                    f'APTCONF={apt_dir}/apt.conf.{branch}.{arch}',
                    f'ARCH={arch}',
                    f'IMAGE_OUTDIR={self.out_dir}',
                    full_target,
                ]
                self.info(f'Begin building of {full_target} {arch}')
                self.call(cmd)
                if os.path.exists(tarball):
                    self.info(f'End building of {full_target} {arch}')
                else:
                    self.error(f'Fail building of {full_target} {arch}')

        return tarball

    def image_path(
        self,
        image: str,
        branch: str,
        arch: str,
        kind: str
    ) -> Path:
        path = (
            self.images_dir
            / branch
            / f'alt-{branch.lower()}-{image}-{arch}.{kind}'
        )
        return path

    def copy_image(self, src: Path, dst: Path) -> None:
        os.link(src, dst)

    def clear_imager_dir(self):
        for branch in self.branches:
            directory = self.images_dir / branch
            for path in directory.glob('*'):
                os.unlink(path)

    def remove_old_tarballs(self):
        with self.pushd(self.out_dir):
            for tb in os.listdir():
                if not re.search(f'-{self.date}-', tb):
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

    def create_images(self) -> None:
        self.clear_imager_dir()
        for branch in self.branches:
            for image in self.images:
                self.ensure_scripts(image)
                target = self.target_by_image(image)
                for arch in self.arches_by_branch(branch):
                    if self.skip_arch(image, arch):
                        continue

                    for kind in self.kinds_by_image(image):
                        tarball = self.build_tarball(
                            target, branch, arch, kind,
                        )
                        image_path = self.image_path(image, branch, arch, kind)
                        self.copy_image(tarball, image_path)
                        for test in self.tests_by_image(image):
                            self.info(f'Test {image} {branch} {arch}')
                            if not test_image(
                                image=image_path,
                                branch=branch,
                                arch=arch,
                                **test,
                            ):
                                self.error(f'Test for {image} failed')

        self.remove_old_tarballs()

    def sign(self):
        sum_file = self.checksum_command.upper()
        for branch in self.branches():
            with self.pushd(self.images_dir / branch):
                files = [f
                         for f in os.listdir()
                         if not f.startswith(sum_file)]
                string = ','.join(files)

                cmd = [self.checksum_command] + files
                self.info(f'Calculate checksum of {string}')
                self.call(cmd, stdout_to_file=sum_file)

                self.info(f'Sign checksum of {string}')
                self.call(['gpg2', '--yes', '-basu', self.key, sum_file])

    def kick(self):
        remote = self._remote
        colon = remote.find(':')
        if colon != -1:
            host = remote[:colon]
            self.call(['ssh', host, 'kick'])

    def sync(self) -> None:
        for branch in self.branches:
            remote = self.remote(branch)
            files = glob.glob(f'{self.images_dir}/{branch}/*')
            if f'self.checksum_command.upper().asc' not in files:
                self.error(f'No checksum signature in branch {branch}')
            else:
                cmd = ['rsync', '-v'] + files + [remote]
                self.call(cmd)

        self.kick()


def get_data_dir() -> str:
    data_dir = (os.getenv('XDG_DATA_HOME',
                          os.path.expanduser('~/.local/share'))
                + f'/{PROG}/')
    return data_dir


def parse_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '-c',
        '--config',
        default=f'/etc/{PROG}/config.yaml',
        help='path to config',
    )
    parser.add_argument(
        '-d',
        '--data-dir',
        default=f'/usr/share/{PROG}',
        help='system data directory',
    )
    args = parser.parse_args()

    if not args.data_dir.endswith('/'):
        args.data_dir += '/'

    return args


def main():
    args = parse_args()
    cloud_build = CB(args.config, args.data_dir)
    cloud_build.create_images()
    cloud_build.sign()
    cloud_build.sync()


if __name__ == '__main__':
    main()
