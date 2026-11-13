RATE_PERCENT = 20


def tax_for(cents):
    return cents * RATE_PERCENT // 100
