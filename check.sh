#!/bin/sh -eu

mypy .
flake8
python3 -m unittest
