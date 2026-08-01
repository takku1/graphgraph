func Middle() -> Int {
    return 1
}

func Entry() -> Int {
    return Middle() + Assist()
}

class Other {
    func Handle() -> Int {
        return 9
    }
}

class Service {
    func Handle() -> Int {
        return 2
    }

    func Run() -> Int {
        return self.Handle()
    }

    // Precision guard: `other` is not a self-alias, so this must NOT bind to
    // the enclosing Service::Handle.
    func RunOther(other: Other) -> Int {
        return other.Handle()
    }
}
