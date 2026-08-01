from helper import Assist


def Middle():
    return 1


def Entry():
    return Middle() + Assist()


class Service:
    def Handle(self):
        return 2

    def Run(self):
        return self.Handle()
