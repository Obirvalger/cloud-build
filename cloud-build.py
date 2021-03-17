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
    cb = cloud_build.CB(**dict(args._get_kwargs()))
    cb.create_images()
    cb.copy_external_files()
    if not args.no_sign:
        cb.sign()
    cb.sync()


if __name__ == '__main__':
    try:
        main()
    except cloud_build.Error as e:
        print(e, file=sys.stdout)
        exit(1)
