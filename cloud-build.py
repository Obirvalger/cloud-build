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
        help='list of sipping stages',
    )
    parser.add_argument(
        '--create-remote-dirs',
        action='store_true',
        help='create remote directories',
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

    cb = cloud_build.CB(config=args.config, tasks=args.tasks)
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
