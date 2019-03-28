#!/usr/bin/python3

from typing import List, Optional

import argparse
import contextlib
import datetime
import glob
import logging
import os
import re
import shutil
import subprocess
import sys

import yaml

PROG = 'cloud-build'


class CB:
    """class for building cloud images"""

    def __init__(self, config: str, system_datadir: str) -> None:
        self.parse_config(config)

        data_dir = (os.getenv('XDG_DATA_HOME',
                              os.path.expanduser('~/.local/share'))
                    + f'/{PROG}/')
        self.images_dir = data_dir + 'images/'
        self.work_dir = data_dir + 'work/'
        self.out_dir = data_dir + 'out/'
        self.scripts_dir = data_dir + 'scripts/'
        self.system_datadir = system_datadir

        self.date = datetime.date.today().strftime('%Y%m%d')

        self.ensure_dirs()
        logging.basicConfig(
            filename=f'{data_dir}{PROG}.log',
            format='%(levelname)s:%(asctime)s - %(message)s',
        )
        self.log = logging.getLogger(PROG)
        # self.log.setLevel(logging.DEBUG)
        self.log.setLevel(logging.INFO)
        self.info(f'Start {PROG}')

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
            cfg.get('mkimage_profiles_git')
        )

        try:
            self._remote = os.path.expanduser(cfg['remote'])
            self.key = cfg['key']
            self._images = cfg['images']
            self._branches = cfg['branches']
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

    def run_script(self, name: str, args: Optional[List[str]] = None) -> None:
        path = self.scripts_dir + name
        if not os.path.exists(path):
            system_path = f'{self.system_datadir}scripts/{name}'
            if os.path.exists(system_path):
                shutil.copyfile(system_path, path)
            else:
                msg = f'Required script `{name}` does not exist'
                self.error(msg)
        if not os.access(path, os.X_OK):
            st = os.stat(path)
            os.chmod(path, st.st_mode | 0o111)

        if args is None:
            args = [path]
        else:
            args = [path] + args

        self.call(args)

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
            os.makedirs(self.images_dir + branch, exist_ok=True)

    def ensure_mkimage_profiles(self, update: bool = False) -> None:
        """Checks that mkimage-profiles exists or clones it"""

        url = self.mkimage_profiles_git
        if url is None:
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

        apt_dir = self.work_dir + 'apt'
        if not os.path.isdir(apt_dir):
            self.run_script('gen-apt-files.sh', [apt_dir])

    @property
    def branches(self) -> List[str]:
        return list(self._branches.keys())

    def arches_by_branch(self, branch: str) -> List[str]:
        return self._branches[branch]

    @property
    def images(self) -> List[str]:
        return list(self._images.keys())

    def kinds_by_image(self, image: str) -> List[str]:
        return self._images[image]['kind']

    def target_by_image(self, image: str) -> str:
        return self._images[image]['target']

    def skip_arch(self, image: str, arch: str) -> bool:
        return arch in self._images[image].get('skip_arches', [])

    def build_tarball(
        self,
        target: str,
        branch: str,
        arch: str,
        kind: str
    ) -> str:
        self.ensure_mkimage_profiles()

        image = re.sub(r'.*/', '', target)
        full_target = f'{target}.{kind}'
        tarball = f'{self.out_dir}{image}-{branch}-{self.date}-{arch}.{kind}'
        apt_dir = self.work_dir + 'apt'
        with self.pushd(self.work_dir + 'mkimage-profiles'):
            if os.path.exists(tarball):
                self.info(f'Skip building of {full_target} {branch} {arch}')
            else:
                cmd = [
                    'make',
                    f'APTCONF={apt_dir}/apt.conf.{branch}.{arch}',
                    f'ARCH={arch}',
                    f'IMAGE_OUTDIR={self.out_dir.rstrip("/")}',
                    f'DISTRO_VERSION={branch}',
                    full_target,
                ]
                self.info(f'Begin building of {full_target} {branch} {arch}')
                self.call(cmd)
                if os.path.exists(tarball):
                    self.info(f'End building of {full_target} {branch} {arch}')
                else:
                    self.error(
                        f'Fail building of {full_target} {branch} {arch}'
                    )

        return tarball

    def image_path(self, image: str, branch: str, arch: str, kind: str) -> str:
        path = '{}{}/alt-{}-{}-{}.{}'.format(
            self.images_dir,
            branch,
            branch.lower(),
            image,
            arch,
            kind,
        )
        return path

    def copy_image(self, src: str, dst: str) -> None:
        if os.path.exists(dst):
            os.unlink(dst)
        os.link(src, dst)

    def create_images(self) -> None:
        for branch in self.branches:
            images_in_branch = []
            for image in self.images:
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
                        images_in_branch.append(image_path)
            self.checksum_sign(images_in_branch)

    def checksum_sign(self, images):
        if len(images) == 0:
            self.error('Empty list of images to checksum_sign')

        sum_file = 'SHA256SUM'
        with self.pushd(os.path.dirname(images[0])):
            files = [os.path.basename(x) for x in images]
            string = ','.join(files)

            cmd = ['sha256sum'] + files
            self.info(f'Calculate checksum of {string}')
            self.call(cmd, stdout_to_file=sum_file)

            self.info(f'Sign checksum of {string}')
            self.call(['gpg2', '--yes', '-basu', self.key, sum_file])

    def sync(self) -> None:
        self.create_images()
        for branch in self.branches:
            remote = self.remote(branch)
            files = glob.glob(f'{self.images_dir}{branch}/*')
            cmd = ['rsync', '-v'] + files + [remote]
            self.call(cmd)

        self.call(['ssh', 'proto', 'kick'])


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
    cloud_build.sync()


if __name__ == '__main__':
    main()
