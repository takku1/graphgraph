from helper import Assist

def Leaf():
    return 0

def Bonus():
    return 2

def Middle():
    return Leaf()

class Engine:
    def Run(self):
        return Leaf()

def Recurse(n):
    if n <= 0:
        return 0
    return Recurse(n - 1)

def Root():
    e = Engine()
    return Middle() + Bonus() + Assist() + e.Run()
