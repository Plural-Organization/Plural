import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    text = Path(args.path).read_text()
    print(f"{args.path}: {len(text.splitlines())} lines, {len(text.split())} words")


if __name__ == "__main__":
    main()
