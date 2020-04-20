#!/usr/bin/python3

import argparse
import sys

import cloud_build

PROG = 'cloud-build'


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
        '--no-tests',
        action='store_true',
        help='disable running tests',
    )
    args = parser.parse_args()

    return args


def main():
    args = parse_args()
    cb = cloud_build.CB(config=args.config, no_tests=args.no_tests)
    cb.create_images()
    cb.copy_external_files()
    cb.sign()
    cb.sync()


if __name__ == '__main__':
    try:
        main()
    except cloud_build.Error as e:
        print(e, file=sys.stdout)
        exit(1)
