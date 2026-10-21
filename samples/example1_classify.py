def classify(n):
    if n > 0:
        if n % 2 == 0:
            return "pos-even"
        return "pos-odd"
    return "non-positive"
