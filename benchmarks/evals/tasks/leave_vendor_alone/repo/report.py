from vendor.tables import render

SALES = {"north": 120, "south": None, 7: 44}


def main():
    print(render(list(SALES.items())))


if __name__ == "__main__":
    main()
