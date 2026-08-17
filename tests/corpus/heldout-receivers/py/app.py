from user import Account


def persist(account: Account) -> int:
    return account.save()
