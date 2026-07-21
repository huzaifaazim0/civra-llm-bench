#!/usr/bin/env python3
"""Thin entrypoint: python3 interactive.py  ==  closer_stress.py interactive."""

from closer_stress import main
import sys

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "interactive", *sys.argv[1:]]
    main()
