#!/usr/bin/python3

from collections.abc import Iterable

import argparse
import yaml
import sys

import cloud_build

PROG = 'cloud-build'


def parse_args():
    def is_dict(string):
        raw_dict = dict(yaml.safe_load(string))
        result = {}
        for k, v in raw_dict.items():
            key = k.lower()
            if not isinstance(v, Iterable) or isinstance(v, str):
                result[key] = [v]
            else:
                result[key] = v
        return result

    stages = ['build', 'test', 'copy_external_files', 'sign', 'sync']

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
        '--key',
        help='gpg key to sign',
    )
    parser.add_argument(
        '--patch-mp-prog',
        help='program to change mkimage-profiles code',
    )
    parser.add_argument(
        '--mkimage-profiles-branch',
        help='force using mkimage-profiles from that branch',
    )
    parser.add_argument(
        '--mkimage-profiles-git',
        help='force using mkimage-profiles from that repository',
    )
    parser.add_argument(
        '--remote',
        help='remote to sync images',
    )
    parser.add_argument(
        '--built-images-dir',
        help='path to already built image for stages other then build',
    )
    parser.add_argument(
        '--stages',
        nargs='+',
        default=stages,
        choices=stages,
        help='list of stages',
    )
    parser.add_argument(
        '--skip-stages',
        nargs='+',
        default=[],
        choices=stages,
        help='list of skipping stages',
    )
    parser.add_argument(
        '--create-remote-dirs',
        action='store_true',
        help='create remote directories',
    )
    parser.add_argument(
        '--force-rebuild',
        action='store_true',
        help='forces rebuild',
    )
    parser.add_argument(
        '--no-tests',
        action='store_true',
        help='disable running tests',
    )
    parser.add_argument(
        '--no-sign',
        action='store_true',
        help='disable creating check sum and signing it',
    )
    parser.add_argument(
        '--tasks',
        default={},
        type=is_dict,
        help='add tasks to repositories',
    )
    args = parser.parse_args()

    return args


def main():
    args = parse_args()
    stages = set(args.stages) - set(args.skip_stages)

    config_override = {}

    def args_to_override(key):
        if (value := getattr(args, key)) is not None:
            config_override[key] = value

    if args.force_rebuild:
        config_override['rebuild_after'] = {'days': 0}

    for arg in [
        'key',
        'remote',
        'patch_mp_prog',
        'mkimage_profiles_git',
        'mkimage_profiles_branch',
    ]:
        args_to_override(arg)

    cb = cloud_build.CB(
        config=args.config,
        tasks=args.tasks,
        built_images_dir=args.built_images_dir,
        config_override=config_override,
    )

    if 'build' in stages:
        no_tests = 'test' not in stages
        cb.create_images(no_tests=no_tests)
    if 'copy_external_files' in stages:
        cb.copy_external_files()
    if 'sign' in stages:
        cb.sign()
    if 'sync' in stages:
        cb.sync(create_remote_dirs=args.create_remote_dirs)


if __name__ == '__main__':
    try:
        main()
    except cloud_build.Error as e:
        print(e, file=sys.stdout)
        exit(1)
