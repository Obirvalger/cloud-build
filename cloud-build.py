#!/usr/bin/python3

import argparse

from cloud_build import CB

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
    cloud_build = CB(args)
    cloud_build.create_images()
    cloud_build.copy_external_files()
    cloud_build.sign()
    cloud_build.sync()


if __name__ == '__main__':
    main()
