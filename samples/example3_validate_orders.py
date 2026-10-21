def validate_orders(orders, min_amount):
    # flags orders that are invalid or below the minimum amount
    valid_count = 0
    flagged = []
    for order in orders:
        try:
            amount = order["amount"]
            status = order["status"]
            if status == "active":
                if amount >= min_amount or order.get("priority"):
                    valid_count += 1
                else:
                    flagged.append(order["id"])
            elif status == "cancelled":
                continue
            else:
                flagged.append(order["id"])
        except KeyError:
            flagged.append(unknown_id)
    return valid_count, flagged
