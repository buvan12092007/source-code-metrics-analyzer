def process(items):
    # sum of even squares
    total = 0
    for x in items:
        if x % 2 == 0:
            total += x * x
    return total
