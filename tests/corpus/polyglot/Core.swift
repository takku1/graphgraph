func Middle() -> Int {
    return 1
}

func Entry() -> Int {
    return Middle() + Assist()
}

class Service {
    func Handle() -> Int {
        return 2
    }

    func Run() -> Int {
        return self.Handle()
    }
}
